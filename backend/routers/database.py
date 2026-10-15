from typing import Any, Dict, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from utils.bi_service import BIService, result_payload
from utils.mcp_client import MCPClient
from utils.config_manager import ConfigManager
from utils.datasources import DatabaseAdapter, normalize_engine

router = APIRouter()


class TestConnectionRequest(BaseModel):
    type: Literal["mysql", "athena", "postgresql", "pgsql", "postgres", "mssql"]
    config: Dict[str, Any]


@router.get("/schema")
def get_database_schema(db: str):
    return BIService().schema(db)


@router.post("/test-connection")
def test_database_connection(request: TestConnectionRequest):
    if not request.config:
        raise ValueError("Connection configuration is required")
    source = {"datasource_id": "connection-test", "engine": normalize_engine(request.type), "config": request.config}
    result = DatabaseAdapter(source, MCPClient()).metadata()
    return {"status": "success", "database_type": request.type, "tables": result["tables"]}


@router.get("/sources")
def list_sources():
    return [{key: value for key, value in source.items() if key != "config"}
            for source in ConfigManager().load_datasources().values()]


@router.post("/sources")
def save_source(source: Dict[str, Any]):
    saved = ConfigManager().save_datasource(source)
    return {key: value for key, value in saved.items() if key != "config"}


@router.get("/sources/{source_id}/metadata")
def metadata(source_id: str, table: str | None = None):
    config = ConfigManager()
    return DatabaseAdapter(config.resolve_datasource(source_id), MCPClient(config)).metadata(table)


@router.get("/sources/{source_id}/preview")
def preview(source_id: str, table: str):
    config = ConfigManager()
    return DatabaseAdapter(config.resolve_datasource(source_id), MCPClient(config)).preview(table)
