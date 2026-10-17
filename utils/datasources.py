import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from utils.run_store import utcnow
from utils.sql_utils import validate_readonly_sql

ENGINES = ("mysql", "athena", "postgresql", "mssql")


def normalize_engine(engine):
    engine = {"pgsql": "postgresql", "postgres": "postgresql", "sqlserver": "mssql"}.get(engine, engine)
    if engine not in ENGINES:
        raise ValueError(f"Unsupported database engine: {engine}")
    return engine


def resolve_source(sources, identifier):
    if identifier in sources:
        return sources[identifier]
    engine = normalize_engine(identifier)
    matches = [source for source in sources.values() if source["engine"] == engine]
    if len(matches) != 1:
        raise ValueError(f"Select an explicit datasource_id for {engine}: found {len(matches)} connections")
    return matches[0]


def validate_source(source):
    source = dict(source)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", source.get("datasource_id", "")):
        raise ValueError("datasource_id must contain 1-80 letters, digits, underscores or hyphens")
    source["engine"] = normalize_engine(source["engine"])
    if not source.get("name") or not isinstance(source.get("config"), dict):
        raise ValueError("Datasource name and connection object are required")
    source.setdefault("schema", {})
    source.setdefault("timezone", "UTC")
    try:
        ZoneInfo(source["timezone"])
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise ValueError("Invalid datasource timezone") from exc
    hour = source.setdefault("business_day_start", 0)
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("Business day start must be an hour from 0 to 23")
    return source


def serialize_cell(value):
    if isinstance(value, (Decimal, UUID, timedelta)):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [serialize_cell(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_cell(item) for key, item in value.items()}
    return value


class DatabaseAdapter:
    def __init__(self, source, mcp=None):
        self.source = source
        self.engine = normalize_engine(source["engine"])
        self.config = source["config"]
        self.mcp = mcp

    def capabilities(self):
        return {"engine": self.engine, "dialect": {"athena": "presto", "postgresql": "postgres",
                                                  "mssql": "tsql"}.get(self.engine, self.engine),
                "cancel": False, "timeout": True, "metadata": True, "streaming": False,
                "paging": "TOP/OFFSET" if self.engine == "mssql" else "LIMIT/OFFSET"}

    def diagnostics(self):
        if self.engine == "mssql":
            try:
                import pyodbc
            except ImportError as exc:
                raise RuntimeError(f"Cannot load pyodbc / system unixODBC library: {exc}. "
                                   "Install locked Python dependencies and host unixODBC.") from exc
            drivers = pyodbc.drivers()
            driver = self.config.get("driver", "ODBC Driver 18 for SQL Server")
            if driver not in drivers:
                raise RuntimeError(f"System ODBC driver not installed: {driver}. Available: {drivers}")
        elif self.engine == "postgresql":
            try:
                import psycopg  # noqa: F401
            except ImportError as exc:
                raise RuntimeError("Missing psycopg 3; install the locked Python dependencies") from exc
        return self.capabilities()

    def _engine(self):
        self.diagnostics()
        required = ("host", "username", "database")
        if any(not self.config.get(key) for key in required):
            raise ValueError(f"Connection requires {', '.join(required)}")
        query = {}
        if self.engine == "mssql":
            query = {"driver": self.config.get("driver", "ODBC Driver 18 for SQL Server"),
                     "Encrypt": self.config.get("encrypt", "yes"),
                     "TrustServerCertificate": self.config.get("trust_server_certificate", "no")}
        url = URL.create(
            "postgresql+psycopg" if self.engine == "postgresql" else "mssql+pyodbc",
            username=self.config["username"], password=self.config.get("password", ""),
            host=self.config["host"], port=int(self.config.get("port", 5432 if self.engine == "postgresql" else 1433)),
            database=self.config["database"], query=query,
        )
        args = ({"connect_timeout": int(self.config.get("connection_timeout", 10))}
                if self.engine == "postgresql" else {"timeout": int(self.config.get("connection_timeout", 10))})
        return create_engine(url, connect_args=args, pool_pre_ping=True)

    def _legacy(self, method, params=None):
        from utils.bi_service import result_payload
        if self.mcp is None:
            from utils.mcp_client import MCPClient
            self.mcp = MCPClient()
        return result_payload(self.mcp.call_mcp_server_with_config(
            self.engine, method, self.config, params or {}))

    def metadata(self, table=None):
        if self.engine in ("mysql", "athena"):
            return self._legacy("describe_table" if table else "get_tables",
                                {"table_name": table, "database": self.config.get("database")})
        engine = self._engine()
        try:
            inspector = inspect(engine)
            schema = self.config.get("schema") or ("public" if self.engine == "postgresql" else "dbo")
            if table:
                columns = inspector.get_columns(table, schema=schema)
                primary = inspector.get_pk_constraint(table, schema=schema).get("constrained_columns", [])
                return {"columns": [{"name": c["name"], "type": str(c["type"]), "null": c["nullable"],
                                     "key": "PRI" if c["name"] in primary else "",
                                     "comment": c.get("comment") or ""} for c in columns],
                        "foreign_keys": inspector.get_foreign_keys(table, schema=schema)}
            return {"schemas": inspector.get_schema_names(), "tables": [
                {"name": name, "schema": schema, "type": kind}
                for kind, names in (("table", inspector.get_table_names(schema=schema)),
                                    ("view", inspector.get_view_names(schema=schema))) for name in names]}
        except SQLAlchemyError as exc:
            raise RuntimeError(f"{self.engine} metadata failed: {exc}") from exc
        finally:
            engine.dispose()

    def query(self, sql):
        sql = validate_readonly_sql(sql, self.engine)
        collected = utcnow()
        if self.engine in ("mysql", "athena"):
            result = self._legacy("execute_query", {"sql": sql, "database": self.config.get("database")})
        else:
            engine = self._engine()
            try:
                with engine.connect() as connection:
                    timeout = int(self.config.get("query_timeout", 30))
                    if self.engine == "postgresql":
                        connection.execute(text("SET TRANSACTION READ ONLY"))
                        connection.execute(text("SELECT set_config('statement_timeout', :ms, true)"),
                                           {"ms": str(timeout * 1000)})
                    else:
                        connection.connection.driver_connection.timeout = timeout
                    cursor = connection.execute(text(sql))
                    columns = list(cursor.keys())
                    logical_types = [str(d[1]) for d in cursor.cursor.description]
                    limit = int(self.config.get("max_rows", 1000))
                    if not 1 <= limit <= 10000:
                        raise ValueError("max_rows must be between 1 and 10000")
                    rows = cursor.fetchmany(limit + 1)
                    result = {"success": True, "data": {
                        "columns": columns, "rows": [[serialize_cell(v) for v in row] for row in rows[:limit]],
                        "logical_types": logical_types,
                        "row_count": min(len(rows), limit), "truncated": len(rows) > limit,
                    }}
            except SQLAlchemyError as exc:
                raise RuntimeError(f"{self.engine} query failed: {exc}") from exc
            finally:
                engine.dispose()
        data = result.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Query response is missing data")
        data.update(datasource_id=self.source["datasource_id"], collected_at=collected,
                    timezone=self.source.get("timezone", "UTC"), units={},
                    completeness="TRUNCATED" if data.get("truncated") else "COMPLETE",
                    warnings=[result["warning"]] if result.get("warning") else [])
        data.setdefault("logical_types", ["unknown"] * len(data.get("columns", [])))
        return result

    def preview(self, table, limit=20):
        import sqlglot
        schema = self.config.get("schema")
        expression = sqlglot.select("*").from_(
            sqlglot.exp.Table(this=sqlglot.exp.to_identifier(table, quoted=True),
                             db=sqlglot.exp.to_identifier(schema, quoted=True) if schema else None)
        ).limit(min(max(int(limit), 1), 100))
        return self.query(expression.sql(dialect=self.capabilities()["dialect"]))
