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
    dialect = {"mysql": "mysql", "athena": "presto"}.get(database_type)
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
