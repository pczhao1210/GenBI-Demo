from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient
from utils.mcp_tool_handler import MCPToolCallHandler

router = APIRouter()


class ExecuteRequest(BaseModel):
    server: str
    tool: str
    params: Dict[str, Any]


@router.post("/execute")
def execute_mcp_tool(request: ExecuteRequest):
    expected = {"athena": "athena_", "mysql": "mysql_", "playwright": "web_"}.get(request.server)
    if expected is None or not request.tool.startswith(expected):
        raise ValueError("Tool does not belong to the selected server")
    config_manager = ConfigManager()
    arguments = dict(request.params)
    if request.server in ("athena", "mysql") and "config" not in arguments:
        arguments["config"] = config_manager.load_database_config().get(request.server, {})
    result = MCPToolCallHandler(MCPClient(config_manager)).execute_tool_call(request.tool, arguments)
    if result.get("error"):
        if result.get("code") in ("INVALID_PARAMS", "TOOL_NOT_FOUND", "UNSUPPORTED_TOOL"):
            raise ValueError(result["error"])
        raise RuntimeError(result["error"])
    return result


@router.get("/status")
def get_mcp_status():
    client = MCPClient()
    servers = {}
    for name, config in client.config_manager.load_mcp_config().items():
        info = client.get_server_info(name)
        servers[name] = {"enabled": config.get("status") == "active",
                         "reachable": "error" not in info, "info": info}
    return {"servers": servers}
