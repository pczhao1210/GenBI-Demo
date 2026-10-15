#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.sql_utils import validate_readonly_sql


class AthenaServer:
    def __init__(self):
        self.client = None
        self.config = {}

    def initialize(self, config: Dict[str, Any]):
        self.config = config
        options = {"region_name": config.get("region", "us-east-1")}
        for key, legacy in (("aws_access_key_id", "access_key"),
                            ("aws_secret_access_key", "secret_key"),
                            ("aws_session_token", "session_token")):
            value = config.get(key) or config.get(legacy)
            if value:
                options[key] = value
        self.client = boto3.client(
            "athena", **options,
            config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}),
        )

    def execute_query(self, sql: str, database: str = None) -> Dict[str, Any]:
        if self.client is None:
            return {"error": "Athena client is not initialized"}
        try:
            sql = validate_readonly_sql(sql, "athena")
            timeout = float(self.config.get("query_timeout", 240))
            max_rows = int(self.config.get("max_rows", 1000))
            if timeout <= 0 or max_rows <= 0:
                raise ValueError("query_timeout and max_rows must be positive")
            params = {
                "QueryString": sql,
                "QueryExecutionContext": {
                    "Database": database or self.config.get("database", "default"),
                    "Catalog": self.config.get("catalog", "AwsDataCatalog"),
                },
                "WorkGroup": self.config.get("workgroup", "primary"),
            }
            if self.config.get("s3_output_location"):
                params["ResultConfiguration"] = {"OutputLocation": self.config["s3_output_location"]}
            started = time.monotonic()
            query_id = self.client.start_query_execution(**params)["QueryExecutionId"]
            while True:
                status = self.client.get_query_execution(
                    QueryExecutionId=query_id
                )["QueryExecution"]["Status"]
                if status["State"] == "SUCCEEDED":
                    break
                if status["State"] in ("FAILED", "CANCELLED"):
                    return {"error": f"Athena query {status['State']}: "
                                     f"{status.get('StateChangeReason', 'No reason provided')}"}
                if time.monotonic() - started >= timeout:
                    self.client.stop_query_execution(QueryExecutionId=query_id)
                    return {"error": f"Athena query timed out after {timeout:g}s and was cancelled"}
                time.sleep(min(1, max(0, timeout - (time.monotonic() - started))))

            rows, columns, token = [], [], None
            first_page = True
            while True:
                if time.monotonic() - started >= timeout:
                    return {"error": "Athena result download timed out; no partial result returned"}
                request = {"QueryExecutionId": query_id, "MaxResults": min(1000, max_rows + 1)}
                if token:
                    request["NextToken"] = token
                page = self.client.get_query_results(**request)
                result_set = page["ResultSet"]
                if first_page:
                    columns = [column["Label"] for column in result_set["ResultSetMetadata"]["ColumnInfo"]]
                page_rows = result_set.get("Rows", [])
                if first_page:
                    page_rows = page_rows[1:]
                    first_page = False
                for row in page_rows:
                    values = [cell.get("VarCharValue") for cell in row["Data"]]
                    rows.append(values + [None] * (len(columns) - len(values)))
                    if len(rows) > max_rows:
                        break
                token = page.get("NextToken")
                if len(rows) > max_rows or not token:
                    break
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            result = {
                "success": True,
                "data": {"columns": columns, "rows": rows, "row_count": len(rows),
                         "query_id": query_id, "truncated": truncated,
                         "execution_time": round(time.monotonic() - started, 3)},
            }
            if truncated:
                result["warning"] = f"Result limited to {max_rows} rows"
            return result
        except (ValueError, KeyError, TypeError, BotoCoreError, ClientError) as exc:
            return {"error": f"Athena query failed: {exc}"}

    def get_tables(self, database: str = None) -> Dict[str, Any]:
        database = database or self.config.get("database", "default")
        paginator = self.client.get_paginator("list_table_metadata")
        tables = []
        for page in paginator.paginate(
            CatalogName=self.config.get("catalog", "AwsDataCatalog"), DatabaseName=database
        ):
            tables.extend(table["Name"] for table in page["TableMetadataList"])
        return {"success": True, "tables": tables}

    def describe_table(self, table_name: str, database: str = None) -> Dict[str, Any]:
        if not table_name:
            raise ValueError("table_name is required")
        result = self.client.get_table_metadata(
            CatalogName=self.config.get("catalog", "AwsDataCatalog"),
            DatabaseName=database or self.config.get("database", "default"), TableName=table_name,
        )["TableMetadata"]
        return {"success": True, "columns": [
            {"name": column["Name"], "type": column["Type"], "comment": column.get("Comment", "")}
            for column in result.get("Columns", []) + result.get("PartitionKeys", [])
        ]}


def handle_mcp_request(request: Dict[str, Any]) -> Dict[str, Any]:
    method, params = request.get("method"), request.get("params", {})
    if method == "get_server_info":
        return {"result": {"name": "athena", "description": "AWS Athena query service",
                           "capabilities": ["database_query", "sql_execution"],
                           "type": "stdio", "version": "1.0.0",
                           "methods": ["execute_query", "get_tables", "describe_table"],
                           "status": "ready"}}
    server = AthenaServer()
    server.initialize(params.get("config", {}))
    if method == "initialize":
        return {"result": {"success": True, "initialized": True}}
    if method == "execute_query":
        return {"result": server.execute_query(params.get("sql"), params.get("database"))}
    if method == "get_tables":
        return {"result": server.get_tables(params.get("database"))}
    if method == "describe_table":
        return {"result": server.describe_table(params.get("table_name"), params.get("database"))}
    return {"error": f"Unknown method: {method}"}


def main():
    for line in sys.stdin:
        try:
            response = handle_mcp_request(json.loads(line))
        except (ValueError, KeyError, TypeError, BotoCoreError, ClientError) as exc:
            response = {"error": str(exc)}
        except Exception as exc:
            print(f"Athena server error: {exc}", file=sys.stderr)
            response = {"error": f"Athena server failed: {exc}"}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
