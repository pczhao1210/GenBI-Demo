import sys
import json
import socket
import subprocess
import tempfile
import time
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import requests

from tests.helpers import ConfigTestCase
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

    def test_null_and_zero_denominators_preserve_meaning(self):
        with self.assertRaisesRegex(ValueError, "NULL"):
            compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d"},
                    {1: table(["n", "d"], [[None, 1]])})
        result = compute({"operation": "ratio", "inputs": [1], "numerator": "n", "denominator": "d"},
                         {1: table(["n", "d"], [[1, 0]])})
        self.assertIsNone(result["data"]["rows"][0][0])
        self.assertEqual(result["data"]["diagnostics"]["zero_denominators"], 1)

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
        with self.assertRaises(RuntimeError):
            client.call("fail", {})


class CrossSourceRunTests(ConfigTestCase):
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
