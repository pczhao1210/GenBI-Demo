import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from functools import lru_cache
from uuid import uuid4

from utils.bi_service import BIService, validate_plan
from utils.config_manager import ConfigManager
from utils.run_store import RunStore, utcnow

TERMINAL = {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}
STEP_TERMINAL = {"SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED", "CANCELLED"}
logger = logging.getLogger(__name__)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot_config(config):
    sources = config.load_datasources()
    return {"databases": config.load_database_config(), "schemas": config.load_schema_config(),
            "llm": config.load_llm_config(), "mcp": config.load_mcp_config(), "sources": sources,
            "semantics": config.load_semantics(), "knowledge": config.load_knowledge(),
            "model_roles": config.load_model_roles()}


class FrozenConfig:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def load_database_config(self):
        return deepcopy(self.snapshot["databases"])

    def load_schema_config(self):
        return deepcopy(self.snapshot["schemas"])

    def load_llm_config(self):
        return deepcopy(self.snapshot["llm"])

    def load_mcp_config(self):
        return deepcopy(self.snapshot["mcp"])

    def load_datasources(self):
        return deepcopy(self.snapshot["sources"])

    def resolve_datasource(self, identifier):
        from utils.datasources import resolve_source
        return resolve_source(self.load_datasources(), identifier)

    def load_semantics(self):
        return deepcopy(self.snapshot["semantics"])

    def load_knowledge(self):
        return deepcopy(self.snapshot["knowledge"])

    def load_model_roles(self):
        return deepcopy(self.snapshot["model_roles"])


class RunService:
    def __init__(self, store=None, config=None, service_factory=BIService):
        self.store = store or RunStore()
        self.config = config or ConfigManager()
        self.service_factory = service_factory
        self._threads = {}
        self._lock = threading.Lock()

    def submit(self, question, database="mysql", session_id=None, submission_id=None,
               plan=None, parent_run_id=None, reuse=None):
        if not question.strip():
            raise ValueError("Question cannot be empty")
        if plan is not None:
            plan = validate_plan(plan)
        run_id = uuid4().hex
        session_id = session_id or uuid4().hex
        snapshot = snapshot_config(self.config)
        state = {"run_id": run_id, "session_id": session_id, "parent_run_id": parent_run_id,
                 "question": question, "database": database, "status": "QUEUED",
                 "phase": "UNDERSTAND", "plan": plan, "plan_version": 1, "steps": reuse or {},
                 "request": None, "created_at": utcnow(), "updated_at": utcnow(),
                 "answer_sufficiency": None, "event_seq": 0, "active_seconds": 0,
                 "limits": {"max_steps": 30, "active_seconds": 300},
                 "source_version": fingerprint(snapshot), "cancel_capability": "cooperative"}
        previous = next((run for run in self.store.history(session_id)
                         if run["database"] == database and run["status"] == "SUCCEEDED"
                         and run.get("understanding")), None)
        state["context"] = deepcopy(previous["understanding"]["slots"]) if previous else {}
        private = {"snapshot": snapshot,
                   "submission_input": {"question": question, "database": database, "plan": plan}}
        state, created = self.store.create(state, private, submission_id or uuid4().hex)
        if created:
            self.store.update(run_id, lambda s: None, "submitted")
        return self.store.get(state["run_id"])

    def start(self, run_id):
        with self._lock:
            if run_id in self._threads and self._threads[run_id].is_alive():
                return
            thread = threading.Thread(target=self.execute, args=(run_id,), daemon=True)
            self._threads[run_id] = thread
            thread.start()

    def _waiting(self, run_id, kind, prompt, step_id=None):
        request = {"request_id": uuid4().hex, "request_kind": kind, "prompt": prompt,
                   "step_id": step_id, "plan_version": self.store.get(run_id)["plan_version"]}
        def change(s):
            if s["status"] == "CANCELLING":
                s["status"] = "CANCELLED"
                return
            s.update(status="WAITING_INPUT", request=request, owner=None)
        self.store.update(run_id, change, "input_requested", request)

    def respond(self, run_id, request_id, plan_version, response):
        state = self.store.get(run_id)
        request = state.get("request")
        artifact = None
        if request and request["request_kind"] != "plan_confirmation" and response.strip():
            artifact = self.store.put_artifact(run_id, {"status": "success", "data": response})
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
            s.update(status="QUEUED", request=None, confirmed=True)
        return self.store.update(run_id, change, "input_received", {"request_id": request_id})

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
            if s["status"] in TERMINAL:
                return
            s["status"] = "CANCELLING" if s["status"] == "RUNNING" else "CANCELLED"
            s["request"] = None
        return self.store.update(run_id, change, "cancel_requested")

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
                else:
                    raise ValueError("Execution owner is still alive")
            for step in s["steps"].values():
                if step["status"] == "RUNNING":
                    step.update(status="PENDING", attempt_id=None)
            s.update(status="CANCELLED" if s["status"] == "CANCELLING" else "QUEUED", owner=None)
        return self.store.update(run_id, change, "recovered")

    def retry(self, run_id, refresh=False):
        previous = self.store.get(run_id)
        if previous["status"] not in TERMINAL:
            raise ValueError("Only terminal runs can be retried")
        current = snapshot_config(self.config)
        reuse, payloads = {}, {}
        if not refresh and previous["source_version"] == fingerprint(current):
            for key, step in previous["steps"].items():
                if step["status"] == "SUCCEEDED" and step.get("validity") == "CURRENT":
                    result = self.store.artifact(run_id, step["artifact_id"])
                    reuse[key] = dict(step)
                    payloads[key] = result
        result = self.submit(previous["question"], previous["database"], previous["session_id"],
                             plan=previous["plan"], parent_run_id=run_id, reuse=reuse)
        for key in reuse:
            artifact = self.store.put_artifact(result["run_id"], payloads[key])
            self.store.update(result["run_id"],
                              lambda s, k=key, a=artifact: s["steps"][k].update(artifact_id=a))
        return self.store.get(result["run_id"])

    def execute(self, run_id):
        claimed = False
        def claim(s):
            nonlocal claimed
            if s["status"] == "QUEUED":
                s.update(status="RUNNING", owner=os.getpid())
                claimed = True
        self.store.update(run_id, claim, "start_requested")
        if not claimed:
            return
        started = time.monotonic()
        try:
            state = self.store.get(run_id)
            snapshot = self.store.get(run_id, private=True)["snapshot"]
            service = self.service_factory(config_manager=FrozenConfig(snapshot))
            if state["plan"] is None:
                understanding = state.get("understanding")
                if understanding is None:
                    question = state["question"]
                    if state.get("clarification_response"):
                        question += "\nUser clarification: " + state["clarification_response"]
                    understanding = service.understand(question, state["database"], state["context"], state["created_at"])
                    self.store.update(run_id, lambda s: s.update(
                        understanding=understanding, normalized_question=understanding["normalized_question"],
                        phase="BIND"), "question_understood", understanding)
                if understanding.get("clarification"):
                    self._waiting(run_id, "understanding", understanding["clarification"])
                    return
                intent = understanding["intent"]
                if intent == "reject":
                    raise ValueError("Only read-only analysis is supported")
                if intent == "concept":
                    result = service.explain(state["question"])
                    artifact = self.store.put_artifact(run_id, result)
                    self.store.update(run_id, lambda s: s.update(
                        status="SUCCEEDED", phase="RENDER", owner=None,
                        answer_sufficiency=result["answer_sufficiency"],
                        steps={"knowledge": {"status": "SUCCEEDED", "artifact_id": artifact, "validity": "CURRENT"}}),
                        "knowledge_answered")
                    return
                if intent == "analysis":
                    plan = service.analysis_plan(understanding["normalized_question"], state["database"])
                    self.store.update(run_id, lambda s: s.update(plan=plan, phase="PLAN"), "plan_created")
                    self._waiting(run_id, "plan_confirmation", "Confirm the proposed analysis plan")
                    return
                plan = validate_plan({"steps": [{"step_id": 1, "step_type": "sql_query",
                                                 "description": state["question"]}]})
                self.store.update(run_id, lambda s: s.update(plan=plan), "plan_created")
            self._dag(run_id, service, started)
        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            self.store.update(run_id, lambda s: s.update(
                status="CANCELLED" if s["status"] == "CANCELLING" else "FAILED",
                error=str(exc), owner=None), "run_failed", {"error": str(exc)})
        finally:
            records = getattr(service.router, "records", []) if "service" in locals() else []
            if not isinstance(records, list):
                records = []
            self.store.update(run_id, lambda s: s.update(
                active_seconds=s["active_seconds"] + time.monotonic() - started,
                model_calls=s.get("model_calls", []) + records))

    def _dag(self, run_id, service, started):
        self.store.update(run_id, lambda s: s.update(phase="EXECUTE"), "phase_changed",
                          {"phase": "EXECUTE"})
        state = self.store.get(run_id)
        plan = validate_plan(state["plan"])
        if len(plan["steps"]) > state["limits"]["max_steps"]:
            raise ValueError("Plan exceeds step budget")
        futures = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            while True:
                state = self.store.get(run_id)
                cancelled = state["status"] == "CANCELLING"
                exhausted = (state["active_seconds"] + time.monotonic() - started
                             > state["limits"]["active_seconds"])
                for step in plan["steps"]:
                    key = str(step["step_id"])
                    existing = state["steps"].get(key, {})
                    if existing.get("status") in STEP_TERMINAL | {"RUNNING"}:
                        continue
                    dependencies = [state["steps"].get(str(ref), {}) for ref in step["dependencies"]]
                    optional = [state["steps"].get(str(ref), {}) for ref in step["optional_dependencies"]]
                    if cancelled or exhausted:
                        self._step_state(run_id, key, {"status": "CANCELLED" if cancelled else "BLOCKED",
                                                       "error": "Cancelled" if cancelled else "Active time budget exhausted"})
                    elif any(item.get("status") in STEP_TERMINAL - {"SUCCEEDED"} for item in dependencies):
                        self._step_state(run_id, key, {"status": "BLOCKED", "error": "Required dependency failed"})
                    elif all(item.get("status") == "SUCCEEDED" for item in dependencies) and all(
                            item.get("status") in STEP_TERMINAL for item in optional):
                        if step["step_type"] == "user_input":
                            if futures:
                                continue
                            self._waiting(run_id, "clarification", step.get("description", "Provide input"),
                                          step["step_id"])
                            return
                        inputs = {}
                        for ref in step["dependencies"] + step["optional_dependencies"]:
                            item = state["steps"][str(ref)]
                            inputs[ref] = (self.store.artifact(run_id, item["artifact_id"])
                                           if item["status"] == "SUCCEEDED"
                                           else {"status": "error", "message": item.get("error")})
                        attempt = uuid4().hex
                        self._step_state(run_id, key, {"status": "RUNNING", "attempt_id": attempt,
                                                       "validity": "CURRENT"})
                        future = pool.submit(service.execute_step, step, state.get("normalized_question", state["question"]),
                                             step.get("datasource_id", state["database"]), inputs)
                        futures[future] = (key, attempt, state["plan_version"])
                if not futures:
                    state = self.store.get(run_id)
                    if all(s.get("status") in STEP_TERMINAL for s in state["steps"].values()):
                        break
                    continue
                done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    key, attempt, version = futures.pop(future)
                    try:
                        payload = future.result()
                        if not isinstance(payload, dict) or payload.get("status") != "success":
                            raise RuntimeError("Tool returned an invalid or unsuccessful result")
                        artifact = self.store.put_artifact(run_id, payload)
                        result = {"status": "SUCCEEDED", "artifact_id": artifact, "validity": "CURRENT"}
                    except Exception as exc:
                        logger.exception("Run %s step %s failed", run_id, key)
                        result = {"status": "FAILED", "error": str(exc), "validity": "CURRENT"}
                    def merge(s):
                        if (s["plan_version"] == version and
                                s["steps"][key].get("attempt_id") == attempt):
                            s["steps"][key].update(result)
                    self.store.update(run_id, merge, "step_finished",
                                      {"step_id": key, "attempt_id": attempt, **result})
        def finish(s):
            successes = sum(item["status"] == "SUCCEEDED" for item in s["steps"].values())
            status = ("CANCELLED" if s["status"] == "CANCELLING" else
                      "SUCCEEDED" if successes == len(plan["steps"]) else "PARTIAL" if successes else "FAILED")
            s.update(status=status, phase="RENDER", owner=None,
                     answer_sufficiency="QUALIFIED" if successes else "INSUFFICIENT")
        self.store.update(run_id, finish, "run_finished")

    def _step_state(self, run_id, key, result):
        self.store.update(run_id, lambda s: s["steps"].setdefault(key, {}).update(result),
                          "step_state", {"step_id": key, **result})


@lru_cache(maxsize=1)
def get_run_service():
    return RunService()
