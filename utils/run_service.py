import hashlib
import json
import logging
import os
import time
from copy import deepcopy
from functools import lru_cache
from uuid import uuid4
from datetime import datetime, timezone

from utils.bi_service import BIService, validate_plan
from utils.config_manager import ConfigManager
from utils.run_store import RunStore, utcnow
from utils.execution import TERMINAL, STEP_TERMINAL, execute_dag, outcome
from utils.resources import BusyError, run_queue
from utils.run_context import FrozenConfig, snapshot_config, step_compatible

logger = logging.getLogger(__name__)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def elapsed_since(timestamp):
    return max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds())


class RunService:
    def __init__(self, store=None, config=None, service_factory=BIService):
        self.store = store or RunStore()
        self.config = config or ConfigManager()
        self.service_factory = service_factory

    def submit(self, question, database="mysql", session_id=None, submission_id=None,
               plan=None, parent_run_id=None, reuse=None, datasource_ids=None):
        if not question.strip():
            raise ValueError("Question cannot be empty")
        if plan is not None:
            plan = validate_plan(plan)
        run_id = uuid4().hex
        requested_session = session_id
        session_id = session_id or uuid4().hex
        snapshot = snapshot_config(self.config)
        state = {"run_id": run_id, "session_id": session_id, "parent_run_id": parent_run_id,
                 "question": question, "database": database, "status": "QUEUED",
                 "phase": "UNDERSTAND", "plan": plan, "plan_version": 1, "steps": reuse or {},
                 "request": None, "created_at": utcnow(), "updated_at": utcnow(),
                 "answer_sufficiency": None, "event_seq": 0, "active_seconds": 0,
                 "limits": {"max_steps": 30, "active_seconds": 300, "tool_calls": 64,
                            "model_calls": 32, "replans": 2, "stagnation": 2},
                 "source_version": fingerprint(snapshot), "cancel_capability": "cooperative"}
        state.update(queued_at=state["created_at"], queue_seconds=0, waiting_seconds=0)
        identifiers = datasource_ids or [database]
        state["datasource_ids"] = list(dict.fromkeys(identifiers))
        previous = next((run for run in self.store.history(session_id)
                         if run["database"] == database and run["status"] == "SUCCEEDED"
                         and run.get("datasource_ids") == state["datasource_ids"]
                         and run["source_version"] == state["source_version"]
                         and run.get("understanding")), None)
        state["context"] = deepcopy(previous["understanding"]["slots"]) if previous else {}
        state["available_results"] = ([f"{previous['run_id']}:{key}" for key, step in previous["steps"].items()
                                       if step["status"] == "SUCCEEDED"] if previous else [])
        private = {"snapshot": snapshot,
                   "submission_input": {"question": question, "database": database, "plan": plan,
                                        "datasource_ids": state["datasource_ids"], "session_id": requested_session}}
        state, created = self.store.create(state, private, submission_id or uuid4().hex)
        if created:
            self.store.update(run_id, lambda s: None, "submitted")
        return self.store.get(state["run_id"])

    def start(self, run_id):
        if self.store.status(run_id) == "QUEUED":
            try:
                future = run_queue.submit((str(self.store.path), run_id), self.execute, run_id)
            except BusyError as exc:
                def reject(s):
                    if s["status"] == "QUEUED":
                        s.update(status="FAILED", error=str(exc))
                self.store.update(run_id, reject, "admission_rejected", {"reason": str(exc)})
                exc.run_id = run_id
                raise
            future.add_done_callback(lambda completed: self._restart_if_queued(run_id))

    def _restart_if_queued(self, run_id):
        if self.store.status(run_id) == "QUEUED":
            self.start(run_id)

    def _waiting(self, run_id, kind, prompt, step_id=None):
        request = {"request_id": uuid4().hex, "request_kind": kind, "prompt": prompt,
                   "step_id": step_id, "plan_version": self.store.get(run_id)["plan_version"]}
        def change(s):
            if s["status"] in TERMINAL:
                return
            if s["status"] == "CANCELLING":
                s.update(status="CANCELLED", owner=None)
                return
            s.update(status="WAITING_INPUT", request=request, owner=None, waiting_at=utcnow())
        self.store.update(run_id, change, "input_requested", request)

    def respond(self, run_id, request_id, plan_version, response):
        state = self.store.get(run_id)
        request = state.get("request")
        artifact = None
        if request and request["request_kind"] == "clarification" and response.strip():
            artifact = uuid4().hex
        def change(s):
            request = s["request"]
            if (s["status"] != "WAITING_INPUT" or not request
                    or request["request_id"] != request_id or s["plan_version"] != plan_version):
                raise ValueError("Stale or mismatched input response")
            if request["request_kind"] == "plan_confirmation":
                if response != "confirm":
                    raise ValueError("Plan confirmation requires 'confirm'; edit plans explicitly")
            else:
                if not response.strip():
                    raise ValueError("Clarification response cannot be empty")
                if request["request_kind"] == "understanding":
                    s["clarification_response"] = response
                    s.pop("understanding", None)
                else:
                    s["steps"][str(request["step_id"])] = {"status": "SUCCEEDED", "artifact_id": artifact,
                                                           "validity": "CURRENT"}
            s.update(status="QUEUED", request=None, confirmed=True, queued_at=utcnow(),
                     waiting_seconds=s.get("waiting_seconds", 0) + elapsed_since(s.get("waiting_at", s["updated_at"])))
        return self.store.update(run_id, change, "input_received", {"request_id": request_id},
                                 artifact=(artifact, {"status": "success", "evidence_class": "user_input",
                                                      "data": response}) if artifact else None)

    def revise(self, run_id, plan, request_id, plan_version):
        plan = validate_plan(plan)
        def change(s):
            if (s["status"] != "WAITING_INPUT" or s["request"]["request_id"] != request_id
                    or s["plan_version"] != plan_version
                    or s["request"]["request_kind"] != "plan_confirmation"):
                raise ValueError("Plan cannot be edited at this checkpoint")
            s.update(plan=plan, plan_version=plan_version + 1, steps={})
            s["request"].update(request_id=uuid4().hex, plan_version=s["plan_version"])
        return self.store.update(run_id, change, "plan_revised")

    def cancel(self, run_id):
        def change(s):
            if s["status"] in TERMINAL | {"CANCELLING"}:
                return
            s["status"] = "CANCELLING" if s["status"] == "RUNNING" else "CANCELLED"
            s["request"] = None
        state = self.store.update(run_id, change, "cancel_requested")
        if state["status"] == "CANCELLED":
            run_queue.cancel((str(self.store.path), run_id))
        return state

    def _cancel_at_checkpoint(self, run_id):
        status = self.store.status(run_id)
        if status == "CANCELLING":
            def stop(s):
                if s["status"] == "CANCELLING":
                    s.update(status="CANCELLED", owner=None, request=None)
            status = self.store.update(run_id, stop, "run_cancelled")["status"]
        return status in TERMINAL

    def recover(self, run_id):
        def change(s):
            if s["status"] not in {"RUNNING", "CANCELLING"}:
                if s["status"] in {"QUEUED", "WAITING_INPUT"}:
                    return
                raise ValueError("Terminal runs cannot be resumed; retry creates a new run")
            owner = s.get("owner")
            if owner:
                try:
                    os.kill(owner, 0)
                except ProcessLookupError:
                    pass
                except PermissionError as exc:
                    raise ValueError("Cannot verify that the execution owner has exited") from exc
                else:
                    raise ValueError("Execution owner is still alive")
            for step in s["steps"].values():
                if step["status"] == "RUNNING":
                    step.update(status="PENDING", attempt_id=None)
            s.update(status="CANCELLED" if s["status"] == "CANCELLING" else "QUEUED",
                     owner=None, queued_at=utcnow())
        return self.store.update(run_id, change, "recovered")

    def retry(self, run_id, refresh=False):
        previous = self.store.get(run_id)
        if previous["status"] not in TERMINAL:
            raise ValueError("Only terminal runs can be retried")
        current = snapshot_config(self.config)
        original = self.store.get(run_id, private=True)["snapshot"]
        reuse, payloads = {}, {}
        if not refresh and previous["plan"]:
            for definition in validate_plan(previous["plan"])["steps"]:
                key = str(definition["step_id"])
                step = previous["steps"].get(key, {})
                dependencies = definition["dependencies"] + definition["optional_dependencies"]
                if (step.get("status") == "SUCCEEDED" and step.get("validity") == "CURRENT"
                        and (previous["source_version"] == fingerprint(current)
                             or step_compatible(definition, original, current))
                        and all(str(ref) in reuse for ref in dependencies)):
                    result = self.store.artifact(run_id, step["artifact_id"])
                    reuse[key] = dict(step)
                    reuse[key].update(attempt_id=None, reused_from=run_id)
                    payloads[key] = result
        result = self.submit(previous["question"], previous["database"], previous["session_id"],
                             plan=previous["plan"], parent_run_id=run_id,
                             datasource_ids=previous.get("datasource_ids"))
        for key in reuse:
            artifact = self.store.put_artifact(result["run_id"], payloads[key])
            reuse[key]["artifact_id"] = artifact
        def inherit(s):
            s["steps"] = reuse
            for key in ("understanding", "normalized_question", "context", "available_results", "analysis_mode"):
                if key in previous:
                    s[key] = deepcopy(previous[key])
            if previous.get("analysis_mode"):
                s["ledger"] = {"goal": previous["question"], "constraints": previous.get("context", {}),
                               "round": 0, "replans": 0, "stagnation": 0, "evidence_fingerprints": [],
                               "progress": [], "unknown": [], "hypotheses": []}
        self.store.update(result["run_id"], inherit, "retry_created", {"parent_run_id": run_id, "refresh": refresh})
        return self.store.get(result["run_id"])

    def execute(self, run_id):
        claimed = False
        def claim(s):
            nonlocal claimed
            if s["status"] == "QUEUED":
                s.update(status="RUNNING", owner=os.getpid(), queue_seconds=s.get("queue_seconds", 0)
                         + elapsed_since(s.get("queued_at", s["created_at"])))
                claimed = True
        self.store.update(run_id, claim, "start_requested")
        if not claimed:
            return
        started = time.monotonic()
        try:
            if self._cancel_at_checkpoint(run_id):
                return
            state = self.store.get(run_id)
            snapshot = self.store.get(run_id, private=True)["snapshot"]
            service = self.service_factory(config_manager=FrozenConfig(snapshot))
            if isinstance(service, BIService):
                from utils.tool_execution import ToolInvoker
                service._invoker = ToolInvoker(service.config, service.mcp, service.tools,
                                                state["datasource_ids"], self.config)
                service._invoker.cancelled = lambda: self.store.status(run_id) in {"CANCELLING", "CANCELLED"}
                service.router.max_calls = state["limits"]["model_calls"] - len(state.get("model_calls", []))
                service.router.deadline = started + state["limits"]["active_seconds"] - state["active_seconds"]
                service._invoker.deadline = service.router.deadline
                service.tools.max_calls = state["limits"]["tool_calls"] - len(state.get("tool_records", []))
            if state["plan"] is None:
                understanding = state.get("understanding")
                if understanding is None:
                    question = state["question"]
                    if state.get("clarification_response"):
                        question += "\nUser clarification: " + state["clarification_response"]
                    understanding = service.understand(question, state["database"], state["context"],
                                                        state["created_at"], state.get("available_results", []),
                                                        state["datasource_ids"])
                    self.store.update(run_id, lambda s: s.update(
                        understanding=understanding, normalized_question=understanding["normalized_question"],
                        phase="BIND"), "question_understood", understanding)
                if self._cancel_at_checkpoint(run_id):
                    return
                if understanding.get("clarification"):
                    self._waiting(run_id, "understanding", understanding["clarification"])
                    return
                intent = understanding["intent"]
                if intent == "reject":
                    raise ValueError("Only read-only analysis is supported")
                if intent == "concept":
                    result = service.explain(state["question"])
                    artifact = self.store.put_artifact(run_id, result)
                    def answered(s):
                        if s["status"] in TERMINAL:
                            return
                        cancelled = s["status"] == "CANCELLING"
                        s.update(status="CANCELLED" if cancelled else "SUCCEEDED", phase="RENDER", owner=None,
                                 answer_sufficiency=None if cancelled else result["answer_sufficiency"],
                                 steps={"knowledge": {"status": "SUCCEEDED", "artifact_id": artifact,
                                                      "validity": "CURRENT"}})
                    self.store.update(run_id, answered, "knowledge_answered")
                    return
                if intent == "analysis" or understanding.get("requires_plan"):
                    plan = service.analysis_plan(understanding["normalized_question"], state["database"],
                                                 datasource_ids=state["datasource_ids"])
                    self.store.update(run_id, lambda s: s.update(plan=plan, phase="PLAN"), "plan_created")
                    self.store.update(run_id, lambda s: s.update(analysis_mode=True, ledger={
                        "goal": state["question"], "constraints": understanding["slots"],
                        "hypotheses": [], "unknown": [], "round": 0, "replans": 0, "stagnation": 0,
                        "evidence_fingerprints": [], "progress": [],
                    }))
                    self._waiting(run_id, "plan_confirmation", "Confirm the proposed analysis plan")
                    return
                plan = validate_plan({"steps": [{"step_id": 1, "step_type": "sql_query",
                                                 "description": state["question"]}]})
                self.store.update(run_id, lambda s: s.update(plan=plan), "plan_created")
            if self.store.get(run_id).get("analysis_mode"):
                self._analysis(run_id, service, started)
            else:
                self._dag(run_id, service, started)
        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            def failed(s):
                if s["status"] not in TERMINAL:
                    s.update(status="CANCELLED" if s["status"] == "CANCELLING" else "FAILED",
                             error=str(exc), owner=None)
            self.store.update(run_id, failed, "run_failed", {"error": str(exc)})
        finally:
            if "service" in locals() and isinstance(service, BIService):
                service.close()
            records = getattr(service.router, "records", []) if "service" in locals() else []
            if not isinstance(records, list):
                records = []
            tool_records = service.tools.records if "service" in locals() and isinstance(service, BIService) else []
            self.store.update(run_id, lambda s: s.update(
                active_seconds=s["active_seconds"] + time.monotonic() - started,
                model_calls=s.get("model_calls", []) + records,
                tool_records=s.get("tool_records", []) + tool_records))

    def _dag(self, run_id, service, started):
        state = self.store.get(run_id)
        plan = validate_plan(state["plan"])
        if isinstance(service, BIService):
            plan = service.bind_plan(plan, state["database"], state["datasource_ids"])
            self.store.update(run_id, lambda s: s.update(
                plan=plan, tool_catalog_version=service.invoker.catalog.version))
        if isinstance(service, BIService) and any(s["step_type"] == "sql_query" for s in plan["steps"]):
            allowed = {service.config.resolve_datasource(ref)["datasource_id"] for ref in state["datasource_ids"]}
            for step in plan["steps"]:
                if step["step_type"] == "sql_query":
                    target = service.config.resolve_datasource(step.get("datasource_id", state["database"]))
                    if target["datasource_id"] not in allowed:
                        raise ValueError("Plan references a datasource outside the frozen active set")
                    step["datasource_id"] = target["datasource_id"]
            self.store.update(run_id, lambda s: s.update(plan=plan))
        def request_input(step):
            self._waiting(run_id, "clarification", step.get("description", "Provide input"), step["step_id"])
            return True
        execute_dag(self.store, run_id, service, started, request_input)
        if not self.store.get(run_id).get("analysis_mode"):
            if self.store.status(run_id) != "WAITING_INPUT":
                self._finish(run_id, len(plan["steps"]))

    def _finish(self, run_id, total):
        def finish(s):
            if s["status"] in TERMINAL:
                return
            successes = sum(item["status"] == "SUCCEEDED" for item in s["steps"].values())
            status = outcome(s)
            s.update(status=status, phase="RENDER", owner=None,
                     answer_sufficiency=s.get("answer_sufficiency") or ("QUALIFIED" if successes else "INSUFFICIENT"))
        self.store.update(run_id, finish, "run_finished")

    def _analysis(self, run_id, service, started):
        from utils.analysis import evidence_content
        while True:
            self._dag(run_id, service, started)
            state = self.store.get(run_id)
            if state["status"] == "WAITING_INPUT":
                return
            if state["status"] in TERMINAL | {"CANCELLING"}:
                self._finish(run_id, len(state["plan"]["steps"]))
                return
            results = {int(key): self.store.artifact(run_id, step["artifact_id"])
                       for key, step in state["steps"].items() if step["status"] == "SUCCEEDED"}
            if not results:
                self._finish(run_id, len(state["plan"]["steps"]))
                return
            model_records = service.router.records if isinstance(service, BIService) else []
            exhausted = (time.monotonic() - started + state["active_seconds"] >= state["limits"]["active_seconds"]
                         or len(model_records) + len(state.get("model_calls", [])) >= state["limits"]["model_calls"])
            if exhausted:
                self.store.update(run_id, lambda s: s.update(
                    report="Execution budget exhausted. Available results are retained; evidence remains limited.",
                    answer_sufficiency="INSUFFICIENT"), "budget_exhausted")
                self._finish(run_id, len(state["plan"]["steps"]))
                return
            ledger = deepcopy(state["ledger"])
            prints = sorted({fingerprint(evidence_content(result.get("data"))) for result in results.values()})
            new = sorted(set(prints) - set(ledger["evidence_fingerprints"]))
            ledger["stagnation"] = 0 if new else ledger["stagnation"] + 1
            ledger["round"] += 1
            ledger["evidence_fingerprints"] = sorted(set(ledger["evidence_fingerprints"]) | set(prints))
            self.store.update(run_id, lambda s: s.update(phase="ASSESS"), "phase_changed", {"phase": "ASSESS"})
            package = service.assess(state.get("normalized_question", state["question"]), results, ledger)
            ledger.update(hypotheses=package["hypotheses"], unknown=package["gaps"])
            ledger["progress"].append({"round": ledger["round"], "new_evidence": len(new),
                                       "remaining_gaps": package["gaps"]})
            stopped = (not package["next_plan"] or package["premise"] == "REFUTED"
                       or ledger["replans"] >= state["limits"]["replans"]
                       or ledger["stagnation"] >= state["limits"]["stagnation"]
                       or time.monotonic() - started + state["active_seconds"] >= state["limits"]["active_seconds"])
            self.store.update(run_id, lambda s: s.update(ledger=ledger, conclusion=package,
                                                        answer_sufficiency=package["answer_sufficiency"]),
                              "evidence_assessed", {"premise": package["premise"],
                                                    "sufficiency": package["answer_sufficiency"], "new_evidence": len(new)})
            if stopped:
                if package["next_plan"]:
                    package["gaps"].append("Analysis stopped at the configured progress or execution budget.")
                    package["next_plan"] = None
                self.store.update(run_id, lambda s: s.update(phase="SYNTHESIZE", conclusion=package))
                if self.store.status(run_id) == "CANCELLING":
                    self._finish(run_id, len(state["plan"]["steps"]))
                    return
                report = service.present(package)
                self.store.update(run_id, lambda s: s.update(report=report), "answer_rendered")
                self._finish(run_id, len(state["plan"]["steps"]))
                return
            ledger["replans"] += 1
            self._replace_plan(run_id, service.bind_plan(
                package["next_plan"], state["database"], state["datasource_ids"])
                if isinstance(service, BIService) else package["next_plan"], ledger)

    def _replace_plan(self, run_id, plan, ledger):
        plan = validate_plan(plan)
        old = self.store.get(run_id)
        old_steps = {step["step_id"]: step for step in old["plan"]["steps"]}
        reusable = set()
        steps = {}
        for step in plan["steps"]:
            key = str(step["step_id"])
            previous = old["steps"].get(key, {})
            dependencies = step["dependencies"] + step["optional_dependencies"]
            if (old_steps.get(step["step_id"]) == step and set(dependencies) <= reusable
                    and previous.get("status") == "SUCCEEDED" and previous.get("validity") == "CURRENT"):
                reusable.add(step["step_id"])
                steps[key] = previous
            elif previous.get("artifact_id"):
                steps[key] = {**previous, "status": "PENDING", "validity": "STALE", "attempt_count": 0}
        def change(s):
            if s["status"] == "CANCELLING":
                return
            s.setdefault("plan_history", []).append({"plan": s["plan"], "steps": s["steps"],
                                                     "version": s["plan_version"]})
            s.update(plan=plan, plan_version=s["plan_version"] + 1, steps=steps, ledger=ledger, phase="VALIDATE")
        self.store.update(run_id, change, "plan_revised", {
            "reason": ledger["unknown"], "reused_steps": sorted(reusable),
            "added": sorted({s["step_id"] for s in plan["steps"]} - set(old_steps)),
            "removed": sorted(set(old_steps) - {s["step_id"] for s in plan["steps"]})})

    def refine(self, run_id, request_id, plan_version, feedback):
        if not feedback.strip():
            raise ValueError("Plan feedback cannot be empty")
        state = self.store.get(run_id)
        if (state["status"] != "WAITING_INPUT" or state["request"]["request_id"] != request_id
                or state["plan_version"] != plan_version):
            raise ValueError("Stale plan feedback")
        snapshot = self.store.get(run_id, private=True)["snapshot"]
        service = self.service_factory(config_manager=FrozenConfig(snapshot))
        started = time.monotonic()
        if isinstance(service, BIService):
            from utils.tool_execution import ToolInvoker
            service._invoker = ToolInvoker(service.config, service.mcp, service.tools,
                                            state["datasource_ids"], self.config)
            service.router.max_calls = state["limits"]["model_calls"] - len(state.get("model_calls", []))
            service.router.deadline = started + state["limits"]["active_seconds"] - state["active_seconds"]
            service._invoker.deadline = service.router.deadline
            service.tools.max_calls = state["limits"]["tool_calls"] - len(state.get("tool_records", []))
        try:
            plan = service.analysis_plan(state.get("normalized_question", state["question"]), state["database"],
                                         state["plan"], feedback, state["datasource_ids"])
            return self.revise(run_id, plan, request_id, plan_version)
        finally:
            if isinstance(service, BIService):
                service.close()
            records = service.router.records if isinstance(service, BIService) else []
            self.store.update(run_id, lambda s: s.update(
                active_seconds=s["active_seconds"] + time.monotonic() - started,
                model_calls=s.get("model_calls", []) + records,
                tool_records=s.get("tool_records", []) + (service.tools.records if isinstance(service, BIService) else [])))


@lru_cache(maxsize=1)
def get_run_service():
    return RunService()
