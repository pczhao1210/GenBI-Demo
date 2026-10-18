import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


def clean_sql_response(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM returned no SQL")
    block = re.search(r"```(?:sql)?\s*\n?(.*?)```", text, re.IGNORECASE | re.DOTALL)
    return (block.group(1) if block else text).strip()


def validate_readonly_sql(sql: str, database_type: str = "mysql") -> str:
    dialect = {"mysql": "mysql", "athena": "presto", "postgresql": "postgres", "postgres": "postgres",
               "pgsql": "postgres", "mssql": "tsql"}.get(database_type)
    if dialect is None:
        raise ValueError(f"Unsupported database: {database_type}")
    sql = clean_sql_response(sql)
    try:
        statements = [statement for statement in sqlglot.parse(sql, read=dialect) if statement is not None]
    except SqlglotError as exc:
        raise ValueError("Invalid SQL; return one read-only SELECT query") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError("Only one read-only SELECT query is allowed")
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop,
                 exp.Alter, exp.Merge, exp.Command, exp.Into, exp.Lock)
    if any(isinstance(node, forbidden) for node in statements[0].walk()):
        raise ValueError("SQL contains a non-read-only operation")
    return sql


def validate_profile_sql(sql, source):
    """Resolve CTE scopes before checking physical table identities."""
    from sqlglot.optimizer.scope import traverse_scope

    dialect = {"mysql": "mysql", "athena": "presto", "postgresql": "postgres", "mssql": "tsql"}[source["engine"]]
    sql = validate_readonly_sql(sql, source["engine"])
    expression = sqlglot.parse_one(sql, read=dialect)
    allowed = set(source["schema"].get("tables", {}))
    config = source["config"]
    default_db = (config.get("schema") or ("public" if source["engine"] == "postgresql" else "dbo")
                  if source["engine"] in ("postgresql", "mssql") else config.get("database"))
    default_catalog = config.get("catalog") if source["engine"] == "athena" else config.get("database")
    for scope in traverse_scope(expression):
        for _, table in scope.selected_sources.values():
            if not isinstance(table, exp.Table):
                continue
            if (not isinstance(table.this, exp.Identifier) or table.name not in allowed
                    or table.db and table.db != default_db
                    or table.catalog and table.catalog != default_catalog):
                raise ValueError(f"SQL table is outside the Profile: {table.sql(dialect=dialect)}")
    return sql
