from unittest.mock import patch

from tests.helpers import ConfigTestCase, query_response
from utils.mcp_tools_registry import MCPToolRegistry
from utils.tool_catalog import ToolCatalog, server_version, version_of
from utils.tool_execution import ToolInvoker
from utils.model_router import ToolBudget
from utils.mcp_tool_handler import MCPToolCallHandler
from utils.run_service import FrozenConfig, RunService, snapshot_config
from utils.run_store import RunStore
from utils.tool_management import TEMPLATES, ToolManagement
from utils.bi_service import BIService
import json


class CatalogTests(ConfigTestCase):
    def test_connect_discovery_is_explicit_and_tools_remain_disabled_until_confirmed(self):
        from copy import deepcopy
        settings = deepcopy(TEMPLATES["http"])
        settings.update(url="http://example.invalid/mcp", categories=["external_api"])
        management = ToolManagement(self.config, self.mcp)
        self.mcp.get_server_info.return_value = {"tools": [
            {"name": "lookup", "description": "Lookup a record", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": True}}]}
        with self.assertRaises(ValueError):
            management.connect_server("new", settings)
        self.assertNotIn("new", self.config.load_mcp_config())
        self.mcp.get_server_info.assert_not_called()
        management.connect_server("new", settings, confirmed=True)
        catalog = ToolCatalog(self.config)
        identity = "mcp:new:lookup"
        tool = catalog.entries[identity]
        self.assertFalse(tool["enabled"])
        self.assertTrue(tool["available"])
        self.assertEqual(tool["capabilities"], ["mcp.new.lookup"])
        management.update_tool(identity, {"enabled": True})
        self.mcp.call_mcp_server.return_value = {"result": {"value": "lookup-value"}}
        result = ToolInvoker(self.config, self.mcp, ToolBudget()).call("mcp.new.lookup", {}, identity)
        self.assertEqual(result["value"], "lookup-value")
        management.update_tool(identity, {"enabled": False})
        with self.assertRaisesRegex(ValueError, "disabled"):
            ToolInvoker(self.config, self.mcp, ToolBudget()).call("mcp.new.lookup", {}, identity)
        self.mcp.call_mcp_server.assert_called_once()

    def test_failed_one_click_discovery_is_disabled_and_reports_error(self):
        from copy import deepcopy
        settings = deepcopy(TEMPLATES["http"])
        settings["url"] = "http://example.invalid/mcp"
        self.mcp.get_server_info.return_value = {"error": "Handshake failed"}
        with self.assertRaisesRegex(RuntimeError, "saved as disabled.*Handshake failed"):
            ToolManagement(self.config, self.mcp).connect_server("broken", settings, confirmed=True)
        self.assertEqual(self.config.load_mcp_config()["broken"]["status"], "inactive")
        self.assertNotIn("broken", self.config.load_tool_discovery().get("servers", {}))

    def test_malformed_tool_schema_discovery_fails_explicitly(self):
        settings = {**TEMPLATES["http"], "url": "http://example.invalid/mcp"}
        self.mcp.get_server_info.return_value = {"tools": [{"name": "broken"}]}
        with self.assertRaisesRegex(RuntimeError, "inputSchema"):
            ToolManagement(self.config, self.mcp).connect_server("broken", settings, confirmed=True)

    def discover(self, server="fixture", mapping=None, tools=None):
        servers = self.config.load_mcp_config()
        servers[server] = {"protocol": "mcp", "type": "streamable_http",
                           "url": "http://example.invalid/mcp", "status": "active",
                           "categories": ["fetch"], "when_to_use": "Read a known URL.",
                           "capabilities": mapping or {"external.fetch": "fetch"}}
        self.config.save_mcp_config(servers)
        self.config.save_tool_discovery(server, {
            "config_version": server_version(servers[server]), "discovered_at": "2026-10-17",
            "tools": tools or [{"name": "fetch", "description": "Fetch",
                                "inputSchema": {"type": "object"},
                                "annotations": {"readOnlyHint": True}}],
        })

    def test_local_definitions_and_legacy_schemas_share_identity(self):
        catalog = ToolCatalog(self.config)
        registry = MCPToolRegistry()
        self.assertEqual(catalog.resolve("database.query")["tool_id"], "local:database.query")
        self.assertEqual(registry.get_tool("database_query")["inputSchema"],
                         catalog.resolve("database.query")["input_schema"])
        self.assertEqual(registry.get_tool("mysql_query")["tool_id"], "local:database.query")
        for operation in ("join", "aggregate", "ratio", "difference"):
            self.assertEqual(catalog.resolve(f"compute.{operation}")["output_kind"], "calculation")

    def test_configuration_migration_is_idempotent_and_preserves_servers(self):
        before = self.config.load_mcp_config()
        first = self.config.load_tools_config()
        self.assertEqual(first, self.config.load_tools_config())
        self.assertEqual(before, self.config.load_mcp_config())
        first["future_extension"] = {"keep": True}
        self.config.save_tools_config(first)
        self.assertEqual(self.config.load_tools_config()["future_extension"], {"keep": True})
        self.assertIsInstance(self.config.load_mcp_config()["mysql"]["capabilities"], list)

    def test_provider_ambiguity_requires_selection_and_disable_is_immediate(self):
        self.discover()
        catalog = ToolCatalog(self.config)
        with self.assertRaisesRegex(ValueError, "explicit"):
            catalog.resolve("external.fetch")
        settings = self.config.load_tools_config()
        settings["default_providers"]["external.fetch"] = "mcp:fixture:fetch"
        self.config.save_tools_config(settings)
        self.assertEqual(ToolCatalog(self.config).resolve("external.fetch")["tool_id"], "mcp:fixture:fetch")
        settings["tools"]["mcp:fixture:fetch"] = {"enabled": False}
        self.config.save_tools_config(settings)
        with self.assertRaises(ValueError):
            ToolCatalog(self.config).resolve("external.fetch")
        self.assertNotIn("mcp:fixture:fetch", [tool["tool_id"] for tool in ToolCatalog(self.config).candidates()])
        self.assertIn("mcp:fixture:fetch", [tool["tool_id"] for tool in catalog.candidates()])

    def test_categories_are_overrides_not_copies_and_rename_preserves_identity(self):
        self.discover(tools=[
            {"name": name, "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}
            for name in ("fetch", "other")])
        settings = self.config.load_tools_config()
        settings["tools"]["mcp:fixture:other"] = {"categories": ["knowledge", "fetch"]}
        settings["categories"]["fetch"] = "Renamed"
        self.config.save_tools_config(settings)
        catalog = ToolCatalog(self.config)
        self.assertEqual(catalog.entries["mcp:fixture:other"]["categories"], ["knowledge", "fetch"])
        self.assertEqual(len([item for item in catalog.list() if item.get("server_id") == "fixture"]), 2)

    def test_changed_server_requires_new_discovery_without_network_on_catalog_read(self):
        self.discover()
        servers = self.config.load_mcp_config()
        servers["fixture"]["url"] = "http://example.invalid/new-mcp"
        self.config.save_mcp_config(servers)
        with patch("subprocess.run") as process:
            catalog = ToolCatalog(self.config)
        process.assert_not_called()
        self.assertNotIn("mcp:fixture:fetch", catalog.entries)

    def test_rediscovery_preserves_bound_plans_and_retry_but_schema_changes_do_not(self):
        self.discover()
        definition = ToolCatalog(self.config).entries["mcp:fixture:fetch"]
        legacy_version = version_of({key: value for key, value in definition.items()
                                     if key != "definition_version"})
        self.mcp.call_mcp_server.return_value = {"result": {"text": "Source body"}}
        runs = RunService(RunStore(self.config.config_dir / "discovery.sqlite3"), self.config,
                          lambda **kwargs: BIService(kwargs["config_manager"], self.mcp, self.llm))
        original = runs.submit("fetch", plan={"steps": [{
            "step_id": 1, "step_type": "external_data", "tool_id": definition["tool_id"],
            "tool_version": legacy_version, "data_requirements": {"url": "https://example.com"},
        }]})
        runs.execute(original["run_id"])
        self.assertEqual(runs.store.get(original["run_id"])["status"], "SUCCEEDED")
        discovery = self.config.load_tool_discovery()["servers"]["fixture"]
        discovery["discovered_at"] = "2026-10-18"
        self.config.save_tool_discovery("fixture", discovery)
        self.mcp.call_mcp_server.reset_mock()
        retried = runs.retry(original["run_id"])
        self.assertEqual(set(retried["steps"]), {"1"})
        runs.execute(retried["run_id"])
        self.assertEqual(runs.store.get(retried["run_id"])["status"], "SUCCEEDED")
        self.mcp.call_mcp_server.assert_not_called()
        refreshed = runs.retry(original["run_id"], refresh=True)
        runs.execute(refreshed["run_id"])
        self.assertEqual(runs.store.get(refreshed["run_id"])["status"], "SUCCEEDED")
        self.assertEqual(self.mcp.call_mcp_server.call_count, 1)
        discovery["tools"][0]["inputSchema"]["required"] = ["new_parameter"]
        self.config.save_tool_discovery("fixture", discovery)
        with self.assertRaisesRegex(ValueError, "version"):
            ToolInvoker(self.config, self.mcp, ToolBudget()).call(
                "external.fetch", {"url": "https://example.com"}, definition["tool_id"],
                definition["definition_version"])

    def test_compute_output_and_preexisting_definition_version_remain_compatible(self):
        self.llm.generate_sql.return_value = "SELECT 1 AS n, 2 AS d"
        self.mcp.call_mcp_server_with_config.return_value = {"result": {"success": True, "data": {
            "columns": ["n", "d"], "rows": [[1, 2]], "row_count": 1, "truncated": False}}}
        definition = ToolCatalog(self.config).resolve("compute.ratio")
        previous = {key: value for key, value in definition.items() if key != "definition_version"}
        previous["input_schema"]["properties"].pop("output")
        result = BIService(self.config, self.mcp, self.llm).execute_plan({"steps": [
            {"step_id": 1, "step_type": "sql_query"},
            {"step_id": 2, "step_type": "compute", "dependencies": [1],
             "tool_version": version_of(previous), "compute_requirements": {
                 "operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d", "output": "rate"}},
        ]}, "ratio", "mysql")
        self.assertEqual(result["execution_status"], "SUCCEEDED")
        self.assertEqual(result["steps"][2]["data"]["columns"], ["rate", "rate_numerator", "rate_denominator"])
        self.assertEqual(result["steps"][2]["data"]["rows"], [["0.5", "1", "2"]])

    def test_fetch_tail_page_cannot_become_complete_observation(self):
        self.discover()
        servers = self.config.load_mcp_config()
        servers["fixture"]["template"] = "fetch"
        self.config.save_mcp_config(servers)
        self.mcp.call_mcp_server.return_value = {"result": {"text": "Last page without a truncation marker"}}
        service = BIService(self.config, self.mcp, self.llm)
        result = service.execute_step({
            "step_id": 1, "step_type": "external_data", "tool_id": "mcp:fixture:fetch",
            "data_requirements": {"capability": "external.fetch", "arguments": {
                "url": "https://example.com", "start_index": 5000},
                "evidence_need": {"variable": "price"}},
        }, "price", "mysql", {})
        self.assertEqual(result["evidence_class"], "discovery")
        self.assertEqual(result["data"]["facts"], [])
        self.assertFalse(result["data"]["sources"][0]["complete"])
        self.assertEqual(result["data"]["sources"][0]["start_index"], 5000)
        self.llm.generate_response.assert_not_called()
        complete = service.invoker.call("external.fetch", {"url": "https://example.com"}, "mcp:fixture:fetch")
        self.assertTrue(complete["complete"])
        self.mcp.call_mcp_server.return_value = {"result": {"text": "Content truncated. Use start_index=5000."}}
        partial = service.invoker.call("external.fetch", {"url": "https://example.com"}, "mcp:fixture:fetch")
        self.assertFalse(partial["complete"])

    def test_unknown_schema_versions_and_invalid_policies_are_rejected(self):
        settings = self.config.load_tools_config()
        for change in ({"schema_version": 999},
                       {"tools": {"local:database.query": {"enabled": "false"}}},
                       {"tools": {"local:database.query": {"policy": {"concurrency": 0}}}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.config.save_tools_config({**settings, **change})

    def test_invocation_uses_frozen_sources_but_observes_live_disable(self):
        snapshot = FrozenConfig(snapshot_config(self.config))
        invoker = ToolInvoker(snapshot, self.mcp, ToolBudget(), ["legacy-mysql"], self.config)
        with self.assertRaisesRegex(ValueError, "active set"):
            invoker.call("database.query", {"datasource_id": "legacy-athena", "sql": "SELECT 1"})
        settings = self.config.load_tools_config()
        settings["tools"]["local:database.query"] = {"enabled": False}
        self.config.save_tools_config(settings)
        with self.assertRaisesRegex(ValueError, "disabled"):
            invoker.call("database.query", {"datasource_id": "legacy-mysql", "sql": "SELECT 1"})
        result = MCPToolCallHandler(self.mcp, self.config).execute_tool_call("mysql_query", {
            "sql": "SELECT 1", "config": {"host": "localhost", "username": "u",
                                         "password": "p", "database": "db"}})
        self.assertEqual(result["code"], "TOOL_DISABLED")
        self.mcp.call_mcp_server_with_config.assert_not_called()

    def test_invocation_validates_schema_version_and_dependency_references(self):
        invoker = ToolInvoker(self.config, self.mcp, ToolBudget())
        for arguments in ({"inputs": [7], "numerator": "n", "denominator": "d"},
                          {"inputs": [1], "numerator": "n", "denominator": "d", "code": "x"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                invoker.call("compute.ratio", arguments, results={1: {"status": "success"}})
        with self.assertRaisesRegex(ValueError, "version"):
            invoker.call("knowledge.search", {"query": "term"}, definition_version="stale")
        self.assertEqual(invoker.budget.records, [])

    @patch("utils.tool_management.shutil.which", return_value="/fixture/uvx")
    def test_new_server_requires_consent_discovery_and_per_tool_enable(self, which):
        management = ToolManagement(self.config, self.mcp)
        management.save_server("new_fetch", TEMPLATES["fetch"])
        self.mcp.get_server_info.assert_not_called()
        with self.assertRaisesRegex(ValueError, "Confirm"):
            management.discover("new_fetch")
        self.mcp.get_server_info.return_value = {"name": "fixture", "tools": [
            {"name": "fetch", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]}
        management.discover("new_fetch", confirmed=True)
        management.set_server_enabled("new_fetch", True)
        self.assertFalse(ToolCatalog(self.config).entries["mcp:new_fetch:fetch"]["enabled"])
        management.update_tool("mcp:new_fetch:fetch", {"enabled": True})
        self.assertEqual(ToolCatalog(self.config).resolve("external.fetch", "mcp:new_fetch:fetch")["tool_name"], "fetch")
        servers = self.config.load_mcp_config()
        servers["new_fetch"]["args"] = ["changed"]
        self.config.save_mcp_config(servers)
        with self.assertRaisesRegex(ValueError, "Discover"):
            management.set_server_enabled("new_fetch", True)

    def test_planner_uses_real_helper_calls_but_retains_only_public_summaries(self):
        schema = {"type": "object", "properties": {
            "thought": {"type": "string"}, "thoughtNumber": {"type": "integer"},
            "totalThoughts": {"type": "integer"}, "nextThoughtNeeded": {"type": "boolean"}},
            "required": ["thought", "thoughtNumber", "totalThoughts", "nextThoughtNeeded"]}
        self.discover(mapping={"reasoning.sequential_thinking": "sequentialthinking"}, tools=[
            {"name": "sequentialthinking", "inputSchema": schema}])
        service = BIService(self.config, self.mcp, self.llm)
        self.mcp.call_mcp_server.return_value = {"result": {
            "thoughtNumber": 1, "totalThoughts": 2, "nextThoughtNeeded": True, "private_echo": "PRIVATE"}}
        request = {"planning_tool_call": {"tool_id": "mcp:fixture:sequentialthinking",
                   "public_summary": "Compare the confirmed periods.", "arguments": {
                       "thought": "PRIVATE", "thoughtNumber": 1, "totalThoughts": 2, "nextThoughtNeeded": True}}}
        self.llm.generate_response.side_effect = [
            json.dumps(request), json.dumps(request),
            json.dumps({"steps": [{"step_id": 1, "step_type": "sql_query"}]})]
        plan = service.analysis_plan("compare", "mysql")
        self.assertEqual(self.mcp.call_mcp_server.call_count, 2)
        self.assertEqual(len(plan["planning_aids"]), 2)
        self.assertNotIn("PRIVATE", json.dumps(plan))
        self.assertNotIn("PRIVATE", json.dumps(service.tools.records))
        self.assertEqual(self.mcp.call_mcp_server.call_args.args[2]["thought"], request["planning_tool_call"]["public_summary"])
        self.assertEqual(plan["steps"][0]["tool_id"], "local:database.query")
        service = BIService(self.config, self.mcp, self.llm)
        self.llm.generate_response.side_effect = None
        self.llm.generate_response.return_value = json.dumps(request)
        with self.assertRaisesRegex(RuntimeError, "iteration budget"):
            service.analysis_plan("compare", "mysql")
        self.assertEqual(len(service.tools.records), 3)

    def test_tool_catalog_and_trial_api_share_validation_without_leaking_connections(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        management = ToolManagement(self.config, self.mcp)
        with patch("backend.routers.tools.ToolManagement", return_value=management):
            client = TestClient(app)
            response = client.get("/api/tools")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("test-key", response.text)
            self.assertNotIn("mysql_test", response.text)
            good = client.post("/api/tools/trial", json={
                "capability": "knowledge.search", "tool_id": "local:knowledge.search",
                "arguments": {"query": "unknown"}})
            self.assertEqual(good.status_code, 200, good.text)
            self.assertEqual(good.json()["result"]["data"]["chunks"], [])
            bad = client.post("/api/tools/trial", json={
                "capability": "compute.ratio", "tool_id": "local:compute.ratio",
                "arguments": {"inputs": [123], "numerator": "n", "denominator": "d"}})
            self.assertEqual(bad.status_code, 400)
        self.mcp.call_mcp_server.assert_not_called()

    def test_legacy_external_fetch_mapping_keeps_its_provider(self):
        self.config.save_mcp_config({"old_fetch": {
            "protocol": "mcp", "type": "streamable_http", "url": "http://example.invalid/mcp",
            "status": "active", "capabilities": {"external.fetch": "retrieve"}}})
        self.mcp.call_mcp_server.return_value = {"result": {"content": [
            {"type": "text", "text": "Retrieved source"}]}}
        result = BIService(self.config, self.mcp).call_capability(
            "external.fetch", {"url": "https://example.com"})
        self.assertEqual(result["text"], "Retrieved source")
        self.mcp.call_mcp_server.assert_called_once_with(
            "old_fetch", "retrieve", {"url": "https://example.com"})

    def test_retry_after_source_change_reuses_independent_branch(self):
        self.llm.generate_sql.return_value = "SELECT 1"
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        runs = RunService(RunStore(self.config.config_dir / "retry.sqlite3"), self.config,
                          lambda **kwargs: BIService(kwargs["config_manager"], self.mcp, self.llm))
        original = runs.submit("query", plan={"steps": [
            {"step_id": 1, "step_type": "sql_query", "datasource_id": "legacy-mysql"},
            {"step_id": 2, "step_type": "sql_query", "datasource_id": "legacy-athena"}]},
            datasource_ids=["legacy-mysql", "legacy-athena"])
        runs.execute(original["run_id"])
        source = self.config.resolve_datasource("legacy-mysql")
        self.config.save_datasource({**source, "config": {**source["config"], "host": "changed"}})
        retried = runs.retry(original["run_id"])
        self.assertEqual(set(retried["steps"]), {"2"})
        self.mcp.call_mcp_server_with_config.reset_mock()
        runs.execute(retried["run_id"])
        self.assertEqual(self.mcp.call_mcp_server_with_config.call_count, 1)
        self.assertEqual(runs.store.get(retried["run_id"])["status"], "SUCCEEDED")
