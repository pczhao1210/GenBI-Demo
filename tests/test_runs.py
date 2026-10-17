import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.main import app
from utils.config_manager import ConfigManager
from utils.run_service import RunService
from utils.run_store import RunStore


def dag():
    return {"steps": [
        {"step_id": 1, "step_type": "sql_query"},
        {"step_id": 2, "step_type": "sql_query"},
        {"step_id": 3, "step_type": "llm_analysis", "dependencies": [1],
         "analysis_requirements": {"input_data": [1]}},
    ]}


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = ConfigManager(Path(temp.name) / "config")
        self.store = RunStore(Path(temp.name) / "runs.sqlite3")
        self.bi = Mock()
        self.bi.execute_step.return_value = {"status": "success", "data": "evidence"}
        self.service = RunService(self.store, self.config, lambda **kwargs: self.bi)

    def submit(self, plan=None, **kwargs):
        return self.service.submit("question", plan=plan or dag(), **kwargs)["run_id"]

    def test_persistence_idempotency_and_events(self):
        run_id = self.submit(submission_id="one")
        self.assertEqual(self.submit(submission_id="one"), run_id)
        with self.assertRaises(ValueError):
            self.service.submit("different", submission_id="one")
        self.service.execute(run_id)
        restored = RunStore(self.store.path)
        state = restored.get(run_id)
        self.assertEqual(state["status"], "SUCCEEDED")
        events = restored.events(run_id)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(restored.events(run_id, events[-1]["seq"]), [])
        self.assertNotIn("snapshot", state)

    def test_session_history_filters_before_limit_and_retains_followup_context(self):
        run_id = self.submit(session_id="older-session")
        understanding = {"slots": {"filters": {"value": {"region": "west"}, "origin": "current"}}}
        self.store.update(run_id, lambda s: s.update(status="SUCCEEDED", understanding=understanding))
        for index in range(205):
            self.store.create({"run_id": f"other-{index}", "session_id": "other"},
                              {"submission_input": {}}, f"other-{index}")
        self.assertEqual(len(self.store.history()), 200)
        self.assertEqual([run["run_id"] for run in self.store.history("older-session")], [run_id])
        self.assertEqual(self.store.history("unknown"), [])
        followup = self.service.submit("yesterday", session_id="older-session", plan=dag())
        self.assertEqual(followup["context"], understanding["slots"])

    def test_failed_dependencies_partial_retry_reuses_success(self):
        def execute(step, *args):
            if step["step_id"] == 1:
                raise RuntimeError("offline")
            return {"status": "success", "data": 2}
        self.bi.execute_step.side_effect = execute
        run_id = self.submit()
        self.service.execute(run_id)
        state = self.store.get(run_id)
        self.assertEqual(state["status"], "PARTIAL")
        self.assertEqual(state["steps"]["3"]["status"], "BLOCKED")
        self.bi.execute_step.side_effect = None
        retry = self.service.retry(run_id)
        self.bi.execute_step.reset_mock()
        self.service.execute(retry["run_id"])
        self.assertEqual(self.bi.execute_step.call_count, 2)
        self.assertEqual(self.store.get(run_id)["status"], "PARTIAL")
        self.assertEqual(self.store.get(retry["run_id"])["status"], "SUCCEEDED")

    def test_all_failed_is_failed_not_partial(self):
        self.bi.execute_step.side_effect = RuntimeError("offline")
        run_id = self.submit()
        self.service.execute(run_id)
        self.assertEqual(self.store.get(run_id)["status"], "FAILED")

    def test_retry_invalidates_consumers_of_retried_optional_inputs(self):
        unavailable = True
        def execute(step, question, database, inputs):
            if step["step_id"] == 1 and unavailable:
                raise RuntimeError("Source unavailable")
            return {"status": "success", "data": inputs}
        self.bi.execute_step.side_effect = execute
        run_id = self.submit({"steps": [
            {"step_id": 1, "step_type": "external_data"},
            {"step_id": 2, "step_type": "llm_analysis", "optional_dependencies": [1],
             "allow_missing_inputs": True, "analysis_requirements": {"input_data": [1]}},
            {"step_id": 3, "step_type": "llm_analysis", "dependencies": [2]},
            {"step_id": 4, "step_type": "sql_query"},
        ]})
        self.service.execute(run_id)
        self.assertEqual(self.store.get(run_id)["status"], "PARTIAL")
        unavailable = False
        retry = self.service.retry(run_id)
        self.assertEqual(set(retry["steps"]), {"4"})
        self.bi.execute_step.reset_mock()
        self.service.execute(retry["run_id"])
        self.assertEqual([call.args[0]["step_id"] for call in self.bi.execute_step.call_args_list], [1, 2, 3])
        state = self.store.get(retry["run_id"])
        self.assertEqual(state["status"], "SUCCEEDED")
        result = self.store.artifact(retry["run_id"], state["steps"]["2"]["artifact_id"])
        self.assertEqual(result["data"]["1"]["status"], "success")

    def test_optional_branch_failure_does_not_fail_required_delivery(self):
        def execute(step, *args):
            if step["step_id"] == 1:
                raise RuntimeError("optional source unavailable")
            return {"status": "success", "data": "qualified delivery"}
        self.bi.execute_step.side_effect = execute
        run_id = self.submit({"steps": [
            {"step_id": 1, "step_type": "external_data", "required": False},
            {"step_id": 2, "step_type": "sql_query", "optional_dependencies": [1], "allow_missing_inputs": True},
        ]})
        self.service.execute(run_id)
        state = self.store.get(run_id)
        self.assertEqual(state["status"], "SUCCEEDED")
        self.assertEqual(state["steps"]["1"]["status"], "FAILED")

    def test_clarification_checkpoint_and_stale_response(self):
        run_id = self.submit({"steps": [
            {"step_id": 1, "step_type": "user_input", "description": "Which metric?"},
            {"step_id": 2, "step_type": "sql_query", "dependencies": [1]},
        ]})
        self.service.execute(run_id)
        state = self.store.get(run_id)
        self.assertEqual(state["status"], "WAITING_INPUT")
        restored = RunService(RunStore(self.store.path), self.config, lambda **kw: self.bi)
        with self.assertRaises(ValueError):
            restored.respond(run_id, "stale", 1, "revenue")
        restored.respond(run_id, state["request"]["request_id"], 1, "revenue")
        restored.execute(run_id)
        self.assertEqual(self.store.get(run_id)["status"], "SUCCEEDED")
        self.assertEqual(self.bi.execute_step.call_count, 1)
        self.assertEqual(self.bi.execute_step.call_args.args[3][1]["data"], "revenue")
        self.assertEqual(len(self.store.replay(run_id)["artifacts"]), 2)

    def test_cancel_does_not_start_dependants_or_claim_early_completion(self):
        entered, release = threading.Event(), threading.Event()
        def execute(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"status": "success"}
        self.bi.execute_step.side_effect = execute
        run_id = self.submit({"steps": [
            {"step_id": 1, "step_type": "sql_query"},
            {"step_id": 2, "step_type": "sql_query", "dependencies": [1]},
        ]})
        worker = threading.Thread(target=self.service.execute, args=(run_id,))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.service.cancel(run_id)["status"], "CANCELLING")
            self.assertEqual(self.service.cancel(run_id)["status"], "CANCELLING")
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.store.get(run_id)["status"], "CANCELLED")
        self.assertEqual(self.bi.execute_step.call_count, 1)

    def test_cancel_during_concept_answer_cannot_be_overwritten_by_success(self):
        entered, release = threading.Event(), threading.Event()
        self.bi.understand.return_value = {
            "intent": "concept", "slots": {}, "normalized_question": "concept", "clarification": None,
        }
        def explain(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"status": "success", "data": "definition", "answer_sufficiency": "QUALIFIED"}
        self.bi.explain.side_effect = explain
        run_id = self.service.submit("concept")["run_id"]
        worker = threading.Thread(target=self.service.execute, args=(run_id,))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.service.cancel(run_id)["status"], "CANCELLING")
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        state = self.store.get(run_id)
        self.assertEqual(state["status"], "CANCELLED")
        self.assertIsNone(state["answer_sufficiency"])
        self.service._finish(run_id, 0)
        self.assertEqual(self.store.get(run_id)["status"], "CANCELLED")

    def test_cancel_during_understanding_stops_before_next_model_stage(self):
        entered, release = threading.Event(), threading.Event()
        def understand(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"intent": "analysis", "slots": {}, "normalized_question": "why", "clarification": None}
        self.bi.understand.side_effect = understand
        run_id = self.service.submit("why")["run_id"]
        worker = threading.Thread(target=self.service.execute, args=(run_id,))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.service.cancel(run_id)["status"], "CANCELLING")
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.store.get(run_id)["status"], "CANCELLED")
        self.bi.analysis_plan.assert_not_called()
        self.bi.execute_step.assert_not_called()

    def test_parallel_branches_are_merged(self):
        barrier = threading.Barrier(2)
        def execute(step, *args):
            if step["step_id"] < 3:
                barrier.wait(5)
            return {"status": "success", "data": step["step_id"]}
        self.bi.execute_step.side_effect = execute
        run_id = self.submit()
        self.service.execute(run_id)
        self.assertEqual(self.store.get(run_id)["status"], "SUCCEEDED")
        self.assertEqual(len(self.store.get(run_id)["steps"]), 3)

    def test_recovery_preserves_completed_steps_and_waiting_request(self):
        run_id = self.submit()
        artifact = self.store.put_artifact(run_id, {"status": "success", "data": 1})
        self.store.update(run_id, lambda s: s.update(status="RUNNING", owner=None, steps={
            "1": {"status": "SUCCEEDED", "artifact_id": artifact, "validity": "CURRENT"},
            "2": {"status": "RUNNING", "attempt_id": "old"},
        }))
        self.service.recover(run_id)
        self.service.execute(run_id)
        self.assertEqual(self.bi.execute_step.call_count, 2)
        with self.assertRaises(ValueError):
            self.service.recover(run_id)

    def test_api_snapshot_artifact_cursor_and_missing_run(self):
        client = TestClient(app)
        with patch("backend.routers.runs.get_run_service", return_value=self.service), \
                patch.object(self.service, "start", side_effect=self.service.execute):
            response = client.post("/api/runs", json={
                "question": "question", "submission_id": "api", "plan": dag(),
            })
            self.assertEqual(response.status_code, 200, response.text)
            run_id = response.json()["run_id"]
            state = client.get(f"/api/runs/{run_id}").json()
            artifact = state["steps"]["1"]["artifact_id"]
            self.assertEqual(client.get(f"/api/runs/{run_id}/artifacts/{artifact}").status_code, 200)
            self.assertEqual(client.get(f"/api/runs/{run_id}/events?after=999").json(), [])
            self.assertEqual(client.get("/api/runs/missing").status_code, 404)
