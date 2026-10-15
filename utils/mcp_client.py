import json
import subprocess
import sys
from typing import Any, Dict, List

from utils.config_manager import ConfigManager, PROJECT_ROOT


def normalize_response(response: Any) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise ValueError("Tool server response must be an object")
    result = response.get("result")
    if "error" in response:
        return {"error": str(response["error"])}
    if isinstance(result, dict) and ("error" in result or result.get("success") is False):
        return {"error": str(result.get("error", "Tool execution failed"))}
    if not isinstance(result, dict):
        raise ValueError("Tool server response is missing result")
    return response


class MCPClient:
    def __init__(self, config_manager=None):
        self.config_manager = config_manager or ConfigManager()

    def _call(self, server_type: str, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        settings = self.config_manager.load_mcp_config().get(server_type)
        if not isinstance(settings, dict) or not settings:
            return {"error": f"Tool server is not configured: {server_type}"}
        if method != "get_server_info" and settings.get("status") != "active":
            return {"error": f"Tool server is disabled: {server_type}; enable it in MCP management"}
        if settings.get("type") != "stdio":
            return {"error": "Only the built-in stdio RPC transport is supported; SSE is not implemented"}
        command = settings.get("command") or sys.executable
        if not isinstance(command, str):
            return {"error": "Server command must be a string"}
        if command in ("python", "python3"):
            command = sys.executable
        args = settings.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            return {"error": "Server args must be a list of strings"}
        connection_config = params.get("config", {})
        if not isinstance(connection_config, dict):
            return {"error": "Connection config must be an object"}
        query_timeout = connection_config.get("query_timeout", 240)
        if isinstance(query_timeout, bool) or not isinstance(query_timeout, (int, float)) or query_timeout <= 0:
            return {"error": "query_timeout must be a positive number"}
        timeout = settings.get("timeout", query_timeout + 15)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            return {"error": "Server timeout must be a positive number"}
        try:
            completed = subprocess.run(
                [command, *args], input=json.dumps({"method": method, "params": params}) + "\n",
                capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=timeout, check=False,
            )
            if completed.returncode:
                return {"error": f"Tool server {server_type} exited with code {completed.returncode}: "
                                 f"{completed.stderr.strip()[:500]}"}
            return normalize_response(json.loads(completed.stdout.strip()))
        except subprocess.TimeoutExpired:
            return {"error": f"Tool server {server_type} timed out after {timeout} seconds"}
        except (OSError, ValueError) as exc:
            return {"error": f"Tool server {server_type} failed: {exc}"}

    def call_mcp_server(self, server_type: str, method: str,
                        params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._call(server_type, method, dict(params or {}))

    def call_mcp_server_with_config(self, server_type: str, method: str,
                                    config: Dict[str, Any],
                                    params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._call(server_type, method, {**(params or {}), "config": config})

    def get_tables(self, database_type: str, config: Dict[str, Any]) -> List[Any]:
        result = self.call_mcp_server_with_config(
            database_type, "get_tables", config, {"database": config.get("database", "default")}
        )
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]["tables"]

    def describe_table(self, database_type: str, config: Dict[str, Any],
                       table_name: str) -> List[Dict[str, Any]]:
        result = self.call_mcp_server_with_config(
            database_type, "describe_table", config,
            {"table_name": table_name, "database": config.get("database", "default")},
        )
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]["columns"]

    def get_server_info(self, server_type: str) -> Dict[str, Any]:
        result = self.call_mcp_server(server_type, "get_server_info")
        return result if "error" in result else result["result"]

    def discover_available_servers(self) -> Dict[str, Dict[str, Any]]:
        return {
            path.name.removesuffix("_server.py"): {
                "name": path.name.removesuffix("_server.py"),
                "description": f"Built-in {path.name.removesuffix('_server.py')} stdio RPC server",
            }
            for path in sorted((PROJECT_ROOT / "mcp_servers").glob("*_server.py"))
        }
