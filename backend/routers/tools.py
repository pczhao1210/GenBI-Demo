from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from utils.model_router import ToolBudget
from utils.tool_catalog import ToolCatalog
from utils.tool_execution import ToolInvoker
from utils.tool_management import TEMPLATES, ToolManagement
from utils.run_context import FrozenConfig, snapshot_config

router = APIRouter()


class ServerSettings(BaseModel):
    settings: dict[str, Any]
    replace_existing: bool = False


class Enable(BaseModel):
    enabled: bool


class Connect(BaseModel):
    settings: dict[str, Any]
    confirmed: bool = False


class Probe(BaseModel):
    confirmed: bool = False


class Override(BaseModel):
    settings: dict[str, Any]


class Provider(BaseModel):
    tool_id: str


class Trial(BaseModel):
    capability: str
    tool_id: str
    arguments: dict[str, Any]
    datasource_ids: list[str] | None = None
    profile_id: str | None = None


@router.get("")
def directory():
    management = ToolManagement()
    catalog = ToolCatalog(management.config)
    return {"version": catalog.version, "categories": catalog.settings["categories"], "tools": catalog.list()}


@router.get("/templates")
def templates():
    return TEMPLATES


@router.put("/servers/{server_id}")
def save_server(server_id: str, request: ServerSettings):
    ToolManagement().save_server(server_id, request.settings, request.replace_existing)
    return {"server_id": server_id, "enabled": False}


@router.post("/servers/{server_id}/discover")
def discover(server_id: str, request: Probe):
    info = ToolManagement().discover(server_id, request.confirmed)
    return {"name": info.get("name"), "tool_count": len(info.get("tools", []))}


@router.post("/servers/{server_id}/connect")
def connect(server_id: str, request: Connect):
    info = ToolManagement().connect_server(server_id, request.settings, request.confirmed)
    return {"server_id": server_id, "enabled": True, "tools": info.get("tools", []),
            "tools_enabled": False}


@router.post("/servers/{server_id}/enabled")
def enable(server_id: str, request: Enable):
    ToolManagement().set_server_enabled(server_id, request.enabled)
    return {"server_id": server_id, "enabled": request.enabled}


@router.delete("/servers/{server_id}")
def delete(server_id: str):
    ToolManagement().delete_server(server_id)
    return {"server_id": server_id, "deleted": True}


@router.put("/definitions/{tool_id}")
def override(tool_id: str, request: Override):
    ToolManagement().update_tool(tool_id, request.settings)
    return {"tool_id": tool_id}


@router.put("/providers/{capability}")
def provider(capability: str, request: Provider):
    ToolManagement().set_default(capability, request.tool_id)
    return {"capability": capability, "tool_id": request.tool_id}


@router.post("/trial")
def trial(request: Trial):
    management = ToolManagement()
    budget = ToolBudget(max_calls=4)
    definition = ToolCatalog(management.config).resolve(request.capability, request.tool_id)
    if definition["output_kind"] == "interpretation":
        raise ValueError("Reasoning tools are restricted to bounded planning, not diagnostic evidence")
    try:
        scoped = FrozenConfig(snapshot_config(management.config, request.profile_id))
        result = ToolInvoker(scoped, management.client, budget, request.datasource_ids).call(
            request.capability, request.arguments, request.tool_id)
        return {"result": result, "calls": budget.records}
    finally:
        management.client.close()
