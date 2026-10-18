from copy import deepcopy
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from tests.helpers import ConfigTestCase
from tests.test_profiles import profile
from tests.test_resource_scope import document, method, ownership
from utils.bi_service import BIService
from utils.knowledge_center import catalog_entries, entry_key, knowledge_context, preview_knowledge
from utils.query_knowledge import retrieve_query_guidance
from utils.resource_scope import ScopedConfig
from utils.run_context import FrozenConfig, snapshot_config, step_compatible


class KnowledgeCenterTests(ConfigTestCase):
    def guide(self, **changes):
        return {"id": "sales-guide", "question": "Company sales", "guidance": "Rebind company and dates.",
                **changes}

    def test_catalog_unifies_legacy_records_without_rewriting_ids(self):
        self.config.save_semantics({"metrics": {"old-id": {"description": "Old metric"}},
                                    "entities": {"company": {"description": "Company entity"}}})
        self.config.save_knowledge({"documents": [document("policy")]})
        parent = method()
        parent["cases"] = [{"id": "case", "status": "draft", "problem_structure": "Why sales changed?",
                            "adaptation": "Compare periods"}]
        self.config.save_methods({"methods": [parent]})
        self.config.save_query_knowledge({"queries": [self.guide()]})
        before = snapshot_config(self.config, catalog=True)
        entries = catalog_entries(self.config)
        self.assertEqual({entry["family"] for entry in entries}, {"definitions", "guides", "references"})
        self.assertEqual({entry["kind"] for entry in entries},
                         {"metrics", "entities", "queries", "methods", "cases", "documents"})
        self.assertEqual(next(entry for entry in entries if entry["kind"] == "metrics")["title"], "old-id")
        self.assertEqual(snapshot_config(self.config, catalog=True), before)
        self.assertNotEqual(entry_key("cases", "b:c", "a"), entry_key("cases", "c", "a:b"))

    def test_metric_business_fields_and_references_preserve_strict_constraints(self):
        ontology = {"metrics": {"sales": {
            "name": "Net sales", "description": "Sum line amounts less refunds",
            "subject": "Company sales from order lines", "dimension_notes": "Try month, region or product",
            "entity_ids": ["company"], "dimension_ids": ["month"], "allowed_dimensions": []}},
            "entities": {"company": {"description": "Company identified uniquely"}},
            "dimensions": {"month": {"description": "Calendar month"}}}
        self.config.save_semantics(ontology)
        self.assertEqual(self.config.load_semantics(), ontology)
        self.llm.generate_response.return_value = json.dumps({
            "intent": "query", "followup": False, "slots": {
                "metrics": {"value": ["sales"], "span": [0, 5]},
                "dimensions": {"value": ["month"], "span": [6, 11]}}, "clarification": None})
        result = BIService(self.config, self.mcp, self.llm).understand(
            "sales month", "legacy-mysql", {}, "2026-10-18T00:00:00Z")
        self.assertIn("incompatible", result["clarification"])
        prompt = self.llm.generate_response.call_args.args[0]
        self.assertIn("Net sales", prompt)
        self.assertIn("Company sales from order lines", prompt)
        self.assertIn("Try month, region or product", prompt)

    def test_free_text_dimensions_do_not_create_a_hard_allowlist(self):
        self.config.save_semantics({"metrics": {"sales": {
            "name": "Net sales", "description": "Sales", "dimension_notes": "Usually analyze by month"}},
            "dimensions": {"region": {"description": "Region"}}})
        self.llm.generate_response.return_value = json.dumps({
            "intent": "query", "followup": False, "slots": {
                "metrics": {"value": ["sales"], "span": [0, 5]},
                "dimensions": {"value": ["region"], "span": [6, 12]}}, "clarification": None})
        result = BIService(self.config, self.mcp, self.llm).understand(
            "sales region", "legacy-mysql", {}, "2026-10-18T00:00:00Z")
        self.assertIsNone(result["clarification"])
        self.assertNotIn("allowed_dimensions", self.config.load_semantics()["metrics"]["sales"])

    def test_metric_reference_validation_and_hidden_reference_preservation(self):
        self.config.save_profile(profile())
        ontology = {"metrics": {"sales": {"description": "Sales", "entity_ids": ["visitor"]}},
                    "entities": {"visitor": {"description": "Visitor",
                        "mappings": {"legacy-athena": {"table": "athena_orders", "columns": ["updated_at"]}}}}}
        self.config.save_semantics(ontology)
        frozen = snapshot_config(self.config, "sales")
        self.assertEqual(frozen["semantics"]["metrics"]["sales"]["entity_ids"], [])
        self.assertNotIn("visitor", frozen["semantics"]["entities"])
        with self.assertRaisesRegex(ValueError, "references"):
            self.config.save_semantics({"metrics": ontology["metrics"]})
        self.config.save_profile(profile("private"))
        with self.assertRaisesRegex(ValueError, "visibility"):
            self.config.save_semantics({"metrics": {"sales": {"description": "Sales", "entity_ids": ["private"]}},
                                        "entities": {"private": {**ownership("private"), "description": "private"}}})
        source = self.config.resolve_datasource("legacy-athena")
        source.update(ownership("private"))
        with self.assertRaisesRegex(ValueError, "business definition"):
            self.config.save_datasource(source)

    def test_stage_filters_do_not_remove_pinned_metric_constraints(self):
        self.config.save_semantics({"metrics": {"sales": {
            "name": "Net sales", "description": "Subtract refunds", "retrieval_stages": []}}})
        self.config.save_query_knowledge({"queries": [self.guide(
            guidance="Planning-specific guidance", retrieval_stages=["planning"])]})
        service = BIService(self.config, self.mcp, self.llm)
        sql = service.sql_prompt("Company sales", "legacy-mysql")
        self.assertIn("Subtract refunds", sql)
        self.assertNotIn("Planning-specific guidance", sql)
        planning = knowledge_context(self.config, "Company sales", "planning")
        self.assertEqual(planning["guides"][0]["guidance"], "Planning-specific guidance")
        understanding = knowledge_context(self.config, "Company sales", "understanding")
        self.assertEqual(understanding["guides"], [])
        preview = preview_knowledge(ScopedConfig(self.config), "Unrelated question", "sql_generation")
        self.assertEqual(preview["used"][0]["reason"], "pinned")
        self.assertEqual(preview["used"][0]["title"], "Net sales")

    def test_business_examples_are_retrievable_and_not_old_answer_replay(self):
        self.config.save_query_knowledge({"queries": [self.guide(examples=[{
            "question": "Unusual seasonal conversion anomaly",
            "guidance": "Compare current dates and product mix; do not reuse old values."}],
            old_sql="SELECT hidden FROM old_table", old_answer="stale figure 998877")]})
        result = retrieve_query_guidance(self.config, "seasonal conversion anomaly")
        self.assertEqual(result[0]["id"], "sales-guide")
        self.assertIn("current dates", result[0]["examples"][0]["guidance"])
        self.assertNotIn("old_table", json.dumps(result))
        self.assertNotIn("998877", json.dumps(result))

    def test_invalid_stages_and_business_examples_fail_explicitly(self):
        for stages in ("planning", ["unknown"], ["planning", "planning"]):
            with self.subTest(stages=stages), self.assertRaisesRegex(ValueError, "stages"):
                self.config.save_query_knowledge({"queries": [self.guide(retrieval_stages=stages)]})
        for examples in ([{"question": "Missing guidance"}], [{"question": "q", "guidance": "g"}] * 9):
            with self.subTest(examples=examples), self.assertRaisesRegex(ValueError, "examples"):
                self.config.save_query_knowledge({"queries": [self.guide(examples=examples)]})
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            knowledge_context(self.config, "sales", "presentation")

    def test_reference_stages_apply_to_linked_excerpts_and_cited_explanations(self):
        doc = {**document("policy"), "retrieval_stages": ["explanation"]}
        self.config.save_knowledge({"documents": [doc]})
        self.config.save_query_knowledge({"queries": [self.guide(bindings={"knowledge": ["policy"]})]})
        sql = knowledge_context(self.config, "Company sales", "sql_generation")
        self.assertEqual(sql["documents"], [])
        self.assertEqual(sql["guides"][0]["knowledge_excerpts"], [])
        explanation = knowledge_context(self.config, "sales policy refunds", "explanation")
        self.assertEqual(explanation["documents"][0]["id"], "policy")
        self.assertIn("chunk_id", explanation["documents"][0])

    def test_method_stages_still_enforce_publication_and_capabilities(self):
        parent = method()
        parent["required_capabilities"] = ["custom.capability"]
        parent["template"]["steps"] = [{"step_id": 1, "step_type": "sql_query",
                                        "description": "Query current sales", "dependencies": []}]
        parent["retrieval_stages"] = ["planning"]
        parent["validation"] = {"reviewer": "QA", "fixture_ids": ["sales"], "passed": True}
        self.config.save_query_knowledge({"queries": [self.guide()]})
        for status in ("draft", "validated", "published"):
            parent["status"] = status
            self.config.save_methods({"methods": [parent]})
        guide = self.guide(bindings={"methods": ["compare"]})
        self.config.save_query_knowledge({"queries": [guide]})
        self.assertEqual(knowledge_context(self.config, "Company sales", "planning", capabilities=[])["methods"], [])
        ready = knowledge_context(self.config, "Company sales", "planning", capabilities=["custom.capability"])
        self.assertEqual(ready["methods"][0]["id"], "compare")
        self.assertEqual(knowledge_context(self.config, "Company sales", "analysis",
                                          capabilities=["custom.capability"])["methods"], [])

    def test_preview_respects_profile_selection_and_reports_missing_dependencies(self):
        self.config.save_profile(profile())
        self.config.save_profile(profile("other"))
        self.config.save_knowledge({"documents": [document("policy"), document("other-private", "other")]})
        self.config.save_query_knowledge({"queries": [self.guide(bindings={
            "sources": {"legacy-athena": ["athena_orders"]}, "knowledge": ["policy"]})]})
        preview = preview_knowledge(ScopedConfig(self.config, "sales"), "Company sales", "planning")
        self.assertEqual(preview["context"]["guides"], [])
        guide = next(item for item in preview["outside_run_scope"] if item["kind"] == "queries")
        self.assertEqual(guide["missing"], ["legacy-athena/athena_orders", "policy"])
        self.assertNotIn("other-private", json.dumps(preview))
        self.llm.generate_response.assert_not_called()
        self.mcp.call_mcp_server_with_config.assert_not_called()

    def test_contexts_freeze_stage_configuration_and_invalidate_reuse(self):
        self.config.save_query_knowledge({"queries": [self.guide()]})
        old = snapshot_config(self.config)
        self.config.save_query_knowledge({"queries": [self.guide(retrieval_stages=[])]})
        new = snapshot_config(self.config)
        self.assertEqual(len(knowledge_context(FrozenConfig(old), "Company sales", "understanding")["guides"]), 1)
        self.assertEqual(knowledge_context(FrozenConfig(new), "Company sales", "understanding")["guides"], [])
        self.assertFalse(step_compatible({"step_type": "sql_query", "datasource_id": "legacy-mysql"}, old, new))

    def test_tool_bound_sql_cannot_reuse_results_after_reference_policy_changes(self):
        self.config.save_knowledge({"documents": [document("policy")]})
        old = snapshot_config(self.config)
        self.config.save_knowledge({"documents": [{**document("policy"), "text": "Changed refund policy"}]})
        new = snapshot_config(self.config)
        step = {"step_type": "sql_query", "datasource_id": "legacy-mysql", "tool_id": "local:database.query"}
        self.assertTrue(step_compatible(step, old, old))
        self.assertFalse(step_compatible(step, old, new))

    def test_catalog_and_preview_api_have_no_side_effects(self):
        self.config.save_knowledge({"documents": [document("policy")]})
        before = deepcopy(snapshot_config(self.config))
        with patch("backend.routers.semantics.ConfigManager", return_value=self.config):
            client = TestClient(app)
            catalog = client.get("/api/semantics/catalog")
            self.assertEqual(catalog.status_code, 200)
            self.assertEqual(catalog.json()[0]["kind"], "documents")
            self.assertNotIn("record", catalog.json()[0])
            preview = client.get("/api/semantics/preview", params={"q": "sales policy", "stage": "explanation"})
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["used"][0]["title"], "policy")
            self.assertEqual(client.get("/api/semantics/preview", params={"q": ""}).status_code, 400)
            self.assertEqual(client.get("/api/semantics/preview", params={"q": "sales", "stage": "bad"}).status_code, 400)
        self.assertEqual(snapshot_config(self.config), before)
