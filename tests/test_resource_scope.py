from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from tests.helpers import ConfigTestCase
from utils.analysis import MethodLibrary
from utils.bi_service import BIService
from utils.config_manager import ConfigManager
from utils.prompts import compose_prompt
from utils.query_knowledge import retrieve_query_guidance
from utils.resource_scope import ScopedConfig
from utils.run_context import FrozenConfig, snapshot_config, step_compatible


def ownership(owner=None):
    return {"visibility": "profile" if owner else "shared", "profile_id": owner}


def document(identifier, owner=None):
    return {**ownership(owner), "id": identifier, "title": identifier, "text": "Sales policy excludes refunds",
            "source": "manual", "version": "1", "scope": "*"}


def method(identifier="compare", owner=None):
    return {**ownership(owner), "id": identifier, "title": "Compare", "description": "Compare periods",
            "version": 1, "status": "draft", "preconditions": {}, "required_capabilities": [],
            "template": {"steps": []}}


class ResourceScopeTests(ConfigTestCase):
    def setUp(self):
        super().setUp()
        for owner in ("a", "b"):
            self.config.save_profile({"id": owner, "name": owner, "status": "draft", "datasources": {}})
        source = self.config.resolve_datasource("mysql")
        for owner in ("a", "b"):
            source["schema"]["tables"][f"{owner}_orders"] = [{"name": f"{owner}_field", "type": "text"}]
        source["schema"]["table_scopes"] = {
            f"{owner}_orders": ownership(owner) for owner in ("a", "b")}
        self.config.save_datasource(source)
        private = deepcopy(source)
        private.update(ownership("b"), datasource_id="private-b", name="Private B")
        private["schema"] = {"tables": {"b_table": [{"name": "b_secret"}]}}
        self.config.save_datasource(private)
        self.config.save_semantics({"metrics": {
            "sales": {"description": "Net sales exclude refunds"},
            "a_kpi": {**ownership("a"), "description": "A private KPI"},
            "b_kpi": {**ownership("b"), "description": "B private KPI"}}})
        self.config.save_knowledge({"documents": [document("shared"), document("a-doc", "a"), document("b-doc", "b")]})
        parent = method()
        parent["cases"] = [{**ownership(owner), "id": owner, "status": "draft",
                            "problem_structure": f"{owner} sales", "adaptation": "Rebind current dates"}
                           for owner in ("a", "b")]
        self.config.save_methods({"methods": [parent, method("private-method", "b")]})
        self.a = ScopedConfig(self.config, "a")
        self.b = ScopedConfig(self.config, "b")
        self.shared = ScopedConfig(self.config)

    def activate(self, owner="a", **extra):
        value = {"id": owner, "name": owner, "status": "active",
                 "datasources": {"legacy-mysql": ["mysql_orders"]}, **extra}
        self.config.save_profile(value)
        return value

    def guide(self, owner=None):
        return {**ownership(owner), "id": "sales-guide", "question": "Show company A net sales this month",
                "guidance": "Resolve company ID and current dates; clarify namesakes; exclude refunds.",
                "bindings": {"sources": {"legacy-mysql": ["mysql_orders"]},
                             "semantics": {"metrics": ["sales"]}, "knowledge": ["shared"], "methods": ["compare"]}}

    def test_catalog_visibility_and_table_parent_caps(self):
        self.assertEqual(set(self.a.load_datasources()), {"legacy-mysql", "legacy-athena"})
        self.assertIn("private-b", self.b.load_datasources())
        self.assertEqual(set(self.a.resolve_datasource("mysql")["schema"]["tables"]), {"mysql_orders", "a_orders"})
        self.assertEqual(set(self.shared.resolve_datasource("mysql")["schema"]["tables"]), {"mysql_orders"})
        self.assertEqual(set(self.a.load_semantics()["metrics"]), {"sales", "a_kpi"})
        self.assertEqual([doc["id"] for doc in self.a.load_knowledge()["documents"]], ["shared", "a-doc"])
        self.assertEqual([case["id"] for case in self.a.load_methods()["methods"][0]["cases"]], ["a"])
        with self.assertRaisesRegex(ValueError, "Unknown"):
            ScopedConfig(self.config, "missing")

    def test_scope_is_discovery_not_automatic_run_access(self):
        self.activate()
        frozen = snapshot_config(self.config, "a")
        self.assertEqual(set(frozen["sources"]), {"legacy-mysql"})
        self.assertEqual(set(frozen["sources"]["legacy-mysql"]["schema"]["tables"]), {"mysql_orders"})
        self.assertEqual(frozen["knowledge"]["documents"], [])
        self.assertEqual(frozen["methods"]["methods"], [])
        self.assertEqual(set(frozen["semantics"]["metrics"]), {"sales", "a_kpi"})
        self.assertNotIn("b_field", json.dumps(frozen))

    def test_unscoped_runs_are_shared_only_and_validate_tables(self):
        frozen = snapshot_config(self.config)
        self.assertTrue(frozen["resource_scoped"])
        self.assertNotIn("private-b", frozen["sources"])
        self.assertEqual([doc["id"] for doc in frozen["knowledge"]["documents"]], ["shared"])
        self.assertEqual(frozen["methods"]["methods"][0]["cases"], [])
        service = BIService(FrozenConfig(frozen), self.mcp, self.llm)
        self.llm.generate_sql.return_value = "SELECT b_field FROM b_orders"
        with self.assertRaisesRegex(ValueError, "outside"):
            service.generate_sql("sales", "legacy-mysql")
        self.mcp.call_mcp_server_with_config.assert_not_called()

    def test_draft_bootstrap_and_private_selection_validation(self):
        with self.assertRaisesRegex(ValueError, "draft"):
            snapshot_config(self.config, "a")
        with self.assertRaisesRegex(ValueError, "another Profile"):
            self.activate(datasources={"legacy-mysql": ["b_orders"]})
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            self.activate(datasources={"private-b": ["b_table"]})
        with self.assertRaisesRegex(ValueError, "knowledge_ids"):
            self.activate(knowledge_ids=["b-doc"])
        self.activate(datasources={"legacy-mysql": ["a_orders"]}, knowledge_ids=["a-doc"])

    def test_source_schema_saves_preserve_hidden_tables_and_reject_overwrite(self):
        source = self.a.resolve_datasource("mysql")
        source["name"] = "Renamed shared source"
        del source["schema"]["tables"]["mysql_orders"]
        self.a.save_datasource(source)
        full = self.config.resolve_datasource("legacy-mysql")
        self.assertEqual(set(full["schema"]["tables"]), {"a_orders", "b_orders"})
        source = self.a.resolve_datasource("mysql")
        source["schema"]["tables"]["b_orders"] = []
        with self.assertRaisesRegex(ValueError, "outside"):
            self.a.save_datasource(source)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.a.save_datasource({**source, "datasource_id": "private-b"})
        with self.assertRaisesRegex(ValueError, "another Profile"):
            self.a.delete_datasource("legacy-mysql")

    def test_semantic_saves_preserve_other_profile_and_hidden_relations(self):
        ontology = self.config.load_semantics()
        ontology["entities"] = {"a": {**ownership("a"), "description": "A"},
                                "b": {**ownership("b"), "description": "B"}}
        ontology["relations"] = [{"from": "a", "to": "b"}]
        self.config.save_semantics(ontology)
        scoped = self.a.load_semantics()
        scoped["metrics"]["a_kpi"]["description"] = "Updated A"
        self.a.save_semantics(scoped)
        saved = self.config.load_semantics()
        self.assertEqual(saved["metrics"]["b_kpi"], ontology["metrics"]["b_kpi"])
        self.assertEqual(saved["relations"], ontology["relations"])
        scoped["metrics"]["b_kpi"] = {"description": "Cannot replace hidden record"}
        with self.assertRaisesRegex(ValueError, "outside"):
            self.a.save_semantics(scoped)

    def test_shared_definitions_cannot_bind_private_schema_or_dimensions(self):
        for binding in ({"legacy-mysql": {"table": "a_orders", "columns": ["a_field"]}},
                        {"private-b": {"table": "b_table", "columns": ["b_secret"]}}):
            with self.subTest(binding=binding), self.assertRaisesRegex(ValueError, "private"):
                self.config.save_semantics({"metrics": {"bad": {"description": "bad", "mappings": binding}}})
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.config.save_semantics({"metrics": {"bad": {"description": "bad", "allowed_dimensions": ["a"]}},
                                        "dimensions": {"a": {**ownership("a"), "description": "A"}}})

    def test_library_saves_preserve_hidden_records_and_cases(self):
        docs = self.a.load_knowledge()
        docs["documents"] = [document("shared"), document("new-a", "a")]
        self.a.save_knowledge(docs)
        self.assertEqual({doc["id"] for doc in self.config.load_knowledge()["documents"]}, {"shared", "new-a", "b-doc"})
        library = self.a.load_methods()
        library["methods"][0]["cases"] = []
        self.a.save_methods(library)
        full = self.config.load_methods()
        self.assertEqual({item["id"] for item in full["methods"]}, {"compare", "private-method"})
        parent = next(item for item in full["methods"] if item["id"] == "compare")
        self.assertEqual([case["id"] for case in parent["cases"]], ["b"])
        with self.assertRaisesRegex(ValueError, "another Profile"):
            self.a.save_methods({"methods": []})
        library["methods"][0].update(ownership("a"))
        with self.assertRaisesRegex(ValueError, "parent method"):
            self.a.save_methods(library)

    def test_hidden_case_injection_and_duplicate_ids_rejected(self):
        library = self.a.load_methods()
        library["methods"][0]["cases"].append({**ownership("b"), "id": "injected", "status": "draft"})
        with self.assertRaisesRegex(ValueError, "outside"):
            self.a.save_methods(library)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.a.save_knowledge({"documents": [document("duplicate"), document("duplicate")]})
        with self.assertRaisesRegex(ValueError, "Unknown resource owner"):
            self.config.save_knowledge({"documents": [document("unknown", "missing")]})

    def test_invalid_resource_shapes_report_validation_errors(self):
        for value in ({"documents": {}}, {"documents": ["bad"]}, {"documents": [{"title": "Missing ID"}]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.a.save_knowledge(value)
        with self.assertRaises(ValueError):
            self.a.save_semantics({"metrics": {"invalid": "not an object"}})
        source = self.a.resolve_datasource("mysql")
        source["schema"]["table_scopes"]["a_orders"] = "profile"
        with self.assertRaisesRegex(ValueError, "object"):
            self.a.save_datasource(source)

    def test_concurrent_profile_writes_preserve_invisible_libraries(self):
        def save(owner):
            config = ScopedConfig(ConfigManager(self.config.config_dir), owner)
            for index in range(5):
                config.save_knowledge({"documents": [document(f"{owner}-{index}", owner)]})
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(save, ("a", "b")))
        self.assertEqual({doc["id"] for doc in self.config.load_knowledge()["documents"]}, {"a-4", "b-4"})

    def test_reference_safe_delete_and_narrowing(self):
        self.activate(knowledge_ids=["shared"], method_ids=["compare"])
        with self.assertRaisesRegex(ValueError, "Profile a"):
            self.shared.save_knowledge({"documents": []})
        docs = self.a.load_knowledge()
        docs["documents"][0].update(ownership("b"))
        with self.assertRaises(ValueError):
            self.config.save_knowledge(docs)
        with self.assertRaisesRegex(ValueError, "Profile a"):
            self.config.delete_datasource("legacy-mysql")
        with self.assertRaisesRegex(ValueError, "owns private"):
            self.config.delete_profile("a")
        self.activate()
        self.shared.save_knowledge({"documents": []})
        self.assertNotIn("shared", [doc["id"] for doc in self.config.load_knowledge()["documents"]])

    def test_column_changes_block_semantic_reference_breakage(self):
        ontology = self.config.load_semantics()
        ontology["metrics"]["sales"]["mappings"] = {
            "legacy-mysql": {"table": "mysql_orders", "columns": ["updated_at"]}}
        self.config.save_semantics(ontology)
        source = self.a.resolve_datasource("mysql")
        source["schema"]["tables"]["mysql_orders"] = [{"name": "renamed"}]
        with self.assertRaisesRegex(ValueError, "business definition sales"):
            self.a.save_datasource(source)

    def test_query_knowledge_requires_explicit_profile_dependencies(self):
        self.config.save_query_knowledge({"queries": [self.guide()]})
        with self.assertRaisesRegex(ValueError, "not selected"):
            self.activate(query_ids=["sales-guide"])
        self.activate(query_ids=["sales-guide"], knowledge_ids=["shared"], method_ids=["compare"])
        self.assertEqual(len(snapshot_config(self.config, "a")["query_knowledge"]["queries"]), 1)
        self.activate("b")
        self.assertEqual(snapshot_config(self.config, "b")["query_knowledge"]["queries"], [])
        changed = self.guide()
        changed["bindings"]["sources"]["legacy-athena"] = ["athena_orders"]
        with self.assertRaisesRegex(ValueError, "not selected"):
            self.config.save_query_knowledge({"queries": [changed]})
        with self.assertRaisesRegex(ValueError, "Profile a"):
            self.config.save_query_knowledge({"queries": []})

    def test_query_links_obey_ownership_and_block_dangling_deletes(self):
        guide = self.guide()
        guide["bindings"]["knowledge"] = ["a-doc"]
        with self.assertRaisesRegex(ValueError, "unavailable knowledge"):
            self.config.save_query_knowledge({"queries": [guide]})
        guide.update(ownership("a"))
        self.a.save_query_knowledge({"queries": [guide]})
        self.assertEqual(self.b.load_query_knowledge()["queries"], [])
        self.assertEqual(snapshot_config(self.config)["query_knowledge"]["queries"], [])
        with self.assertRaisesRegex(ValueError, "query knowledge"):
            self.a.save_knowledge({"documents": [document("shared")]})
        self.a.save_query_knowledge({"queries": []})
        self.a.save_knowledge({"documents": [document("shared")]})

    def test_query_retrieval_injects_guidance_and_policy_not_old_results(self):
        self.config.save_query_knowledge({"queries": [self.guide()]})
        self.activate(query_ids=["sales-guide"], knowledge_ids=["shared"], method_ids=["compare"])
        config = FrozenConfig(snapshot_config(self.config, "a"))
        guides = retrieve_query_guidance(config, "company net sales this month")
        self.assertEqual([guide["id"] for guide in guides], ["sales-guide"])
        self.assertEqual(guides[0]["knowledge_excerpts"][0]["id"], "shared")
        service = BIService(config, self.mcp, self.llm)
        prompt = service.sql_prompt("company net sales this month", "legacy-mysql")
        self.assertIn("clarify namesakes", prompt)
        self.assertIn("Sales policy excludes refunds", prompt)
        self.assertNotIn("b-doc", prompt)
        self.llm.generate_response.return_value = json.dumps({"intent": "query", "followup": False,
                                                             "slots": {}, "clarification": None})
        service.understand("company net sales this month", "legacy-mysql", {}, "2026-10-18T00:00:00Z")
        self.assertIn("clarify namesakes", self.llm.generate_response.call_args.args[0])
        self.assertEqual(retrieve_query_guidance(config, "unrelated weather"), [])

    def test_linked_methods_still_require_publication_and_compatibility(self):
        library = {"methods": [method("compatible"), method("incompatible"), method("draft")]}
        for item in library["methods"][:2]:
            item["status"] = "published"
        library["methods"][1]["required_capabilities"] = ["unavailable"]
        self.assertEqual([item["id"] for item in MethodLibrary(library).retrieve(
            "unrelated", [], {}, preferred_ids=["incompatible", "draft", "compatible"])], ["compatible"])

    def test_examples_private_then_shared_legacy_unchanged_and_max_eight(self):
        examples = [
            *[{**ownership(), "input": f"shared-{i}", "output": "shared answer"} for i in range(8)],
            {"profile_id": None, "input": "legacy-only", "output": "legacy"},
            {**ownership("a"), "input": "private-a", "output": "private answer"},
            {**ownership("b"), "input": "private-b", "output": "private answer"}]
        self.config.save_workflow_config({"nodes": {"sql_generation": {"example_mode": "few_shot", "examples": examples}}})
        self.activate()
        config = FrozenConfig(snapshot_config(self.config, "a"))
        text, selected = compose_prompt(config, "sql_generation", "Current question")
        self.assertEqual(len(selected), 8)
        self.assertIn("private-a", text)
        self.assertIn("shared-6", text)
        self.assertNotIn("shared-7", text)
        self.assertNotIn("private-b", text)
        self.assertNotIn("legacy-only", text)
        scoped = self.a.load_workflow_config()
        scoped["nodes"]["sql_generation"]["example_mode"] = "one_shot"
        self.a.save_workflow_config(scoped)
        text, selected = compose_prompt(FrozenConfig(snapshot_config(self.config, "a")), "sql_generation", "")
        self.assertEqual(len(selected), 1)
        self.assertIn("private-a", text)
        self.assertNotIn("shared-0", text)
        full = self.config.load_workflow_config()["nodes"]["sql_generation"]["examples"]
        self.assertEqual(len(full), 11)
        self.assertEqual(sum(item["input"] == "private-b" for item in full), 1)
        too_many = deepcopy(scoped)
        too_many["nodes"]["sql_generation"]["examples"].append(
            {**ownership(), "input": "ninth shared example", "output": "answer"})
        with self.assertRaises(ValueError):
            self.a.save_workflow_config(too_many)

    def test_snapshot_freezes_guidance_and_retries_check_scope(self):
        self.config.save_query_knowledge({"queries": [self.guide()]})
        self.activate(query_ids=["sales-guide"], knowledge_ids=["shared"], method_ids=["compare"])
        old = snapshot_config(self.config, "a")
        guide = self.guide()
        guide["guidance"] = "Updated definition"
        self.config.save_query_knowledge({"queries": [guide]})
        new = snapshot_config(self.config, "a")
        self.assertNotEqual(old["query_knowledge"], new["query_knowledge"])
        self.assertEqual(snapshot_config(FrozenConfig(old)), old)
        self.assertFalse(step_compatible({"step_type": "sql_query", "datasource_id": "legacy-mysql"}, old, new))

    def test_scope_aware_api_reads_writes_and_metadata(self):
        client = TestClient(app)
        with patch("backend.routers.semantics.ConfigManager", return_value=self.config), \
                patch("backend.routers.database.ConfigManager", return_value=self.config), \
                patch("backend.routers.database.DatabaseAdapter") as adapter:
            shared = client.get("/api/semantics/knowledge").json()
            self.assertEqual([doc["id"] for doc in shared["documents"]], ["shared"])
            response = client.put("/api/semantics/knowledge", params={"profile_id": "a"},
                                  json={"documents": [document("updated", "a")]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("b-doc", [doc["id"] for doc in self.config.load_knowledge()["documents"]])
            response = client.put("/api/semantics/knowledge", params={"profile_id": "a"},
                                  json={"documents": [document("b-doc")]})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(client.get("/api/database/sources/private-b/metadata").status_code, 400)
            adapter.return_value.metadata.return_value = {"tables": ["mysql_orders", "a_orders", "b_orders"]}
            response = client.get("/api/database/sources/legacy-mysql/metadata", params={"profile_id": "a"})
            self.assertEqual(response.json()["tables"], ["mysql_orders", "a_orders"])
            response = client.post("/api/database/sources", params={"profile_id": "a"},
                                   json=self.a.resolve_datasource("mysql"))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("b_orders", response.json()["schema"]["tables"])
            response = client.get("/api/database/sources/legacy-mysql/metadata",
                                  params={"profile_id": "a", "table": "b_orders"})
            self.assertEqual(response.status_code, 400)
            response = client.delete("/api/database/sources/legacy-athena")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("legacy-athena", self.config.load_datasources())
