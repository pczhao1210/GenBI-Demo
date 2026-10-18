from copy import deepcopy
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from tests.helpers import ConfigTestCase, query_response
from utils.bi_service import BIService
from utils.model_router import ModelRouter, ToolBudget
from utils.run_context import FrozenConfig, snapshot_config, step_compatible
from utils.run_service import RunService
from utils.run_store import RunStore
from utils.semantics import KnowledgeIndex
from utils.sql_utils import validate_profile_sql
from utils.tool_execution import ToolInvoker


def profile(identifier="sales"):
    return {"id": identifier, "name": identifier, "description": "Sales domain",
            "datasources": {"legacy-mysql": ["mysql_orders"]},
            "mcp_servers": [], "knowledge_ids": [], "method_ids": []}


class ProfileTests(ConfigTestCase):
    def setUp(self):
        super().setUp()
        sources = self.config.load_datasources()
        source = sources["legacy-mysql"]
        source["schema"]["tables"]["private_orders"] = [{"name": "secret", "type": "text"}]
        self.config.save_datasource(source)
        self.config.save_knowledge({"documents": [
            {"id": "sales", "title": "Sales", "text": "Sales definition", "source": "sales.md", "version": "1", "scope": "*"},
            {"id": "private", "title": "Private", "text": "Private sales", "source": "private.md", "version": "1", "scope": "*"},
        ]})
        self.config.save_profile(profile())
        self.runs = RunService(RunStore(self.config.config_dir / "runs.sqlite3"), self.config)

    def configure_product_definition(self):
        source = self.config.resolve_datasource("legacy-mysql")
        source["schema"]["tables"]["mysql_orders"] = [
            {"name": "unit_price", "type": "decimal", "description": "A: unit price"},
            {"name": "quantity", "type": "integer", "description": "B: quantity"},
            {"name": "discount_factor", "type": "decimal", "description": "C: discount factor"},
        ]
        self.config.save_datasource(source)
        definition = "KPI1 = A * B * C per order line; A is unit price, B is quantity, C is discount factor."
        self.config.save_semantics({"metrics": {"kpi1": {"description": definition}}})
        return definition

    def test_definition_only_query_uses_scoped_schema_and_business_formula(self):
        definition = self.configure_product_definition()
        frozen = FrozenConfig(snapshot_config(self.config, "sales"))
        self.assertNotIn("allowed_dimensions", frozen.load_semantics()["metrics"]["kpi1"])
        self.llm.generate_response.return_value = json.dumps({
            "intent": "query", "followup": False,
            "slots": {"metrics": {"value": ["kpi1"], "span": [0, 4]}}, "clarification": None})
        service = BIService(frozen, self.mcp, self.llm)
        understood = service.understand("KPI1 for each order line", "legacy-mysql", {}, "2026-10-18T00:00:00Z")
        self.assertIsNone(understood["clarification"])
        self.assertEqual(understood["runtime_metrics"], ["kpi1"])
        self.assertFalse(understood["requires_plan"])
        prompt = self.llm.generate_response.call_args.args[0]
        for content in (definition, "unit_price", "quantity", "discount_factor"):
            self.assertIn(content, prompt)
        for forbidden in ("private_orders", "secret", "athena_orders", "test-key"):
            self.assertNotIn(forbidden, prompt)
        sql = "SELECT unit_price * quantity * discount_factor AS kpi1 FROM mysql_orders"
        self.llm.generate_sql.return_value = sql
        response = query_response([[16]])
        response["result"]["data"]["columns"] = ["kpi1"]
        self.mcp.call_mcp_server_with_config.return_value = response
        result = service.query(understood["normalized_question"], "legacy-mysql")
        self.assertEqual(result["sql"], sql)
        self.assertEqual(result["data"]["rows"], [[16]])
        self.assertIn(definition, self.llm.generate_sql.call_args.args[0])
        self.assertEqual(self.config.load_semantics()["metrics"]["kpi1"], {"description": definition})
        self.llm.generate_sql.return_value = "SELECT secret FROM private_orders"
        with self.assertRaisesRegex(ValueError, "outside the Profile"):
            service.generate_sql(understood["normalized_question"], "legacy-mysql")
        self.mcp.call_mcp_server_with_config.assert_called_once()

    def test_unmapped_kpi_with_multiple_profile_sources_requires_planning(self):
        self.configure_product_definition()
        selected = profile()
        selected["datasources"]["legacy-athena"] = ["athena_orders"]
        self.config.save_profile(selected)
        self.llm.generate_response.return_value = json.dumps({
            "intent": "query", "followup": False,
            "slots": {"metrics": {"value": ["kpi1"], "span": [0, 4]}}, "clarification": None})
        service = BIService(FrozenConfig(snapshot_config(self.config, "sales")), self.mcp, self.llm)
        result = service.understand("KPI1", "legacy-mysql", {}, "2026-10-18T00:00:00Z",
                                    datasource_ids=["legacy-mysql", "legacy-athena"])
        self.assertIsNone(result["clarification"])
        self.assertTrue(result["requires_plan"])
        self.assertIn("athena_orders", self.llm.generate_response.call_args.args[0])

    def test_ambiguous_definition_waits_before_sql_and_preserves_user_clarification(self):
        self.configure_product_definition()
        extracted = {"intent": "query", "followup": False,
                     "slots": {"metrics": {"value": ["kpi1"], "span": [0, 4]}}}
        self.llm.generate_response.side_effect = [
            json.dumps({**extracted, "clarification": "Sum line products or multiply component totals?"}),
            json.dumps({**extracted, "clarification": None}),
        ]
        self.llm.generate_sql.return_value = "SELECT SUM(unit_price * quantity * discount_factor) AS kpi1 FROM mysql_orders"
        self.mcp.call_mcp_server_with_config.return_value = query_response([[16]])
        runs = RunService(RunStore(self.config.config_dir / "definition-runs.sqlite3"), self.config,
                          lambda **kw: BIService(kw["config_manager"], self.mcp, self.llm))
        runs.start = lambda run_id: None
        run_id = runs.submit("KPI1 total", "legacy-mysql", profile_id="sales")["run_id"]
        runs.execute(run_id)
        state = runs.store.get(run_id)
        self.assertEqual(state["status"], "WAITING_INPUT")
        self.assertEqual(state["request"]["request_kind"], "understanding")
        self.llm.generate_sql.assert_not_called()
        self.mcp.call_mcp_server_with_config.assert_not_called()
        answer = "Sum the per-line products; do not multiply component totals."
        runs.respond(run_id, state["request"]["request_id"], state["plan_version"], answer)
        runs.execute(run_id)
        self.assertEqual(runs.store.get(run_id)["status"], "SUCCEEDED")
        self.assertIn(answer, self.llm.generate_sql.call_args.args[0])

    def test_direct_sql_api_reports_semantic_ambiguity_without_querying(self):
        self.configure_product_definition()
        self.llm.generate_response.return_value = json.dumps({
            "intent": "query", "followup": False,
            "slots": {"metrics": {"value": ["kpi1"], "span": [0, 4]}},
            "clarification": "Which aggregation should apply to KPI1?"})
        service = BIService(FrozenConfig(snapshot_config(self.config, "sales")), self.mcp, self.llm)
        with patch("backend.routers.chat.scoped_service", return_value=service):
            for endpoint in ("/api/chat/query", "/api/chat/generate-sql"):
                with self.subTest(endpoint=endpoint):
                    response = TestClient(app).post(endpoint, json={
                        "question": "KPI1 total", "datasource_id": "legacy-mysql", "profile_id": "sales"})
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertIn("Clarification required", response.text)
        self.llm.generate_sql.assert_not_called()
        self.mcp.call_mcp_server_with_config.assert_not_called()

    def test_snapshot_limits_every_resource_without_mutating_global_config(self):
        selected = profile()
        selected["datasources"]["legacy-athena"] = ["athena_orders"]
        selected["knowledge_ids"] = ["sales"]
        self.config.save_profile(selected)
        frozen = FrozenConfig(snapshot_config(self.config, "sales"))
        self.assertEqual(set(frozen.load_datasources()), {"legacy-mysql", "legacy-athena"})
        self.assertEqual(set(frozen.resolve_datasource("mysql")["schema"]["tables"]), {"mysql_orders"})
        self.assertEqual(set(frozen.load_mcp_config()), {"mysql", "athena"})
        self.assertEqual([doc["id"] for doc in frozen.load_knowledge()["documents"]], ["sales"])
        self.assertEqual(KnowledgeIndex(frozen.load_knowledge()).search("private"), [])
        self.assertIn("private_orders", self.config.resolve_datasource("mysql")["schema"]["tables"])
        self.assertIn("playwright", self.config.load_mcp_config())
        self.assertEqual(snapshot_config(frozen)["profile"], selected)

    def test_empty_resource_lists_never_expand_to_global_resources(self):
        frozen = FrozenConfig(snapshot_config(self.config, "sales"))
        self.assertEqual(frozen.load_knowledge()["documents"], [])
        self.assertEqual(frozen.load_methods()["methods"], [])
        with self.assertRaises(ValueError):
            ToolInvoker(frozen, self.mcp, ToolBudget()).call("external.search", {"query": "sales"},
                                                          "legacy:playwright:search_web")
        self.mcp.call_mcp_server.assert_not_called()

    def test_ontology_keeps_only_in_scope_physical_definitions_and_global_concepts(self):
        self.config.save_semantics({"entities": {
            "orders": {"description": "Orders", "mappings": {"legacy-mysql": {"table": "mysql_orders"}}},
            "private": {"description": "Private orders", "mappings": {"legacy-mysql": {"table": "private_orders"}}},
            "concept": {"description": "General concept"},
        }, "relations": [{"from": "orders", "to": "private"}]})
        scoped = FrozenConfig(snapshot_config(self.config, "sales")).load_semantics()
        self.assertEqual(set(scoped["entities"]), {"orders", "concept"})
        self.assertEqual(scoped["relations"], [])
        self.assertIn("private", self.config.load_semantics()["entities"])

    def test_missing_or_empty_tables_and_unknown_resources_are_explicit_errors(self):
        for replacement in ({"datasources": {}}, {"datasources": {"legacy-mysql": []}},
                            {"datasources": {"legacy-mysql": ["missing"]}}, {"knowledge_ids": ["missing"]},
                            {"mcp_servers": ["missing"]}):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.config.save_profile({**profile(), **replacement})
        self.config.save_knowledge({"documents": []})
        selected = profile()
        selected["knowledge_ids"] = ["sales"]
        with self.assertRaises(ValueError):
            self.config.save_profile(selected)

    def test_physical_table_scope_rejects_qualified_cte_join_and_subquery_escapes(self):
        source = FrozenConfig(snapshot_config(self.config, "sales")).resolve_datasource("mysql")
        for sql in ("SELECT * FROM mysql_orders", "SELECT * FROM mysql_test.mysql_orders",
                    "WITH x AS (SELECT * FROM mysql_orders) SELECT * FROM x",
                    "SELECT * FROM (SELECT * FROM mysql_orders) a"):
            self.assertEqual(validate_profile_sql(sql, source), sql)
        for sql in ("SELECT * FROM private_orders", "SELECT * FROM other.mysql_orders",
                    "WITH mysql_orders AS (SELECT * FROM private_orders) SELECT * FROM mysql_orders",
                    "SELECT * FROM mysql_orders a JOIN private_orders b ON 1=1",
                    "SELECT * FROM mysql_orders WHERE EXISTS (SELECT 1 FROM private_orders)"):
            with self.subTest(sql=sql), self.assertRaisesRegex(ValueError, "outside the Profile"):
                validate_profile_sql(sql, source)

    def test_queries_and_metadata_enforce_scope_before_invoking_adapters(self):
        frozen = FrozenConfig(snapshot_config(self.config, "sales"))
        invoker = ToolInvoker(frozen, self.mcp, ToolBudget())
        for capability, args in (
            ("database.query", {"datasource_id": "legacy-mysql", "sql": "SELECT * FROM private_orders"}),
            ("database.preview", {"datasource_id": "legacy-mysql", "table": "private_orders"}),
            ("database.query", {"datasource_id": "legacy-athena", "sql": "SELECT * FROM athena_orders"}),
        ):
            with self.assertRaises(ValueError):
                invoker.call(capability, args)
        result = invoker.call("database.metadata", {"datasource_id": "legacy-mysql"})
        self.assertEqual(result["tables"], ["mysql_orders"])
        self.mcp.call_mcp_server_with_config.assert_not_called()
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        invoker.call("database.query", {"datasource_id": "legacy-mysql", "sql": "SELECT * FROM mysql_orders"})
        self.mcp.call_mcp_server_with_config.assert_called_once()

    def test_generate_sql_endpoint_cannot_return_out_of_scope_sql(self):
        self.llm.generate_sql.return_value = "SELECT * FROM private_orders"
        scoped = BIService(FrozenConfig(snapshot_config(self.config, "sales")), self.mcp, self.llm)
        with self.assertRaisesRegex(ValueError, "outside the Profile"):
            scoped.generate_sql("show rows", "legacy-mysql")

    def test_profiles_are_frozen_per_run_and_conversations_are_isolated(self):
        first = self.runs.submit("sales", "legacy-mysql", session_id="conversation", profile_id="sales")
        snapshot = self.runs.store.get(first["run_id"], private=True)["snapshot"]
        changed = profile()
        changed["knowledge_ids"] = ["sales"]
        self.config.save_profile(changed)
        self.assertEqual(snapshot["knowledge"]["documents"], [])
        self.config.save_profile(profile("other"))
        with self.assertRaisesRegex(ValueError, "conversation"):
            self.runs.submit("other", "legacy-mysql", session_id="conversation", profile_id="other")
        second = self.runs.submit("other", "legacy-mysql", session_id="other-conversation", profile_id="other")
        legacy = self.runs.submit("legacy", "legacy-mysql")
        self.assertEqual(self.runs.store.history_page(profile_id="sales")["items"][0]["run_id"], first["run_id"])
        self.assertEqual(self.runs.store.history_page(profile_id="other")["items"][0]["run_id"], second["run_id"])
        self.assertEqual(self.runs.store.history_page(profile_id="")["items"][0]["run_id"], legacy["run_id"])
        self.runs.cancel(first["run_id"])
        retry = self.runs.retry(first["run_id"], refresh=True)
        self.assertEqual(retry["profile_id"], "sales")
        refreshed = self.runs.store.get(retry["run_id"], private=True)["snapshot"]
        self.assertEqual(refreshed["knowledge"]["documents"][0]["id"], "sales")
        self.config.delete_profile("sales")
        with self.assertRaisesRegex(ValueError, "Unknown Profile"):
            self.runs.retry(first["run_id"])
        self.assertEqual(self.runs.store.get(first["run_id"], private=True)["snapshot"], snapshot)

    def test_api_profile_crud_and_submit_share_validation(self):
        with patch("backend.routers.profiles.ConfigManager", return_value=self.config), \
                patch("backend.routers.runs.get_run_service", return_value=self.runs), \
                patch.object(self.runs, "start"):
            client = TestClient(app)
            self.assertEqual(client.put("/api/profiles/api", json=profile("api")).status_code, 200)
            self.assertIn("api", client.get("/api/profiles").json())
            response = client.post("/api/runs", json={"question": "rows", "database": "legacy-mysql",
                "profile_id": "api", "submission_id": "api-scope"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["profile_id"], "api")
            self.assertEqual(client.post("/api/runs", json={"question": "rows", "database": "legacy-athena",
                "profile_id": "api", "submission_id": "outside"}).status_code, 400)
            self.assertEqual(client.delete("/api/profiles/api").status_code, 200)

    def test_multi_source_profile_plan_executes_only_selected_tables(self):
        selected = profile()
        selected["datasources"]["legacy-athena"] = ["athena_orders"]
        self.config.save_profile(selected)
        frozen = FrozenConfig(snapshot_config(self.config, "sales"))
        bi = BIService(frozen, self.mcp, self.llm)
        self.llm.generate_sql.side_effect = ["SELECT * FROM mysql_orders", "SELECT * FROM athena_orders"]
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        plan = {"steps": [
            {"step_id": 1, "step_type": "sql_query", "datasource_id": "legacy-mysql", "dependencies": []},
            {"step_id": 2, "step_type": "sql_query", "datasource_id": "legacy-athena", "dependencies": [1]},
        ]}
        result = bi.execute_plan(plan, "show both", "legacy-mysql")
        self.assertTrue(result["completed"])
        self.assertEqual(self.mcp.call_mcp_server_with_config.call_count, 2)


class WorkflowConfigTests(ConfigTestCase):
    def test_editable_defaults_replace_instructions_but_not_runtime_scope(self):
        from utils.prompts import DEFAULT_PROMPTS, EXECUTION_CONTRACT
        from utils.model_router import NODE_ROLES
        self.assertEqual(set(DEFAULT_PROMPTS), set(NODE_ROLES))
        self.config.save_profile(profile())
        settings = {"nodes": {"sql_generation": {"prompt_template": "CUSTOM SQL RULES", "example_mode": "one_shot",
            "examples": [{"profile_id": "sales", "input": "sales demonstration", "output": "SELECT 1"},
                         {"profile_id": "other", "input": "SECRET OTHER PROFILE", "output": "SELECT 2"},
                         {"profile_id": None, "input": "LEGACY MODE EXAMPLE", "output": "SELECT 3"}]}}}
        self.config.save_workflow_config(settings)
        frozen = FrozenConfig(snapshot_config(self.config, "sales"))
        self.assertEqual(len(frozen.load_workflow_config()["nodes"]["sql_generation"]["examples"]), 1)
        self.llm.generate_sql.return_value = "SELECT * FROM outside_profile"
        bi = BIService(frozen, self.mcp, self.llm)
        with self.assertRaisesRegex(ValueError, "outside the Profile"):
            bi.generate_sql("Current sales question", "mysql")
        sent = self.llm.generate_sql.call_args.args[0]
        self.assertIn("CUSTOM SQL RULES", sent)
        self.assertIn("sales demonstration", sent)
        self.assertIn("Current sales question", sent)
        self.assertIn("mysql_orders", sent)
        self.assertIn(EXECUTION_CONTRACT, sent)
        self.assertNotIn(DEFAULT_PROMPTS["sql_generation"], sent)
        self.assertNotIn("SECRET OTHER PROFILE", sent)
        self.assertNotIn("LEGACY MODE EXAMPLE", sent)
        self.assertEqual(bi.router.records[0]["example_count"], 1)
        self.mcp.call_mcp_server_with_config.assert_not_called()

    def test_one_shot_few_shot_and_no_matching_profile_have_exact_example_counts(self):
        from utils.prompts import compose_prompt
        self.config.save_profile(profile())
        examples = [{"profile_id": "sales", "input": f"example-{n}", "output": "SELECT 1"} for n in range(3)]
        for mode, count in (("zero_shot", 0), ("one_shot", 1), ("few_shot", 3)):
            self.config.save_workflow_config({"nodes": {"sql_generation": {"example_mode": mode, "examples": examples}}})
            frozen = FrozenConfig(snapshot_config(self.config, "sales"))
            sent, selected = compose_prompt(frozen, "sql_generation", "actual input")
            self.assertEqual(len(selected), count)
            for index in range(3):
                self.assertEqual(f"example-{index}" in sent, index < count)
            unscoped, selected = compose_prompt(self.config, "sql_generation", "actual input")
            self.assertEqual(selected, [])
            self.assertNotIn("example-0", unscoped)

    def test_example_validation_rejects_partial_rows_and_over_budget(self):
        for examples in ([{"input": "", "output": "result"}],
                         [{"input": "question", "output": "result", "profile_id": 1}],
                         [{"input": "question", "output": "result"}] * 9):
            with self.assertRaises(ValueError):
                self.config.save_workflow_config({"nodes": {"planning": {"examples": examples}}})

    def test_named_role_and_node_models_follow_global_connection_without_duplicated_secrets(self):
        from utils.model_router import effective_model
        from utils.model_config import available_models, model_name
        original = self.config.load_llm_config()
        self.config.save_model_catalog(original, ["fast-model", "sql-model", "fast-model"])
        self.assertEqual(available_models(original, self.config.load_model_catalog()), ["fast-model", "sql-model"])
        self.assertNotIn("test-key", str(self.config.load_model_catalog()))
        self.config.save_model_roles({"fast": {"model_name": "fast-model"}})
        self.config.save_workflow_config({"nodes": {"understanding": {"model_name": "sql-model"}}})
        _, model, origin, _ = effective_model(self.config, "fast", "understanding")
        self.assertEqual(model_name(model), "sql-model")
        self.assertEqual(origin, "node_override")
        self.assertEqual(model["openai"]["api_key"], original["openai"]["api_key"])
        frozen = FrozenConfig(snapshot_config(self.config))
        original["openai"]["api_key"] = "new-test-key"
        self.config.save_llm_config(original)
        self.assertEqual(available_models(original, self.config.load_model_catalog()), [])
        self.assertEqual(effective_model(self.config, "fast")[1]["openai"]["api_key"], "new-test-key")
        self.assertEqual(effective_model(frozen, "fast")[1]["openai"]["api_key"], "test-key")
        with self.assertRaises(ValueError):
            self.config.save_model_catalog(original, [])

    def test_node_role_global_precedence_and_prompt_are_frozen_and_audited(self):
        role_model = {"provider": "custom", "custom": {"model": "role-model"}}
        node_model = {"provider": "custom", "custom": {"model": "node-model"}}
        self.config.save_model_roles({"reasoning": role_model})
        self.config.save_workflow_config({"nodes": {
            "planning": {"role": "reasoning", "model": node_model, "prompt": "Check comparison definitions"},
            "understanding": {"role": "reasoning", "prompt": ""},
        }})
        frozen = FrozenConfig(snapshot_config(self.config))
        self.config.save_workflow_config({})
        router = ModelRouter(frozen)
        with patch("utils.model_router.LLMClient") as client:
            for node, role, expected in (("planning", "reasoning", node_model),
                                         ("understanding", "fast", role_model),
                                         ("sql_generation", "sql", self.config.load_llm_config())):
                router.call(role, "generate_response", "Required JSON contract", node=node)
                self.assertEqual(client.call_args.args[0], expected)
            planning_call = client.return_value.generate_response.call_args_list[0]
            self.assertIn("Required JSON contract", planning_call.args[0])
            self.assertIn("Check comparison definitions", planning_call.args[0])
            self.assertNotIn("node", planning_call.kwargs)
        self.assertEqual([record["config_source"] for record in router.records],
                         ["node_override", "role_override", "global_default"])
        self.assertEqual([record["node"] for record in router.records], ["planning", "understanding", "sql_generation"])
        self.assertEqual(len(router.records[0]["prompt_version"]), 64)

    def test_invalid_node_configuration_and_changed_prompt_invalidate_reuse(self):
        for value in ({"nodes": {"cancel": {}}}, {"nodes": {"planning": {"role": "unknown"}}},
                      {"nodes": {"planning": {"prompt": 2}}}, {"nodes": {"planning": {"model": {}}}}):
            with self.assertRaises(ValueError):
                self.config.save_workflow_config(value)
        before = snapshot_config(self.config)
        self.config.save_workflow_config({"nodes": {"planning": {"prompt": "Compare carefully"}}})
        after = snapshot_config(self.config)
        self.assertFalse(step_compatible({"step_type": "llm_analysis"}, before, after))
        old = deepcopy(before)
        old.pop("workflow")
        self.assertEqual(FrozenConfig(old).load_workflow_config(), {})
