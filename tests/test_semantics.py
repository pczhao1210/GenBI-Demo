import json
from unittest.mock import Mock, patch

from tests.helpers import ConfigTestCase
from utils.bi_service import BIService
from utils.model_router import ModelRouter
from utils.semantics import KnowledgeIndex
from utils.understanding import resolve_time, understand


class SemanticTests(ConfigTestCase):
    def extraction(self, question, patches, followup=False, context=None, ontology=None):
        model = Mock(return_value=json.dumps({"intent": "query", "followup": followup, "slots": patches,
                                             "clarification": None}))
        result = understand(question, context or {}, "2026-10-15T01:00:00+00:00",
                            {"datasource_id": "legacy-mysql", "timezone": "Asia/Shanghai"},
                            ontology or {}, model)
        return result, model

    def test_followup_only_patches_time_and_uses_current_request_date(self):
        context = {
            "entities": {"value": ["shop"], "origin": "current"},
            "metrics": {"value": ["sales"], "origin": "current"},
            "time": {"value": {"start": "2000-01-01"}, "origin": "current"},
            "filters": {"value": {"exclude": "refund"}, "origin": "current"},
        }
        ontology = {"entities": {"shop": {}}, "metrics": {"sales": {
            "allowed_dimensions": [], "mappings": {"legacy-mysql": {}}}}}
        result, model = self.extraction("前天呢", {"time": {"value": {"expression": "前天"}, "span": [0, 2]}},
                                        True, context, ontology)
        slots = result["slots"]
        self.assertEqual(slots["metrics"]["value"], ["sales"])
        self.assertEqual(slots["filters"]["value"], {"exclude": "refund"})
        self.assertEqual(slots["time"]["value"]["start"], "2026-10-13T00:00:00+08:00")
        self.assertEqual(context["time"]["value"]["start"], "2000-01-01")
        self.assertEqual(model.call_args.args[0], "fast")

    def test_business_day_and_invalid_times(self):
        result = resolve_time({"expression": "昨天"}, "2026-10-15T01:00:00+08:00", "Asia/Shanghai", 4)
        self.assertEqual(result["start"], "2026-10-13T04:00:00+08:00")
        with self.assertRaises(ValueError):
            resolve_time({"start": "2026-10-15", "end": "2026-10-14"}, "2026-10-15T00:00:00Z", "UTC")

    def test_unknown_ids_and_spans_do_not_execute(self):
        for patch in ({"metrics": {"value": ["missing"], "span": [0, 1]}},
                      {"metrics": {"value": [], "span": [0, 99]}}):
            with self.assertRaises(ValueError):
                self.extraction("sales", patch)

    def test_incompatible_metric_and_multiple_references_request_clarification(self):
        ontology = {"metrics": {"sales": {"allowed_dimensions": [], "mappings": {}}}}
        result, _ = self.extraction("sales", {"metrics": {"value": ["sales"], "span": [0, 5]}},
                                    ontology=ontology)
        self.assertIn("not computable", result["clarification"])
        result, _ = self.extraction("that", {"result_reference": {"value": ["1", "2"], "span": [0, 4]}})
        self.assertIn("Multiple", result["clarification"])

    def test_knowledge_search_is_scoped_and_traceable(self):
        knowledge = {"documents": [{"id": "one", "title": "Conversion ratio", "text": "Orders divided by visits",
                                   "source": "manual#2", "version": "3", "scope": "retail"}]}
        index = KnowledgeIndex(knowledge)
        self.assertEqual(index.search("conversion", scope="finance"), [])
        chunk = index.search("conversion", scope="retail")[0]
        self.assertEqual(chunk["source"], "manual#2")
        self.assertEqual(chunk["chunk_id"], "one:0")
        self.assertEqual(chunk["version"], "3")

    def test_role_routing_and_budget_never_silently_fallback(self):
        roles = {"reasoning": {"provider": "custom", "custom": {"model": "strong"}}}
        self.config.save_model_roles(roles)
        router = ModelRouter(self.config, max_calls=1)
        with patch("utils.model_router.LLMClient") as client:
            client.return_value.generate_response.side_effect = RuntimeError("unavailable")
            with self.assertRaises(RuntimeError):
                router.call("reasoning", "generate_response", "plan")
            self.assertEqual(client.call_args.args[0], roles["reasoning"])
            self.assertEqual(client.call_count, 1)
        self.assertEqual(router.records[0]["status"], "FAILED")
        with self.assertRaisesRegex(RuntimeError, "budget"):
            router.call("fast", "generate_response", "answer")

    def test_concept_explanation_does_not_need_database(self):
        self.config.save_knowledge({"documents": [{
            "id": "ratio", "title": "Conversion", "text": "Conversion is orders divided by visits",
            "source": "manual", "scope": "*", "version": "1"}]})
        service = BIService(self.config, self.mcp, self.llm)
        self.llm.generate_response.return_value = "Orders divided by visits [ratio:0]"
        answer = service.explain("Conversion")
        self.assertEqual(answer["citations"][0]["chunk_id"], "ratio:0")
        self.mcp.assert_not_called()
