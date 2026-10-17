import json
import threading
from unittest.mock import patch

import requests
from fastapi.testclient import TestClient

from backend.main import app
from tests.helpers import ConfigTestCase, query_response
from utils.bi_service import BIService, format_analysis_report, validate_plan
from utils.run_service import RunService
from utils.run_store import RunStore
from utils.resources import RunQueue
from tests.test_llm import response


def plan():
    return {"analysis_goal": "compare", "expected_output": "report", "steps": [
        {"step_id": 1, "step_type": "sql_query", "description": "query first", "dependencies": []},
        {"step_id": 2, "step_type": "sql_query", "description": "query second", "dependencies": []},
        {"step_id": 3, "step_type": "llm_analysis", "dependencies": [2],
         "analysis_requirements": {"input_data": [2]}},
    ]}


class ServiceTests(ConfigTestCase):
    def setUp(self):
        super().setUp()
        self.service = BIService(self.config, self.mcp, self.llm)

    def test_query_uses_schema_and_real_tool_results(self):
        self.llm.generate_sql.return_value = "```sql\nSELECT updated_at FROM mysql_orders\n```"
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        result = self.service.query("show updates", "mysql")
        self.assertEqual(result["data"]["rows"], [[1]])
        self.assertIn("mysql_orders", self.llm.generate_sql.call_args.args[0])
        self.assertIn("updated_at", self.llm.generate_sql.call_args.args[0])
        self.assertEqual(self.mcp.call_mcp_server_with_config.call_args.args[0], "mysql")

    def test_exact_data_reference_not_first_matching_step(self):
        self.service.query = self.mcp.query
        self.service.query.side_effect = [
            {"data": "WRONG_FIRST_DATA"}, {"data": "EXPECTED_SECOND_DATA"},
        ]
        self.llm.generate_response.return_value = "evidence-based report"
        result = self.service.execute_plan(plan(), "compare", "mysql")
        self.assertTrue(result["completed"])
        prompt = self.llm.generate_response.call_args.args[0]
        self.assertIn("EXPECTED_SECOND_DATA", prompt)
        self.assertNotIn("WRONG_FIRST_DATA", prompt)

    def test_clarification_reaches_sql_prompt_through_persisted_workflow(self):
        self.llm.generate_sql.return_value = "SELECT updated_at FROM mysql_orders"
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        runs = RunService(RunStore(self.config.config_dir / "runs.sqlite3"), self.config,
                          lambda **kwargs: self.service)
        run_id = runs.submit("retrieve chosen segment", plan={"steps": [
            {"step_id": 1, "step_type": "user_input", "description": "Which segment?"},
            {"step_id": 2, "step_type": "sql_query", "dependencies": [1]},
        ]})["run_id"]
        runs.execute(run_id)
        state = runs.store.get(run_id)
        runs.respond(run_id, state["request"]["request_id"], state["plan_version"], "retail_west_51")
        runs.execute(run_id)
        self.assertEqual(runs.store.get(run_id)["status"], "SUCCEEDED")
        self.assertIn("retail_west_51", self.llm.generate_sql.call_args.args[0])

    def test_exhausted_tool_budget_allows_clarification_and_model_only_steps(self):
        self.llm.generate_response.return_value = "Evidence summary"
        runs = RunService(RunStore(self.config.config_dir / "budget.sqlite3"), self.config,
                          lambda **kwargs: BIService(kwargs["config_manager"], self.mcp, self.llm))
        run_id = runs.submit("explain", plan={"steps": [
            {"step_id": 1, "step_type": "knowledge_retrieval", "query": "term"},
            {"step_id": 2, "step_type": "user_input", "dependencies": [1]},
            {"step_id": 3, "step_type": "llm_analysis", "dependencies": [1, 2]},
            {"step_id": 4, "step_type": "knowledge_retrieval", "query": "more", "dependencies": [3]},
        ]})["run_id"]
        runs.store.update(run_id, lambda s: s["limits"].update(tool_calls=1))
        runs.execute(run_id)
        state = runs.store.get(run_id)
        self.assertEqual(state["status"], "WAITING_INPUT")
        runs.respond(run_id, state["request"]["request_id"], state["plan_version"], "confirmed")
        runs.execute(run_id)
        state = runs.store.get(run_id)
        self.assertEqual(state["steps"]["3"]["status"], "SUCCEEDED")
        self.assertEqual(state["steps"]["4"]["status"], "BLOCKED")
        self.assertEqual(len(state["tool_records"]), 1)
        self.llm.generate_response.assert_called_once()

    def test_sql_dependency_binding_excludes_unrelated_results(self):
        self.service.query = self.mcp.query
        self.service.query.return_value = {"data": {}}
        self.service.execute_step({"step_type": "sql_query", "dependencies": [2]}, "query", "mysql", {
            1: {"data": "UNRELATED"}, 2: {"data": "CONFIRMED_FILTER"},
        })
        prompt = self.service.query.call_args.args[0]
        self.assertIn("CONFIRMED_FILTER", prompt)
        self.assertNotIn("UNRELATED", prompt)

    def test_real_network_failures_retry_within_model_budget_not_nested_step_retries(self):
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        for failures, expected_calls, expected_status in (
            ([requests.Timeout("offline"), response()], 2, "SUCCEEDED"),
            ([requests.ConnectionError("offline")] * 3, 3, "FAILED"),
            ([response(401)], 1, "FAILED"),
        ):
            with self.subTest(status=expected_status, calls=expected_calls):
                runs = RunService(RunStore(self.config.config_dir / "network.sqlite3"), self.config,
                                  lambda **kwargs: BIService(kwargs["config_manager"], self.mcp))
                run_id = runs.submit("query", plan={"steps": [
                    {"step_id": 1, "step_type": "sql_query"},
                ]})["run_id"]
                with patch("utils.llm_client.requests.post", side_effect=failures) as post:
                    runs.execute(run_id)
                state = runs.store.get(run_id)
                self.assertEqual(state["status"], expected_status, state)
                self.assertEqual(post.call_count, expected_calls)
                self.assertEqual(len(state["model_calls"]), expected_calls)
                self.assertEqual(state["steps"]["1"]["attempt_count"], 1)

    def test_failed_dependencies_skip_analysis_and_report_partial(self):
        self.service.query = self.mcp.query
        self.service.query.side_effect = [RuntimeError("offline"), RuntimeError("offline")]
        result = self.service.execute_plan(plan(), "compare", "mysql")
        self.assertFalse(result["completed"])
        self.assertEqual(result["steps"][3]["status"], "skipped")
        self.llm.generate_response.assert_not_called()
        report = format_analysis_report("compare", result)
        self.assertIn("partial (0/3)", report)
        self.assertIn("offline", report)
        self.assertIn("skipped", report)

    def test_plan_orders_dependencies_instead_of_numeric_ids(self):
        unordered = {"steps": [
            {"step_id": 1, "step_type": "llm_analysis", "dependencies": [2],
             "analysis_requirements": {"input_data": ["步骤2"]}},
            {"step_id": 2, "step_type": "sql_query"},
        ]}
        normalized = validate_plan(unordered)
        self.assertEqual([step["step_id"] for step in normalized["steps"]], [2, 1])
        self.assertEqual(normalized["steps"][1]["analysis_requirements"]["input_data"], [2])
        self.assertEqual(unordered["steps"][0]["analysis_requirements"]["input_data"], ["步骤2"])

    def test_plan_rejects_cycles_unknown_ids_duplicates_and_ambiguous_refs(self):
        for steps in (
            [{"step_id": 1, "step_type": "sql_query", "dependencies": [1]}],
            [{"step_id": 1, "step_type": "sql_query", "dependencies": [99]}],
            [{"step_id": 1, "step_type": "sql_query"}, {"step_id": 1, "step_type": "sql_query"}],
            [{"step_id": 1, "step_type": "llm_analysis",
              "analysis_requirements": {"input_data": ["sales data"]}}],
        ):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                validate_plan({"steps": steps})

    def test_no_mock_external_facts_on_search_failure(self):
        external_plan = {"steps": [
            {"step_id": 1, "step_type": "external_data", "data_requirements": {"query": "weather"}},
        ]}
        self.mcp.call_mcp_server.return_value = {"result": {"results": []}}
        result = self.service.execute_plan(external_plan, "weather", "mysql")
        self.assertEqual(result["steps"][1]["status"], "error")
        self.assertNotIn("data", result["steps"][1])
        self.assertIn("No external sources", result["steps"][1]["message"])

    def test_refinement_passes_previous_plan_and_feedback(self):
        self.llm.generate_response.return_value = json.dumps(plan())
        previous = plan()
        self.service.analysis_plan("question", "mysql", previous, "retain changes")
        prompt = self.llm.generate_response.call_args.args[0]
        self.assertIn("Previous plan", prompt)
        self.assertIn("retain changes", prompt)

    def test_empty_result_is_valid_but_nested_errors_are_not(self):
        self.llm.generate_sql.return_value = "SELECT updated_at FROM mysql_orders"
        self.mcp.call_mcp_server_with_config.return_value = query_response(rows=[])
        self.assertEqual(self.service.query("question", "mysql")["data"]["rows"], [])
        self.mcp.call_mcp_server_with_config.return_value = {"result": {"error": "offline"}}
        with self.assertRaisesRegex(RuntimeError, "offline"):
            self.service.query("question", "mysql")

    def test_invalid_row_shape_is_an_explicit_execution_error(self):
        self.llm.generate_sql.return_value = "SELECT updated_at FROM mysql_orders"
        self.mcp.call_mcp_server_with_config.return_value = {
            "result": {"success": True, "data": {"columns": ["n"], "rows": [[1, 2]]}},
        }
        with self.assertRaisesRegex(RuntimeError, "invalid columns or rows"):
            self.service.query("question", "mysql")

    def test_sql_corrections_are_bounded_and_upgrade_without_changing_input(self):
        self.llm.generate_sql.return_value = "SELECT updated_at FROM mysql_orders"
        self.mcp.call_mcp_server_with_config.return_value = {"result": {"error": "SQL syntax error"}}
        with self.assertRaisesRegex(RuntimeError, "syntax"):
            self.service.query("exclude refunds", "mysql")
        self.assertEqual(self.mcp.call_mcp_server_with_config.call_count, 3)
        self.assertEqual([record["role"] for record in self.service.router.records], ["sql", "sql", "reasoning"])
        self.assertIn("exclude refunds", self.llm.generate_sql.call_args.args[0])


class APITests(ConfigTestCase):
    def setUp(self):
        super().setUp()
        self.service = BIService(self.config, self.mcp, self.llm)
        self.llm.generate_sql.return_value = "SELECT updated_at FROM mysql_orders"
        self.llm.generate_response.return_value = json.dumps(plan())
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        self.client = TestClient(app)
        for target, value in (
            ("backend.routers.chat.BIService", self.service),
            ("backend.routers.database.BIService", self.service),
            ("backend.routers.database.MCPClient", self.mcp),
            ("backend.routers.llm.BIService", self.service),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_real_query_and_generate_sql_routes(self):
        for path in ("/api/chat/generate-sql", "/api/chat/query"):
            result = self.client.post(path, json={"question": "updates", "database": "mysql"})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertIn("updated_at", result.json()["sql"])
        self.assertEqual(self.client.post("/generate-sql", json={}).status_code, 404)
        self.mcp.call_mcp_server_with_config.assert_called_once()

    def test_synchronous_plan_shares_run_admission_and_returns_busy(self):
        queue = RunQueue(workers=1, queue_capacity=0)
        self.addCleanup(queue.close)
        entered, release = threading.Event(), threading.Event()
        def occupy():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Fixture timed out")
        future = queue.submit("active-run", occupy)
        try:
            self.assertTrue(entered.wait(5))
            with patch("utils.resources.run_queue", queue):
                result = self.client.post("/api/chat/execute-plan", json={
                    "question": "query", "plan": {"steps": [{"step_id": 1, "step_type": "sql_query"}]}})
            self.assertEqual(result.status_code, 503, result.text)
            self.assertEqual(result.headers["Retry-After"], "1")
            self.llm.generate_sql.assert_not_called()
            self.mcp.call_mcp_server_with_config.assert_not_called()
        finally:
            release.set()
            future.result(5)

    def test_invalid_database_and_empty_connection_cannot_succeed(self):
        invalid = self.client.post("/api/database/test-connection", json={"type": "invalid", "config": {}})
        self.assertEqual(invalid.status_code, 422)
        empty = self.client.post("/api/database/test-connection", json={"type": "mysql", "config": {}})
        self.assertEqual(empty.status_code, 400)

    def test_database_schema_is_saved_schema_not_fixed_customers(self):
        result = self.client.get("/api/database/schema", params={"db": "mysql"})
        self.assertEqual(result.status_code, 200)
        self.assertIn("mysql_orders", result.json()["tables"])
        self.assertNotIn("customers", result.json()["tables"])

    def test_execution_failure_has_error_http_status(self):
        self.mcp.call_mcp_server_with_config.return_value = {"result": {"error": "offline"}}
        result = self.client.post("/api/chat/query", json={"question": "updates", "database": "mysql"})
        self.assertEqual(result.status_code, 502)
        self.assertFalse(result.json()["success"])

    def test_plan_and_refinement_are_generated(self):
        result = self.client.post("/api/chat/analyze", json={"question": "why", "database": "mysql"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()["analysis_chain"]), 3)
        result = self.client.post("/api/chat/optimize-chain", json={
            "original_chain": plan()["steps"], "feedback": "more detail", "database": "mysql",
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("more detail", self.llm.generate_response.call_args.args[0])

    def test_chat_preserves_history(self):
        self.llm.chat.return_value = {"content": "real response", "tool_calls": None}
        messages = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "answer"},
                    {"role": "user", "content": "follow up"}]
        result = self.client.post("/api/llm/chat", json={"messages": messages})
        self.assertEqual(result.status_code, 200)
        self.llm.chat.assert_called_once_with(messages, model=None, temperature=None)
