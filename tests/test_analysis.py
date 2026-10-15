from copy import deepcopy
import unittest
from unittest.mock import Mock

import tests.test_runs as run_fixtures
from tests.helpers import ConfigTestCase
from utils.analysis import MethodLibrary, render_conclusion, validate_conclusion

dag = run_fixtures.dag


def package(next_plan=None):
    return {"answer_sufficiency": "INSUFFICIENT", "premise": "UNKNOWN", "claims": [],
            "hypotheses": [], "gaps": ["Need comparable coverage"], "next_plan": next_plan}


class AnalysisTests(ConfigTestCase):
    def test_method_lifecycle_and_holdout_prerequisites(self):
        method = {"id": "decomposition", "title": "Ratio decomposition",
                  "description": "Compare ratio numerator and denominator changes across groups",
                  "preconditions": {"has_components": True}, "required_capabilities": ["database.query"],
                  "template": dag(), "version": 1, "status": "draft", "old_conclusion": "old fact"}
        self.config.save_methods({"methods": [method]})
        with self.assertRaises(ValueError):
            self.config.save_methods({"methods": [{**method, "status": "published"}]})
        method.update(status="validated", validation={"reviewer": "demo-review", "fixture_ids": ["ratio-1"], "passed": True})
        self.config.save_methods({"methods": [method]})
        method["status"] = "published"
        self.config.save_methods({"methods": [method]})
        library = MethodLibrary(self.config.load_methods())
        self.assertEqual(library.retrieve("ratio", ["database.query"], {}), [])
        self.assertEqual(library.retrieve("ratio", [], {"has_components": True}), [])
        selected = library.retrieve("ratio changes in a new domain", ["database.query"], {"has_components": True})
        self.assertEqual(selected[0]["id"], "decomposition")
        self.assertNotIn("old_conclusion", selected[0])

    def test_facts_must_match_values_types_and_references(self):
        results = {1: {"data": {"columns": ["total"], "rows": [["101.25"]]}}}
        good = package()
        good["claims"] = [{"text": "Observed total", "evidence": [1], "facts": [
            {"step_id": 1, "column": "total", "row": 0, "value": "101.25"}]}]
        self.assertEqual(validate_conclusion(good, results), good)
        for value in ("101.26", 101.25):
            bad = deepcopy(good)
            bad["claims"][0]["facts"][0]["value"] = value
            with self.assertRaisesRegex(ValueError, "bound result value"):
                validate_conclusion(bad, results)
        bad = deepcopy(good)
        bad["claims"][0]["text"] = "Sales rose 500 percent"
        with self.assertRaisesRegex(ValueError, "unbound number"):
            validate_conclusion(bad, results)

    def test_false_premise_stops_attribution_and_fast_cannot_add_claims(self):
        bad = package(dag())
        bad["premise"] = "REFUTED"
        with self.assertRaises(ValueError):
            validate_conclusion(bad, {})
        call = Mock(return_value='{"claim_order":[0,1],"style":"bullets"}')
        with self.assertRaises(ValueError):
            render_conclusion(package(), call)
        call.return_value = '{"claim_order":[],"style":"bullets"}'
        report = render_conclusion(package(), call)
        self.assertIn("INSUFFICIENT", report)
        self.assertEqual(call.call_args.args[0], "fast")


class AnalysisRunTests(unittest.TestCase):
    setUp = run_fixtures.RunTests.setUp
    submit = run_fixtures.RunTests.submit
    def analysis_run(self):
        run_id = self.submit()
        self.store.update(run_id, lambda s: s.update(analysis_mode=True, ledger={
            "round": 0, "replans": 0, "stagnation": 0, "evidence_fingerprints": [],
            "progress": [], "unknown": [], "hypotheses": [],
        }))
        self.bi.present.return_value = "Limited conclusion"
        return run_id

    def test_stagnation_threshold_and_replay_no_external_calls(self):
        self.bi.assess.side_effect = lambda *args: package(dag())
        run_id = self.analysis_run()
        self.service.execute(run_id)
        state = self.store.get(run_id)
        self.assertEqual(state["status"], "SUCCEEDED")
        self.assertEqual(state["answer_sufficiency"], "INSUFFICIENT")
        self.assertEqual(state["ledger"]["stagnation"], 2)
        self.assertEqual(self.bi.execute_step.call_count, 3)
        calls = self.bi.mock_calls[:]
        self.store.events(run_id)
        self.store.get(run_id)
        self.assertEqual(self.bi.mock_calls, calls)

    def test_plan_change_invalidates_changed_step_and_descendants_only(self):
        run_id = self.submit()
        self.service.execute(run_id)
        old = self.store.get(run_id)
        changed = deepcopy(old["plan"])
        changed["steps"][0]["description"] = "Different query"
        self.store.update(run_id, lambda s: s.update(status="RUNNING"))
        self.service._replace_plan(run_id, changed, {"unknown": ["different input"]})
        state = self.store.get(run_id)
        self.assertEqual(state["steps"]["1"]["validity"], "STALE")
        self.assertEqual(state["steps"]["3"]["validity"], "STALE")
        self.assertEqual(state["steps"]["2"]["status"], "SUCCEEDED")

    def test_transient_error_has_exact_retry_limit(self):
        self.bi.execute_step.side_effect = TimeoutError("temporary")
        run_id = self.submit({"steps": [{"step_id": 1, "step_type": "sql_query"}]})
        self.service.execute(run_id)
        self.assertEqual(self.bi.execute_step.call_count, 3)
        self.assertEqual(self.store.get(run_id)["steps"]["1"]["attempt_count"], 3)

    def test_replan_limit_stops_even_with_new_evidence_each_round(self):
        def assess(*args):
            plan = dag()
            plan["steps"][0]["description"] = f"new requirement {self.bi.assess.call_count}"
            return package(plan)
        self.bi.assess.side_effect = assess
        self.bi.execute_step.side_effect = lambda *args: {
            "status": "success", "data": self.bi.execute_step.call_count}
        run_id = self.analysis_run()
        self.service.execute(run_id)
        state = self.store.get(run_id)
        self.assertEqual(state["ledger"]["replans"], 2)
        self.assertEqual(state["ledger"]["stagnation"], 0)
        self.assertEqual(self.bi.assess.call_count, 3)
