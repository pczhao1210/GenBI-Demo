import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from tests.helpers import ConfigTestCase, query_response
from utils.config_manager import ConfigManager, PROJECT_ROOT
from utils.mcp_client import MCPClient, normalize_response
from utils.mcp_tool_handler import MCPToolCallHandler
from utils.sql_utils import clean_sql_response, validate_readonly_sql


class ConfigurationTests(ConfigTestCase):
    def test_default_path_is_independent_of_cwd(self):
        original = os.getcwd()
        self.addCleanup(os.chdir, original)
        os.chdir(PROJECT_ROOT / "backend")
        self.assertEqual(ConfigManager().config_dir, PROJECT_ROOT / "config")

    def test_failed_write_preserves_existing_file(self):
        previous = self.config.load_llm_config()
        with patch("utils.config_manager.json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.config.save_llm_config({"provider": "broken"})
        self.assertEqual(self.config.load_llm_config(), previous)
        self.assertEqual(list(self.config.config_dir.glob("*.tmp")), [])

    def test_concurrent_read_modify_writes_preserve_all_keys(self):
        def write(index):
            ConfigManager(self.config.config_dir).save_database_config(str(index), {"value": index})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(16)))
        saved = self.config.load_database_config()
        for index in range(16):
            self.assertEqual(saved[str(index)]["value"], index)

    def test_empty_mcp_configuration_is_not_resurrected(self):
        self.config._save_config("example_mcp_config.json", {"mcp_servers": {"mysql": {}}})
        self.config.save_mcp_config({})
        self.assertEqual(self.config.load_mcp_config(), {})

    def test_corrupt_configuration_is_not_silently_reset(self):
        (self.config.config_dir / "llm_config.json").write_text("{")
        with self.assertRaises(ValueError):
            self.config.load_llm_config()


class SQLTests(ConfigTestCase):
    def test_readonly_queries_and_keyword_identifiers(self):
        for sql in (
            "SELECT created_at, updated_at FROM orders",
            "SELECT 'DELETE' AS operation",
            "/* read only */ WITH t AS (SELECT 1 AS n) SELECT n FROM t",
            "SELECT 1 UNION ALL SELECT 2",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(validate_readonly_sql(sql), sql)

    def test_reject_non_queries_and_multiple_statements(self):
        for sql in ("DELETE FROM orders", "SELECT 1; SELECT 2", "SELECT * FROM orders FOR UPDATE",
                    "DROP TABLE orders", "not SQL", "", "SELECT 1 INTO OUTFILE '/tmp/out'"):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_readonly_sql(sql)

    def test_cleaning_preserves_order_by_and_fenced_cte(self):
        sql = "WITH t AS (SELECT 1 AS n) SELECT n FROM t ORDER BY n"
        self.assertEqual(clean_sql_response(f"Here is SQL:\n```SQL\n{sql}\n```"), sql)


class MCPTests(ConfigTestCase):
    def test_nested_failure_is_normalized(self):
        self.assertEqual(normalize_response({"result": {"error": "failed"}}), {"error": "failed"})
        with self.assertRaises(ValueError):
            normalize_response([])

    def test_configured_command_cwd_and_interpreter(self):
        client = MCPClient(self.config)
        with patch("utils.mcp_client.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps(query_response()), "")
            parameters = {"sql": "SELECT 1"}
            result = client.call_mcp_server_with_config("mysql", "execute_query", {}, parameters)
        self.assertNotIn("error", result)
        self.assertEqual(run.call_args.args[0][0], sys.executable)
        self.assertEqual(run.call_args.kwargs["cwd"], PROJECT_ROOT)
        self.assertNotIn("config", parameters)
        self.assertGreater(run.call_args.kwargs["timeout"], 0)

    def test_disabled_server_and_unsupported_transport_are_explicit(self):
        config = self.config.load_mcp_config()
        config["mysql"]["status"] = "inactive"
        config["athena"]["type"] = "sse"
        self.config.save_mcp_config(config)
        with patch("utils.mcp_client.subprocess.run") as run:
            client = MCPClient(self.config)
            self.assertIn("disabled", client.call_mcp_server("mysql", "execute_query")["error"])
            self.assertIn("SSE", client.call_mcp_server("athena", "execute_query")["error"])
            run.assert_not_called()

    def test_transport_timeout(self):
        with patch("utils.mcp_client.subprocess.run", side_effect=subprocess.TimeoutExpired("server", 1)):
            result = MCPClient(self.config).call_mcp_server("mysql", "get_server_info")
        self.assertIn("timed out", result["error"])

    def test_invalid_timeout_does_not_crash_or_launch_a_process(self):
        with patch("utils.mcp_client.subprocess.run") as run:
            result = MCPClient(self.config).call_mcp_server_with_config(
                "mysql", "execute_query", {"query_timeout": "invalid"},
            )
        self.assertIn("query_timeout", result["error"])
        run.assert_not_called()

    def test_handler_uses_schema_validation_and_propagates_nested_errors(self):
        self.mcp.call_mcp_server_with_config.return_value = {"result": {"error": "query failed"}}
        handler = MCPToolCallHandler(self.mcp)
        config = {"host": "localhost", "username": "u", "password": "p", "database": "db"}
        result = handler.execute_tool_call("mysql_query", {"sql": "SELECT 1", "config": config})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "query failed")
        for arguments in ({"query": "test", "max_results": 0},
                          {"query": "test", "max_results": True},
                          {"query": "test", "unknown": "ignored"}):
            self.assertEqual(handler.execute_tool_call("web_search", arguments)["code"], "INVALID_PARAMS")
        self.assertEqual(handler.execute_tool_call("mysql_query", {
            "sql": "SELECT 1", "config": {},
        })["code"], "INVALID_PARAMS")

    def test_handler_matches_declared_output_shape(self):
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        result = MCPToolCallHandler(self.mcp).execute_tool_call(
            "athena_query", {"sql": "SELECT 1", "config": {"region": "us-east-1"}},
        )
        self.assertEqual(result["data"]["rows"], [[1]])

    def test_missing_tables_is_an_error_not_empty_success(self):
        with patch.object(MCPClient, "call_mcp_server_with_config", return_value={"error": "offline"}):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                MCPClient(self.config).get_tables("mysql", {})

    def test_real_stdio_servers_respond_without_database_credentials(self):
        client = MCPClient(self.config)
        for name in ("mysql", "athena", "playwright"):
            with self.subTest(name=name):
                info = client.get_server_info(name)
                self.assertNotIn("error", info, info)
                self.assertEqual(info["name"], name)
