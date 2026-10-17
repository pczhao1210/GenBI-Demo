import sys
import json
import socket
import subprocess
import tempfile
import time
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

import requests

from tests.helpers import ConfigTestCase
from utils.analysis import render_conclusion, validate_conclusion
from utils.computation import compute
from utils.config_manager import PROJECT_ROOT
from utils.external_evidence import align_facts, extract_evidence, extract_structured
from utils.standard_mcp import StandardMCPClient
from utils.bi_service import BIService
from utils.run_service import RunService
from utils.run_store import RunStore


def table(columns, rows, source="pg", **extra):
    return {"status": "success", "data": {
        "columns": columns, "rows": rows, "truncated": False, "completeness": "COMPLETE",
        "entity": "shop", "grain": ["day", "shop"], "timezone": "UTC",
        "time_range": {"start": "2026-10-01T00:00:00+00:00", "end": "2026-10-02T00:00:00+00:00"},
        "units": {}, "datasource_id": source, "collected_at": "2026-10-03T00:00:00Z", **extra,
    }}


class ComputationTests(unittest.TestCase):
    def test_empty_inputs_do_not_create_zero_measurements(self):
        result = compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d"},
                         {1: table(["n", "d"], [])})
        self.assertEqual(result["data"]["rows"], [])

    def test_ratio_recomputes_components_instead_of_averaging_ratios(self):
        result = compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d",
                          "output": "rate"}, {1: table(["n", "d"], [["1", "2"], ["9", "90"]])})
        self.assertEqual(result["data"]["rows"][0][1:], [["10", "92"]][0])
        self.assertTrue(result["data"]["rows"][0][0].startswith("0.108695652173913"))
        self.assertNotEqual(result["data"]["rows"][0][0], "0.3")

    def test_cross_type_join_checks_cardinality_unmatched_and_totals(self):
        inputs = {
            1: table(["shop", "revenue"], [["a", "10.25"], ["b", "20.75"]], units={"revenue": "CNY"}),
            2: table(["code", "visits"], [["a", 2], ["b", 4]], source="mssql", units={"visits": "count"}),
        }
        requirements = {"operation": "join", "inputs": [1, 2], "left_on": ["shop"], "right_on": ["code"],
                        "cardinality": "one_to_one"}
        result = compute(requirements, inputs)["data"]
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["diagnostics"]["unmatched_left_ratio"], 0)
        self.assertEqual(result["diagnostics"]["source_totals"][0]["revenue"], "31.00")
        self.assertEqual(result["diagnostics"]["output_totals"]["revenue"], "31.00")
        inputs[2]["data"]["rows"].append(["a", 9])
        with self.assertRaisesRegex(ValueError, "cardinality"):
            compute(requirements, inputs)

    def test_truncation_alignment_and_unmatched_rejected(self):
        requirements = {"operation": "join", "inputs": [1, 2], "left_on": ["id"], "right_on": ["id"],
                        "cardinality": "one_to_one"}
        base = {1: table(["id"], [["a"]]), 2: table(["id"], [["a"]])}
        for key, value in (("truncated", True), ("timezone", "Asia/Shanghai"), ("rows", [["b"]])):
            inputs = deepcopy(base)
            inputs[2]["data"][key] = value
            with self.assertRaises(ValueError):
                compute(requirements, inputs)

    def test_repeated_measures_cannot_silently_double_count(self):
        joined = compute({"operation": "join", "inputs": [1, 2], "left_on": ["id"], "right_on": ["id"],
                          "cardinality": "one_to_many"}, {
                              1: table(["id", "amount"], [["a", "10"]], units={"amount": "CNY"}),
                              2: table(["id", "event"], [["a", "x"], ["a", "y"]]),
                          })
        with self.assertRaisesRegex(ValueError, "duplicated"):
            compute({"operation": "aggregate", "inputs": [3], "columns": ["amount"]}, {3: joined})

    def test_chained_join_preserves_repeated_measures_on_both_sides_and_after_renaming(self):
        first = compute({"operation": "join", "inputs": [1, 2], "left_on": ["shop"], "right_on": ["shop"],
                         "cardinality": "one_to_many"}, {
                             1: table(["shop", "amount"], [["a", "10"]], source="shops", units={"amount": "CNY"}),
                             2: table(["shop", "event"], [["a", "e1"], ["a", "e2"]], source="events"),
                         })
        details = table(["event", "amount"], [["e1", "1"], ["e2", "2"]],
                        source="details", units={"amount": "CNY"})
        for reversed_inputs in (False, True):
            with self.subTest(reversed_inputs=reversed_inputs):
                second = compute({"operation": "join", "inputs": [3, 4], "left_on": ["event"],
                                  "right_on": ["event"], "cardinality": "one_to_one"},
                                 {3: details if reversed_inputs else first,
                                  4: first if reversed_inputs else details})
                duplicated = "amount_right" if reversed_inputs else "amount_left"
                clean = "amount_left" if reversed_inputs else "amount_right"
                self.assertIn(duplicated, second["data"]["repeated_measures"])
                self.assertEqual(set(second["data"]["sources"]), {"shops", "events", "details"})
                with self.assertRaisesRegex(ValueError, "duplicated"):
                    compute({"operation": "aggregate", "inputs": [5], "columns": [duplicated]}, {5: second})
                valid = compute({"operation": "aggregate", "inputs": [5], "columns": [clean]}, {5: second})
                self.assertEqual(valid["data"]["rows"], [["3"]])

    def test_big_integers_survive_nulls_outer_joins_and_aggregation(self):
        value = 9007199254740993
        joined = compute({"operation": "join", "inputs": [1, 2], "left_on": ["id"], "right_on": ["id"],
                          "cardinality": "one_to_one", "how": "outer", "max_unmatched_ratio": 1}, {
                              1: table(["id", "amount"], [["a", value]], units={"amount": "count"}),
                              2: table(["id"], [["b"]]),
                          })
        for source in (table(["amount"], [[value], [None]]), joined):
            with self.subTest(source=source):
                result = compute({"operation": "aggregate", "inputs": [1], "columns": ["amount"],
                                  "null_policy": "exclude"}, {1: source})
                self.assertEqual(result["data"]["rows"], [[str(value)]])
                self.assertEqual(result["data"]["diagnostics"]["excluded_null_rows"], 1)
        self.assertEqual(joined["data"]["diagnostics"]["output_totals"]["amount"], str(value))

    def test_null_and_zero_denominators_preserve_meaning(self):
        with self.assertRaisesRegex(ValueError, "NULL"):
            compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d"},
                    {1: table(["n", "d"], [[None, 1]])})
        result = compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d"},
                         {1: table(["n", "d"], [[1, 0]])})
        self.assertIsNone(result["data"]["rows"][0][0])
        self.assertEqual(result["data"]["diagnostics"]["zero_denominators"], 1)

    def test_computed_units_follow_output_columns_and_support_chained_calculation(self):
        inputs = {1: table(["n", "d", "unused"], [[10, 3, 1]],
                           units={"n": "CNY", "d": "CNY", "unused": "count"})}
        ratio = compute({"operation": "ratio", "inputs": [1], "numerator": "n",
                         "denominator": "d", "output": "rate"}, inputs)
        self.assertEqual(ratio["data"]["units"], {
            "rate": "ratio", "rate_numerator": "CNY", "rate_denominator": "CNY"})
        difference = compute({"operation": "difference", "inputs": [2], "numerator": "rate_numerator",
                              "denominator": "rate_denominator", "output": "net"}, {2: ratio})
        self.assertEqual(difference["data"]["units"], {"net": "CNY"})
        self.assertEqual(difference["data"]["rows"], [["7"]])
        summed = compute({"operation": "aggregate", "inputs": [3], "columns": ["net"]}, {3: difference})
        self.assertEqual(summed["data"]["units"], {"net": "CNY"})
        inputs[1]["data"]["units"]["d"] = "count"
        rate = compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d"}, inputs)
        self.assertEqual(rate["data"]["units"]["ratio"], "(CNY)/(count)")
        inputs[1]["data"]["units"].pop("d")
        unknown = compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d"}, inputs)
        self.assertNotIn("ratio", unknown["data"]["units"])
        self.assertTrue(any("unit is unknown" in warning for warning in unknown["data"]["diagnostics"]["warnings"]))

    def test_join_budget_is_checked_before_expansion(self):
        inputs = {1: table(["id"], [[i] for i in range(6000)]),
                  2: table(["id"], [[i] for i in range(6000, 12000)])}
        with self.assertRaisesRegex(ValueError, "row budget"):
            compute({"operation": "join", "inputs": [1, 2], "left_on": ["id"], "right_on": ["id"],
                     "cardinality": "one_to_one", "how": "outer", "max_unmatched_ratio": 1}, inputs)

    def test_memory_budget_is_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, "memory budget"):
            compute({"operation": "aggregate", "inputs": [1], "columns": ["n"]},
                    {1: table(["n", "large"], [[1, "x" * (16 * 1024 * 1024)]])})


class ExternalTests(unittest.TestCase):
    def test_structured_api_uses_json_pointer_not_invented_positions(self):
        import json
        payload = {"records": [{"metric": "price", "city": "Shanghai", "unit": "CNY",
                                "amount": "12.5", "time": "2026-10-01T12:00:00+00:00"}]}
        document = {"url": "https://example.invalid/api", "text": json.dumps(payload),
                    "complete": True, "collected_at": "2026-10-03T00:00:00Z", "published_at": None}
        need = {"variable": "price", "region": "Shanghai", "unit": "CNY",
                "start": "2026-10-01T00:00:00+00:00", "end": "2026-10-02T00:00:00+00:00"}
        mapping = {"records_path": ["records"], "variable": "metric", "region": "city",
                   "value": "amount", "unit": "unit", "observed_at": "time"}
        result = extract_structured(document, need, mapping)
        self.assertEqual(result["facts"][0]["source_position"], "/records/0")
        self.assertEqual(result["facts"][0]["value"], "12.5")
        evidence = {1: {"status": "success", "evidence_class": "observation", "data": result}}
        conclusion = {
            "answer_sufficiency": "QUALIFIED", "premise": "UNKNOWN", "hypotheses": [], "gaps": [],
            "next_plan": None, "claims": [{"text": "Observed price is 12.5", "evidence": [1], "facts": [
                {"step_id": 1, "fact_index": 0, "value": "12.5", "source_url": "invented",
                 "source_position": "/invented"},
            ]}],
        }
        verified = validate_conclusion(conclusion, evidence)
        report = render_conclusion(verified, Mock(return_value='{"claim_order":[0],"style":"bullets"}'))
        self.assertIn("12.5", report)
        self.assertIn("https://example.invalid/api", report)
        self.assertIn("/records/0", report)
        self.assertNotIn("invented", report)
        for change in ({"value": 12.5}, {"value": "999"}, {"fact_index": 1}, {"fact_index": -1},
                       {"fact_index": True}, {"step_id": 2}, {"row": 0, "column": "value"}):
            with self.subTest(change=change):
                bad = deepcopy(conclusion)
                bad["claims"][0]["facts"][0].update(change)
                with self.assertRaises(ValueError):
                    validate_conclusion(bad, evidence)
        with self.assertRaisesRegex(ValueError, "discovery"):
            validate_conclusion(conclusion, {1: {**evidence[1], "evidence_class": "discovery"}})
        escaped = extract_structured(
            {**document, "text": json.dumps({"records/v1~": payload["records"]})},
            need, {**mapping, "records_path": ["records/v1~"]})
        self.assertEqual(escaped["facts"][0]["source_position"], "/records~1v1~0/0")

    def test_evidence_tracks_position_and_excludes_wrong_time_region(self):
        text = "2026-10-01T12:00:00+00:00 Shanghai 12.5 CNY"
        document = {"url": "https://example.invalid/history", "text": text, "complete": True,
                    "collected_at": "2026-10-03T00:00:00Z", "published_at": None}
        need = {"variable": "price", "region": "Shanghai", "unit": "CNY",
                "start": "2026-10-01T00:00:00+00:00", "end": "2026-10-02T00:00:00+00:00"}
        facts = [{"variable": "price", "region": "Shanghai", "unit": "CNY", "value": "12.5",
                  "observed_at": "2026-10-01T12:00:00+00:00", "span": [0, len(text)]}]
        accepted, warnings = align_facts(facts, need, document)
        self.assertEqual(accepted[0]["source_url"], document["url"])
        self.assertEqual(accepted[0]["excerpt"], text)
        self.assertEqual(warnings, [])
        conclusion = {
            "answer_sufficiency": "QUALIFIED", "premise": "UNKNOWN", "hypotheses": [], "gaps": [],
            "next_plan": None, "claims": [{"text": "Observed price is 12.5", "evidence": [1], "facts": [
                {"step_id": 1, "fact_index": 0, "value": "12.5"},
            ]}],
        }
        verified = validate_conclusion(conclusion, {1: {
            "status": "success", "evidence_class": "observation", "data": {"facts": accepted},
        }})
        self.assertEqual(verified["claims"][0]["facts"][0]["source_position"], [0, len(text)])
        accepted, warnings = align_facts(facts, {**need, "region": "Beijing"}, document)
        self.assertEqual(accepted, [])
        self.assertTrue(warnings)
        facts[0]["value"] = "999"
        with self.assertRaises(ValueError):
            align_facts(facts, need, document)

    def test_truncated_documents_are_discovery_not_evidence(self):
        model = Mock()
        result = extract_evidence({"complete": False}, {}, model)
        self.assertEqual(result["facts"], [])
        model.assert_not_called()


class StandardMCPTests(ConfigTestCase):
    def test_run_owned_session_reuses_process_and_isolates_another_run(self):
        from utils.standard_mcp import RunMCPContext
        settings = {"protocol": "mcp", "type": "stdio", "command": sys.executable,
                    "args": [str(PROJECT_ROOT / "tests/fixtures/mcp_server.py")], "timeout": 10}
        first, second = RunMCPContext(), RunMCPContext()
        try:
            a = first.call(settings, "counter", {})["result"]
            b = first.call(settings, "counter", {})["result"]
            c = second.call(settings, "counter", {})["result"]
            self.assertEqual((a["calls"], b["calls"], c["calls"]), (1, 2, 1))
            self.assertEqual(a["pid"], b["pid"])
            self.assertNotEqual(a["pid"], c["pid"])
        finally:
            first.close()
            second.close()
        self.assertFalse(first.thread.is_alive())
        self.assertEqual(first.sessions, {})

    def test_real_streamable_http_protocol(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([sys.executable, str(PROJECT_ROOT / "tests/fixtures/mcp_server.py"), str(port)],
                                       stdout=log, stderr=log)
            try:
                ready = False
                for _ in range(100):
                    if process.poll() is not None:
                        break
                    try:
                        requests.get(f"http://127.0.0.1:{port}/mcp", timeout=0.2)
                        ready = True
                        break
                    except requests.ConnectionError:
                        time.sleep(0.05)
                if not ready:
                    log.seek(0)
                    self.fail("MCP HTTP fixture did not start: " + log.read().decode())
                client = StandardMCPClient({"type": "streamable_http", "url": f"http://127.0.0.1:{port}/mcp"})
                self.assertEqual(client.call("echo", {"value": 42})["result"]["value"], 42)
            finally:
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(5)

    def test_real_stdio_initialize_discover_call_and_error(self):
        client = StandardMCPClient({
            "protocol": "mcp", "type": "stdio", "command": sys.executable,
            "args": [str(PROJECT_ROOT / "tests/fixtures/mcp_server.py")], "timeout": 10,
        })
        info = client.call("get_server_info", {})["result"]
        self.assertEqual(info["name"], "GenBI test fixture")
        self.assertIn("echo", [tool["name"] for tool in info["tools"]])
        self.assertEqual(client.call("echo", {"value": 42})["result"]["value"], 42)
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            client.call("fail", {})

    def test_grouped_errors_keep_the_root_cause_but_redact_reasoning_content(self):
        for stateful in (False, True):
            with self.subTest(stateful=stateful):
                client = StandardMCPClient({"template": "sequential_thinking"} if stateful else {})
                error = ExceptionGroup("transport", [
                    ExceptionGroup("session", [RuntimeError("PRIVATE_SENTINEL refused destination")])])
                with patch.object(client, "request", new=AsyncMock(side_effect=error)):
                    with self.assertRaises(RuntimeError) as caught:
                        client.call("tool", {})
                if stateful:
                    self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))
                else:
                    self.assertIn("PRIVATE_SENTINEL refused destination", str(caught.exception))


class CrossSourceRunTests(ConfigTestCase):
    def test_metrics_on_active_secondary_source_reach_plan_confirmation(self):
        self.config.load_datasources()
        self.config.save_semantics({"metrics": {
            metric: {"description": metric, "formula": "COUNT(*)", "aggregation": "sum",
                     "time_field": "updated_at", "unit": "count", "allowed_dimensions": [],
                     "mappings": {source: {"table": name, "columns": ["updated_at"]}}}
            for metric, source, name in (("sales", "legacy-mysql", "mysql_orders"),
                                         ("traffic", "legacy-athena", "athena_orders"))
        }})
        plan = {"steps": [
            {"step_id": 1, "step_type": "sql_query", "datasource_id": "legacy-mysql"},
            {"step_id": 2, "step_type": "sql_query", "datasource_id": "legacy-athena"},
        ]}
        for intent, active_ids in (("analysis", ["legacy-mysql", "legacy-athena"]),
                                   ("query", ["legacy-mysql", "legacy-athena"]),
                                   ("analysis", ["legacy-mysql"])):
            with self.subTest(intent=intent, active_ids=active_ids):
                self.llm.generate_response.side_effect = [
                    json.dumps({"intent": intent, "followup": False, "clarification": None,
                                "slots": {"metrics": {"value": ["sales", "traffic"], "span": [0, 17]}}}),
                    json.dumps(plan),
                ]
                runs = RunService(RunStore(self.config.config_dir / "understanding.sqlite3"), self.config,
                                  lambda **kw: BIService(kw["config_manager"], self.mcp, self.llm))
                run_id = runs.submit("sales and traffic comparison", database="legacy-mysql",
                                     datasource_ids=active_ids)["run_id"]
                runs.execute(run_id)
                state = runs.store.get(run_id)
                self.assertEqual(state["status"], "WAITING_INPUT", state)
                if len(active_ids) == 2:
                    self.assertEqual(state["request"]["request_kind"], "plan_confirmation")
                    self.assertEqual({step["datasource_id"] for step in state["plan"]["steps"]}, set(active_ids))
                else:
                    self.assertIn("not computable", state["request"]["prompt"])
                self.mcp.call_mcp_server_with_config.assert_not_called()

    def test_full_run_binds_each_engine_and_calculates_known_ratio(self):
        for identifier, engine in (("pg", "postgresql"), ("ms", "mssql")):
            self.config.save_datasource({
                "datasource_id": identifier, "name": identifier, "engine": engine,
                "config": {"database": identifier}, "schema": {"tables": {"metrics": [
                    {"name": "id", "type": "text"}, {"name": "value", "type": "decimal"}]}},
            })
        self.llm.generate_sql.return_value = "SELECT id, value FROM metrics"
        contract = {"entity": "shop", "grain": ["shop"], "time_range": {
            "start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"}, "units": {}}
        plan = {"steps": [
            {"step_id": 1, "step_type": "sql_query", "datasource_id": "pg", "result_contract": contract},
            {"step_id": 2, "step_type": "sql_query", "datasource_id": "ms", "result_contract": contract},
            {"step_id": 3, "step_type": "compute", "dependencies": [1, 2], "compute_requirements": {
                "operation": "join", "inputs": [1, 2], "left_on": ["id"], "right_on": ["id"],
                "cardinality": "one_to_one"}},
            {"step_id": 4, "step_type": "compute", "dependencies": [3], "compute_requirements": {
                "operation": "ratio", "inputs": [3], "numerator": "value_left", "denominator": "value_right"}},
        ]}
        store = RunStore(self.config.config_dir / "runs.sqlite3")
        service = RunService(store, self.config, lambda **kwargs: BIService(kwargs["config_manager"], self.mcp, self.llm))
        calls = []
        def query(adapter, sql):
            calls.append((adapter.source["datasource_id"], adapter.engine))
            rows = [["a", "1"], ["b", "9"]] if adapter.engine == "postgresql" else [["a", "2"], ["b", "90"]]
            return {"data": table(["id", "value"], rows, source=adapter.source["datasource_id"],
                                  warnings=[])["data"]}
        with patch("utils.datasources.DatabaseAdapter.query", query):
            run = service.submit("ratio", database="pg", plan=plan, datasource_ids=["pg", "ms"])
            service.execute(run["run_id"])
        state = store.get(run["run_id"])
        self.assertEqual(state["status"], "SUCCEEDED", state.get("error"))
        self.assertEqual(set(calls), {("pg", "postgresql"), ("ms", "mssql")})
        data = store.artifact(run["run_id"], state["steps"]["4"]["artifact_id"])["data"]
        self.assertEqual(data["rows"][0][1:], ["10", "92"])
        self.assertEqual({call["role"] for call in state["model_calls"]}, {"sql"})
