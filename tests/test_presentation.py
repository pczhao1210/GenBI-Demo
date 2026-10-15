import json
from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient

from backend.main import app
import tests.test_runs as run_fixtures
from utils.presentation import chart_spec, csv_export, export_run


class PresentationTests(unittest.TestCase):
    def test_charts_validate_unique_keys_time_units_and_shares(self):
        self.assertEqual(chart_spec({"columns": ["day", "amount"], "rows": [
            ["2026-10-01", "10.25"], ["2026-10-02", "12.25"]]
        })["kind"], "line")
        self.assertEqual(chart_spec({"columns": ["category", "share"], "rows": [["a", 20], ["b", 80]],
                                     "units": {"share": "%"}})["kind"], "pie")
        self.assertIsNone(chart_spec({"columns": ["category", "amount"], "rows": [["a", 1], ["a", 2]]}))
        self.assertIsNone(chart_spec({"columns": ["text", "other"], "rows": [["a", "b"], ["c", "d"]]}))
        self.assertIsNone(chart_spec({"columns": ["category", "amount"], "rows": [["a", "1e9999"], ["b", 2]]}))

    def test_csv_preserves_decimal_null_and_escapes_spreadsheet_formulas(self):
        text = csv_export({"columns": ["amount", "missing", "text"], "rows": [
            ["123456789.123456789", None, "=1+1"]]})
        self.assertIn("123456789.123456789,, '=1+1".replace(", ", ","), text)

    def test_markdown_export_has_expected_tuple_shape(self):
        content, media, extension = export_run({"snapshot": {
            "question": "question", "created_at": "2026-10-15", "status": "SUCCEEDED", "report": "Evidence"}}, "markdown")
        self.assertIn("Evidence", content)
        self.assertEqual((media, extension), ("text/markdown", "md"))


class ReplayTests(unittest.TestCase):
    setUp = run_fixtures.RunTests.setUp
    submit = run_fixtures.RunTests.submit

    def test_replay_and_export_are_persistent_and_never_call_tools(self):
        run_id = self.submit()
        self.service.execute(run_id)
        calls = self.bi.mock_calls[:]
        replay = self.store.replay(run_id)
        content, media, suffix = export_run(replay)
        self.assertEqual(json.loads(content)["kind"], "HISTORICAL_REPLAY")
        self.assertNotIn("private", content)
        self.assertEqual(len(replay["artifacts"]), 3)
        self.assertEqual(self.bi.mock_calls, calls)
        with patch("backend.routers.runs.get_run_service", return_value=self.service):
            client = TestClient(app)
            self.assertEqual(client.get(f"/api/runs/{run_id}/replay").status_code, 200)
            self.assertEqual(client.get(f"/api/runs/{run_id}/export").headers["content-type"], "application/json")
            artifact = self.store.get(run_id)["steps"]["1"]["artifact_id"]
            self.assertEqual(client.get(f"/api/runs/{run_id}/export?format=csv&artifact_id={artifact}").status_code, 400)
        self.assertEqual(self.bi.mock_calls, calls)

    def test_refresh_creates_new_run_and_reexecutes_all_steps(self):
        run_id = self.submit()
        self.service.execute(run_id)
        refreshed = self.service.retry(run_id, refresh=True)
        self.service.execute(refreshed["run_id"])
        self.assertNotEqual(refreshed["run_id"], run_id)
        self.assertEqual(self.bi.execute_step.call_count, 6)

    def test_deep_dependency_failure_marks_all_descendants_blocked(self):
        self.bi.execute_step.side_effect = RuntimeError("offline")
        run_id = self.submit({"steps": [
            {"step_id": i, "step_type": "sql_query", "dependencies": [i - 1] if i > 1 else []}
            for i in range(1, 8)]})
        self.service.execute(run_id)
        state = self.store.get(run_id)
        self.assertEqual(len(state["steps"]), 7)
        self.assertEqual(state["steps"]["7"]["status"], "BLOCKED")
        self.assertEqual(self.bi.execute_step.call_count, 1)

    def test_retry_preserves_frozen_understanding_and_analysis_contract(self):
        run_id = self.submit()
        self.service.execute(run_id)
        self.store.update(run_id, lambda s: s.update(analysis_mode=True,
            normalized_question="Explicit 2026-10-13 interval", understanding={"slots": {"time": {
                "value": {"start": "2026-10-13T00:00:00Z", "end": "2026-10-14T00:00:00Z"}}}}))
        retry = self.service.retry(run_id)
        self.assertTrue(retry["analysis_mode"])
        self.assertEqual(retry["normalized_question"], "Explicit 2026-10-13 interval")
        self.assertEqual(retry["ledger"]["replans"], 0)
