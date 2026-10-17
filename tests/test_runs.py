import tempfile
import threading
import unittest
import time
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.main import app
from utils.config_manager import ConfigManager
from utils.run_service import RunService
from utils.run_store import RunStore
from utils.resources import BusyError, ResourceLimiter, RunQueue
from utils.run_view import RunViewCache


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

    def test_history_cursor_filters_session_before_paging_and_returns_summaries(self):
        wanted = [self.submit(session_id="wanted") for _ in range(5)]
        for _ in range(6):
            self.submit(session_id="unrelated")
        seen, cursor = [], None
        while True:
            page = self.store.history_page("wanted", cursor, limit=2)
            seen.extend(item["run_id"] for item in page["items"])
            self.assertTrue(all("steps" not in item and "plan" not in item for item in page["items"]))
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(seen, list(reversed(wanted)))

    def test_public_and_status_reads_do_not_load_private_snapshot(self):
        run_id = self.submit()
        private = self.store.get(run_id, private=True)
        connect = self.store.connect
        @contextmanager
        def without_private():
            with connect() as db:
                db.set_authorizer(lambda action, table, column, *args: (
                    sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ
                    and table == "runs" and column == "private" else sqlite3.SQLITE_OK))
                yield db
        with patch.object(self.store, "connect", side_effect=without_private):
            self.assertEqual(self.store.get(run_id)["status"], "QUEUED")
            with patch("utils.run_store.json.loads", side_effect=AssertionError("State must not be deserialized")):
                self.assertEqual(self.store.status(run_id), "QUEUED")
            with self.assertRaises(KeyError):
                self.store.status("missing")
        self.assertEqual(self.store.get(run_id, private=True), private)

    def test_view_byte_budget_is_shared_and_oversized_artifacts_are_not_retained(self):
        cache, store = RunViewCache(max_bytes=6000), Mock()
        payload = {"data": "x" * 4000}
        store.artifact.return_value = payload
        self.assertEqual(cache.artifact(store, "view", "run", "a"), payload)
        store.get.return_value = {"session_id": "view", "report": "y" * 4000}
        summary = {"run_id": "run", "event_seq": 1, "updated_at": "now"}
        self.assertEqual(cache.snapshot(store, "view", summary)["report"], "y" * 4000)
        self.assertEqual(cache.artifacts, {})
        self.assertEqual(cache.artifact(store, "view", "run", "a"), payload)
        self.assertEqual(store.artifact.call_count, 2)
        self.assertEqual(cache.snapshots, {})
        store.artifact.return_value = {"data": "z" * 8000}
        self.assertEqual(len(cache.artifact(store, "view", "run", "large")["data"]), 8000)
        self.assertNotIn(("view", "run", "large"), cache.artifacts)
        self.assertLessEqual(cache.cached_bytes, cache.max_bytes)
        self.assertGreater(cache.cached_bytes, 0)

    def test_oversized_event_history_still_returns_all_pages_without_retaining_them(self):
        cache, store = RunViewCache(max_bytes=4000), Mock()
        events = [{"seq": index, "payload": "x" * 30} for index in range(1, 3)]
        store.events.side_effect = lambda run_id, after: events[after:after + 500]
        self.assertEqual(cache.read_events(store, "view", "run"), events)
        with patch("utils.run_view._size_bytes", side_effect=AssertionError("Unchanged events must not be reweighed")):
            self.assertEqual(cache.read_events(store, "view", "run"), events)
        events.extend({"seq": index, "payload": "x" * 30} for index in range(3, 701))
        store.events.reset_mock()
        self.assertEqual(cache.read_events(store, "view", "run"), events)
        self.assertEqual([call.kwargs["after"] for call in store.events.call_args_list], [2, 502])
        self.assertEqual(cache.events, {})
        self.assertEqual(cache.read_events(store, "view", "run"), events)
        self.assertEqual(cache.cached_bytes, 0)

    def test_unchanged_view_does_not_reread_state_or_artifact_and_drains_event_pages(self):
        run_id = self.submit(session_id="view")
        self.service.execute(run_id)
        for _ in range(1001):
            self.store.update(run_id, lambda s: None, "fixture")
        summary = self.store.history_page("view")["items"][0]
        cache = RunViewCache()
        with patch.object(self.store, "get", wraps=self.store.get) as read, \
                patch.object(self.store, "artifact", wraps=self.store.artifact) as artifact:
            for _ in range(3):
                state = cache.snapshot(self.store, "view", summary)
                cache.artifact(self.store, "view", run_id, state["steps"]["1"]["artifact_id"])
            self.assertEqual(read.call_count, 1)
            self.assertEqual(artifact.call_count, 1)
        events = cache.read_events(self.store, "view", run_id)
        self.assertGreater(len(events), 1000)
        self.assertEqual(events[-1]["seq"], self.store.get(run_id)["event_seq"])
        self.assertEqual(cache.read_events(self.store, "view", run_id), events)
        with self.assertRaises(ValueError):
            cache.snapshot(self.store, "another-session", summary)


class ResourceTests(unittest.TestCase):
    def test_bounded_queue_cancel_and_completed_future_cleanup(self):
        queue = RunQueue(workers=1, queue_capacity=1)
        self.addCleanup(queue.close)
        entered, release = threading.Event(), threading.Event()
        def work():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Fixture timed out")
        first = queue.submit("first", work)
        try:
            self.assertTrue(entered.wait(5))
            self.assertIs(queue.submit("first", work), first)
            queue.submit("second", work)
            with self.assertRaises(BusyError):
                queue.submit("overflow", work)
            self.assertTrue(queue.cancel("second"))
            self.assertNotIn("second", queue.futures)
        finally:
            release.set()
        first.result(5)
        queue.close()
        self.assertEqual(queue.futures, {})

    def test_provider_wait_is_cancellable_and_entries_are_reclaimed(self):
        limiter = ResourceLimiter(capacity=1)
        cancel = threading.Event()
        errors = []
        def wait_for_resource():
            try:
                with limiter.acquire("server", timeout=2, cancelled=cancel.is_set):
                    self.fail("Cancelled waiter must not execute")
            except BaseException as exc:
                errors.append(exc)
        with limiter.acquire("server"):
            thread = threading.Thread(target=wait_for_resource)
            thread.start()
            cancel.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(limiter.active, 1)
        from concurrent.futures import CancelledError
        self.assertIsInstance(errors[0], CancelledError)
        self.assertEqual(limiter.providers, {})
        self.assertEqual(limiter.peak, 1)
        self.assertEqual(limiter.active, 0)

    def test_resource_timeout_does_not_leak_capacity(self):
        limiter = ResourceLimiter(capacity=1)
        with limiter.acquire("one"):
            started = time.monotonic()
            with self.assertRaises(BusyError), limiter.acquire("two", timeout=0.02):
                self.fail("Unavailable permit granted")
            self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(limiter.providers, {})
