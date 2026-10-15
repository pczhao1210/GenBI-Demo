import json
import unittest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from mcp_servers.athena_server import AthenaServer
from mcp_servers.mysql_server import MySQLServerOptimized, serialize_value


class MySQLTests(unittest.TestCase):
    def setUp(self):
        self.server = MySQLServerOptimized()
        self.server.pool = Mock()
        self.cursor = Mock()
        connection = self.server.pool.get_connection.return_value
        context = Mock()
        context.__enter__ = Mock(return_value=self.cursor)
        context.__exit__ = Mock(return_value=False)
        connection.cursor.return_value = context
        self.cursor.description = [("n",)]
        self.cursor.fetchmany.return_value = [(1,)]

    def test_cte_and_leading_comment_return_rows(self):
        for sql in ("WITH t AS (SELECT 1 AS n) SELECT n FROM t", "/* comment */ SELECT 1"):
            with self.subTest(sql=sql):
                result = self.server.execute_query(sql)
                self.assertTrue(result["success"])
                self.assertEqual(result["data"]["rows"], [[1]])

    def test_row_limit_is_bounded_and_truncation_is_honest(self):
        self.server.config = {"max_rows": 2}
        self.cursor.fetchmany.return_value = [(1,), (2,), (3,)]
        result = self.server.execute_query("SELECT n FROM orders")
        self.cursor.fetchmany.assert_called_once_with(3)
        self.assertIn("LIMIT 3", self.cursor.execute.call_args.args[0])
        self.assertEqual(result["data"]["rows"], [[1], [2]])
        self.assertTrue(result["data"]["truncated"])
        self.assertIsNone(result["data"]["total_rows"])

    def test_non_readonly_statement_never_executes(self):
        self.assertIn("error", self.server.execute_query("DELETE FROM orders"))
        self.cursor.execute.assert_not_called()

    def test_decimal_and_time_are_serializable_without_float_rounding(self):
        value = Decimal("123456789012345678.1234")
        self.cursor.fetchmany.return_value = [(value,)]
        self.assertEqual(self.server.execute_query("SELECT amount FROM orders")["data"]["rows"], [[str(value)]])
        self.assertIn(str(value), json.dumps({"value": value, "time": timedelta(seconds=1)}, default=serialize_value))

    def test_stats_failure_is_not_zero_success(self):
        with patch.object(self.server, "execute_query_internal", return_value={"error": "offline"}):
            self.assertEqual(self.server.get_database_stats(), {"error": "offline"})


def athena_page(values, token=None, header=False):
    rows = ([{"Data": [{"VarCharValue": "n"}]}] if header else []) + [
        {"Data": [{} if value is None else {"VarCharValue": str(value)}]} for value in values
    ]
    result = {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": [{"Label": "n"}]}, "Rows": rows}}
    if token:
        result["NextToken"] = token
    return result


class AthenaTests(unittest.TestCase):
    def setUp(self):
        self.server = AthenaServer()
        self.client = self.server.client = Mock()
        self.client.start_query_execution.return_value = {"QueryExecutionId": "offline"}
        self.client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def test_pagination_preserves_second_page_first_row_and_null(self):
        self.server.config = {"max_rows": 2000, "workgroup": "analytics", "database": "warehouse"}
        self.client.get_query_results.side_effect = [
            athena_page([1], token="page-two", header=True), athena_page([2, None]),
        ]
        result = self.server.execute_query("SELECT n FROM orders")
        self.assertEqual(result["data"]["rows"], [["1"], ["2"], [None]])
        self.assertEqual(self.client.get_query_results.call_count, 2)
        self.assertEqual(self.client.get_query_results.call_args.kwargs["NextToken"], "page-two")
        request = self.client.start_query_execution.call_args.kwargs
        self.assertEqual(request["WorkGroup"], "analytics")
        self.assertEqual(request["QueryExecutionContext"]["Database"], "warehouse")

    def test_truncation_after_page_boundary(self):
        self.server.config = {"max_rows": 1}
        self.client.get_query_results.side_effect = [
            athena_page([1], token="page-two", header=True), athena_page([2]),
        ]
        result = self.server.execute_query("SELECT n FROM orders")
        self.assertEqual(result["data"]["rows"], [["1"]])
        self.assertTrue(result["data"]["truncated"])
        self.assertIn("warning", result)

    def test_timeout_cancels_running_query(self):
        self.server.config = {"query_timeout": 1}
        self.client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "RUNNING"}}}
        with patch("mcp_servers.athena_server.time.monotonic", side_effect=[0, 2]):
            result = self.server.execute_query("SELECT n FROM orders")
        self.assertIn("cancelled", result["error"])
        self.client.stop_query_execution.assert_called_once_with(QueryExecutionId="offline")

    def test_failure_does_not_fetch_results(self):
        self.client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": "bad query"}},
        }
        self.assertIn("bad query", self.server.execute_query("SELECT 1")["error"])
        self.client.get_query_results.assert_not_called()

    def test_tables_use_metadata_pagination_not_hardcoded_fallback_queries(self):
        self.client.get_paginator.return_value.paginate.return_value = [
            {"TableMetadataList": [{"Name": "one"}]}, {"TableMetadataList": [{"Name": "two"}]},
        ]
        self.assertEqual(self.server.get_tables("warehouse")["tables"], ["one", "two"])
        self.client.start_query_execution.assert_not_called()

    def test_schema_includes_partition_columns(self):
        self.client.get_table_metadata.return_value = {"TableMetadata": {
            "Columns": [{"Name": "n", "Type": "int"}],
            "PartitionKeys": [{"Name": "day", "Type": "date"}],
        }}
        self.assertEqual([column["name"] for column in self.server.describe_table("orders")["columns"]], ["n", "day"])
