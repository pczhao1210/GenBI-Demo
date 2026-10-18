from typing import Any, Dict, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from utils.mcp_client import MCPClient
from utils.config_manager import ConfigManager
from utils.datasources import DatabaseAdapter, normalize_engine
from utils.resource_scope import ScopedConfig

router = APIRouter()


class TestConnectionRequest(BaseModel):
    type: Literal["mysql", "athena", "postgresql", "pgsql", "postgres", "mssql"]
    config: Dict[str, Any]


@router.get("/schema")
def get_database_schema(db: str, profile_id: str | None = None):
    return ScopedConfig(ConfigManager(), profile_id).resolve_datasource(db)["schema"]


@router.post("/test-connection")
def test_database_connection(request: TestConnectionRequest):
    if not request.config:
        raise ValueError("Connection configuration is required")
    source = {"datasource_id": "connection-test", "engine": normalize_engine(request.type), "config": request.config}
    result = DatabaseAdapter(source, MCPClient()).metadata()
    return {"status": "success", "database_type": request.type, "tables": result["tables"]}


@router.get("/sources")
def list_sources(profile_id: str | None = None):
    return [{key: value for key, value in source.items() if key != "config"}
            for source in ScopedConfig(ConfigManager(), profile_id).load_datasources().values()]


@router.post("/sources")
def save_source(source: Dict[str, Any], profile_id: str | None = None):
    saved = ScopedConfig(ConfigManager(), profile_id).save_datasource(source)
    return {key: value for key, value in saved.items() if key != "config"}


@router.get("/sources/{source_id}/metadata")
def metadata(source_id: str, table: str | None = None, profile_id: str | None = None):
    config = ScopedConfig(ConfigManager(), profile_id)
    source = config.resolve_datasource(source_id)
    if table and not config.table_visible(source_id, table):
        raise ValueError("Table schema is outside the current Profile")
    result = DatabaseAdapter(source, MCPClient(config)).metadata(table)
    if not table and "tables" in result:
        result["tables"] = [item for item in result["tables"] if config.table_visible(
            source_id, item.get("name", str(item)) if isinstance(item, dict) else item)]
    return result


@router.get("/sources/{source_id}/preview")
def preview(source_id: str, table: str, profile_id: str | None = None):
    config = ScopedConfig(ConfigManager(), profile_id)
    source = config.resolve_datasource(source_id)
    if not config.table_visible(source_id, table):
        raise ValueError("Table schema is outside the current Profile")
    return DatabaseAdapter(source, MCPClient(config)).preview(table)


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, profile_id: str | None = None):
    ScopedConfig(ConfigManager(), profile_id).delete_datasource(source_id)
    return {"status": "deleted"}
