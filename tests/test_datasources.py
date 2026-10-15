from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from tests.helpers import ConfigTestCase, query_response
from utils.bi_service import BIService
from utils.datasources import DatabaseAdapter, normalize_engine
from utils.sql_utils import validate_readonly_sql


class DatasourceTests(ConfigTestCase):
    def test_repeatable_migration_preserves_explicit_source_and_schema(self):
        first = self.config.load_datasources()
        self.assertEqual(first, self.config.load_datasources())
        self.assertEqual(first["legacy-mysql"]["schema"]["tables"]["mysql_orders"][0]["name"], "updated_at")
        source = first["legacy-mysql"]
        self.config.save_datasource({**source, "name": "Renamed"})
        self.assertEqual(self.config.resolve_datasource("legacy-mysql")["name"], "Renamed")
        self.assertIn("mysql_orders", self.config.resolve_datasource("legacy-mysql")["schema"]["tables"])

    def test_two_connections_require_id_and_keep_schema_separate(self):
        source = self.config.resolve_datasource("mysql")
        self.config.save_datasource({**source, "datasource_id": "second", "schema": {
            "tables": {"other": []}}, "config": {"database": "second_db"}})
        with self.assertRaisesRegex(ValueError, "explicit datasource_id"):
            self.config.resolve_datasource("mysql")
        with self.assertRaises(ValueError):
            self.config.save_database_config("mysql", {"database": "must-not-write"})
        self.assertEqual(self.config.resolve_datasource("legacy-mysql")["config"]["database"], "mysql_test")
        service = BIService(self.config, self.mcp, self.llm)
        self.llm.generate_sql.return_value = "SELECT 1"
        self.mcp.call_mcp_server_with_config.return_value = query_response()
        service.query("rows", "second")
        self.assertEqual(self.mcp.call_mcp_server_with_config.call_args.args[2]["database"], "second_db")
        self.assertNotIn("mysql_orders", service.sql_prompt("rows", "second"))

    def test_dialects_accept_native_cte_dates_and_paging(self):
        for engine, sql in (
            ("postgresql", "WITH x AS (SELECT CURRENT_DATE AS d) SELECT d FROM x LIMIT 5"),
            ("mssql", "WITH x AS (SELECT GETDATE() AS d) SELECT TOP (5) d FROM x"),
        ):
            self.assertEqual(validate_readonly_sql(sql, engine), sql)
        self.assertEqual(normalize_engine("pgsql"), "postgresql")

    def test_new_adapter_preserves_decimal_date_null_and_truncation(self):
        source = {"datasource_id": "pg", "engine": "postgresql", "config": {"max_rows": 1}, "timezone": "UTC"}
        adapter = DatabaseAdapter(source)
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        cursor = connection.execute.return_value
        cursor.keys.return_value = ["amount", "day", "missing"]
        cursor.cursor.description = [("amount", Decimal), ("day", date), ("missing", str)]
        cursor.fetchmany.return_value = [
            (Decimal("123456789.123456789"), date(2026, 10, 15), None), (Decimal("2"), None, None)]
        with patch.object(adapter, "_engine", return_value=engine):
            result = adapter.query("SELECT amount, day, missing FROM t")["data"]
        self.assertEqual(result["rows"], [["123456789.123456789", "2026-10-15", None]])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["completeness"], "TRUNCATED")
        self.assertEqual(result["datasource_id"], "pg")
        engine.dispose.assert_called_once()

    def test_odbc_driver_missing_is_distinct_and_not_a_success(self):
        adapter = DatabaseAdapter({"datasource_id": "ms", "engine": "mssql", "config": {}})
        module = MagicMock()
        module.drivers.return_value = []
        with patch.dict("sys.modules", {"pyodbc": module}):
            with self.assertRaisesRegex(RuntimeError, "System ODBC driver not installed"):
                adapter.diagnostics()

    def test_preview_uses_target_dialect_and_quotes_identifier(self):
        adapter = DatabaseAdapter({"datasource_id": "ms", "engine": "mssql", "config": {"schema": "dbo"}})
        with patch.object(adapter, "query") as query:
            adapter.preview("order details")
        self.assertIn("TOP 20", query.call_args.args[0])
        self.assertIn("[order details]", query.call_args.args[0])
