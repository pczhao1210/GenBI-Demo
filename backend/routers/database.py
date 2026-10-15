from typing import Any, Dict, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from utils.bi_service import BIService, result_payload
from utils.mcp_client import MCPClient

router = APIRouter()


class TestConnectionRequest(BaseModel):
    type: Literal["mysql", "athena"]
    config: Dict[str, Any]


@router.get("/schema")
def get_database_schema(db: Literal["mysql", "athena"]):
    return BIService().schema(db)


@router.post("/test-connection")
def test_database_connection(request: TestConnectionRequest):
    if not request.config:
        raise ValueError("Connection configuration is required")
    result = result_payload(MCPClient().call_mcp_server_with_config(
        request.type, "get_tables", request.config,
        {"database": request.config.get("database", "default")},
    ))
    return {"status": "success", "database_type": request.type, "tables": result["tables"]}
