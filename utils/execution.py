"""Shared DAG semantics for persistent runs and the synchronous compatibility API."""

import logging
import time
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait
from copy import deepcopy
from threading import RLock
from uuid import uuid4

from utils.model_router import ToolBudget

TERMINAL = {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}
STEP_TERMINAL = {"SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED", "CANCELLED"}
logger = logging.getLogger(__name__)


def outcome(state):
    required = [step for step in state["plan"]["steps"] if step.get("required", True)]
    successful = {key for key, step in state["steps"].items() if step["status"] == "SUCCEEDED"}
    if state["status"] in {"CANCELLING", "CANCELLED"}:
        return "CANCELLED"
    if successful and all(str(step["step_id"]) in successful for step in required):
        return "SUCCEEDED"
    if any(str(step["step_id"]) in successful and step["step_type"] != "user_input" for step in required):
        return "PARTIAL"
    return "FAILED"


class MemoryExecutionStore:
    def __init__(self, state):
        self.state = deepcopy(state)
        self.artifacts = {}
        self.lock = RLock()

    def get(self, run_id):
        with self.lock:
            return deepcopy(self.state)

    def status(self, run_id):
        with self.lock:
            return self.state["status"]

    def update(self, run_id, change, event_type=None, payload=None):
        with self.lock:
            change(self.state)
            return deepcopy(self.state)

    def put_artifact(self, run_id, payload):
        with self.lock:
            artifact_id = uuid4().hex
            self.artifacts[artifact_id] = deepcopy(payload)
            return artifact_id

    def artifact(self, run_id, artifact_id):
        with self.lock:
            return deepcopy(self.artifacts[artifact_id])


def execute_dag(store, run_id, service, started, request_input):
    from utils.bi_service import validate_plan
    state = store.get(run_id)
    plan = validate_plan(state["plan"])
    if len(plan["steps"]) > state["limits"]["max_steps"]:
        raise ValueError("Plan exceeds step budget")
    store.update(run_id, lambda s: s.update(plan=plan, phase="EXECUTE"),
                 "phase_changed", {"phase": "EXECUTE"})
    futures = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            state = store.get(run_id)
            cancelled = state["status"] in {"CANCELLING", "CANCELLED"}
            exhausted = state["active_seconds"] + time.monotonic() - started > state["limits"]["active_seconds"]
            budget = getattr(service, "tools", None)
            calls_exhausted = (len(budget.records) >= budget.max_calls if isinstance(budget, ToolBudget)
                               else state.get("step_attempts", 0) >= state["limits"]["tool_calls"])
            for step in plan["steps"]:
                key = str(step["step_id"])
                existing = state["steps"].get(key, {})
                if existing.get("status") in STEP_TERMINAL | {"RUNNING"}:
                    continue
                dependencies = [state["steps"].get(str(ref), {}) for ref in step["dependencies"]]
                optional = [state["steps"].get(str(ref), {}) for ref in step["optional_dependencies"]]
                result = None
                needs_tool = step["step_type"] not in ("llm_analysis", "user_input")
                if cancelled or exhausted or (calls_exhausted and needs_tool):
                    result = {"status": "CANCELLED" if cancelled else "BLOCKED",
                              "error": "Cancelled" if cancelled else "Execution budget exhausted"}
                elif any(item.get("status") in STEP_TERMINAL - {"SUCCEEDED"} for item in dependencies):
                    result = {"status": "BLOCKED", "error": "Required dependency failed"}
                elif all(item.get("status") == "SUCCEEDED" for item in dependencies) and all(
                        item.get("status") in STEP_TERMINAL for item in optional):
                    if len(futures) >= 4:
                        continue
                    if step["step_type"] == "user_input":
                        if futures:
                            continue
                        if request_input(step):
                            return
                        continue
                    inputs = {}
                    for ref in step["dependencies"] + step["optional_dependencies"]:
                        item = state["steps"][str(ref)]
                        inputs[ref] = (store.artifact(run_id, item["artifact_id"])
                                       if item["status"] == "SUCCEEDED"
                                       else {"status": "error", "message": item.get("error")})
                    attempt = uuid4().hex
                    accepted = False

                    def begin(s):
                        nonlocal accepted
                        if s["status"] != "RUNNING":
                            return
                        accepted = True
                        s["steps"].setdefault(key, {}).update(
                            status="RUNNING", attempt_id=attempt, validity="CURRENT",
                            attempt_count=existing.get("attempt_count", 0) + 1)
                        s["step_attempts"] = s.get("step_attempts", 0) + 1
                    store.update(run_id, begin, "step_started", {"step_id": key, "attempt_id": attempt})
                    if not accepted:
                        continue
                    future = pool.submit(
                        _invoke, store, run_id, service, step,
                        state.get("normalized_question", state["question"]),
                        step.get("datasource_id", state["database"]), inputs)
                    futures[future] = (key, attempt, state["plan_version"], step)
                if result:
                    store.update(run_id, lambda s: s["steps"].setdefault(key, {}).update(result),
                                 "step_state", {"step_id": key, **result})
            if not futures:
                state = store.get(run_id)
                if all(state["steps"].get(str(step["step_id"]), {}).get("status") in STEP_TERMINAL
                       for step in plan["steps"]):
                    return
                continue
            done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                key, attempt, version, definition = futures.pop(future)
                try:
                    payload = future.result()
                    if not isinstance(payload, dict) or payload.get("status") != "success":
                        raise RuntimeError("Tool returned an invalid or unsuccessful result")
                    artifact = store.put_artifact(run_id, payload)
                    result = {"status": "SUCCEEDED", "artifact_id": artifact, "validity": "CURRENT"}
                except CancelledError:
                    result = {"status": "CANCELLED", "validity": "CURRENT"}
                except Exception as exc:
                    logger.exception("Run %s step %s failed", run_id, key)
                    result = {"status": "FAILED", "error": str(exc), "validity": "CURRENT"}
                    current = store.get(run_id)
                    retryable = getattr(service, "step_retryable", None)
                    if (isinstance(exc, (TimeoutError, ConnectionError))
                            and current["status"] == "RUNNING"
                            and current["steps"][key]["attempt_count"] <= 2
                            and (retryable is None or retryable(definition))):
                        result["status"] = "PENDING"

                def merge(s):
                    if s["plan_version"] == version and s["steps"][key].get("attempt_id") == attempt:
                        s["steps"][key].update(result)
                store.update(run_id, merge, "step_finished", {"step_id": key, "attempt_id": attempt, **result})


def _invoke(store, run_id, service, step, question, database, inputs):
    from utils.resources import step_resources
    cancelled = lambda: store.status(run_id) in {"CANCELLING", "CANCELLED"}
    with step_resources.acquire("steps", limit=16, timeout=30, cancelled=cancelled):
        return service.execute_step(step, question, database, inputs)
