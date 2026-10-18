import re
import shutil
from copy import deepcopy
from urllib.parse import urlparse

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient
from utils.run_store import utcnow
from utils.tool_catalog import ToolCatalog, server_version, version_of


TEMPLATES = {
    "fetch": {
        "protocol": "mcp", "type": "stdio", "command": "uvx",
        "args": ["mcp-server-fetch==2026.10.10"], "status": "inactive",
        "categories": ["fetch"], "capabilities": {"external.fetch": "fetch"},
        "when_to_use": "Retrieve the body of a known public URL, not search or causal evidence.",
        "template": "fetch", "package_version": "2026.10.10",
    },
    "sequential_thinking": {
        "protocol": "mcp", "type": "stdio", "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking@1.0.0"],
        "status": "inactive", "categories": ["reasoning"],
        "capabilities": {"reasoning.sequential_thinking": "sequentialthinking"},
        "when_to_use": "Optional bounded complex planning assistance; not observed facts or calculations.",
        "template": "sequential_thinking", "package_version": "1.0.0",
    },
    "stdio": {"protocol": "mcp", "type": "stdio", "command": "", "args": [],
              "status": "inactive", "categories": [], "capabilities": {}, "when_to_use": ""},
    "http": {"protocol": "mcp", "type": "streamable_http", "url": "",
             "status": "inactive", "categories": [], "capabilities": {}, "when_to_use": ""},
}


class ToolManagement:
    def __init__(self, config=None, client=None):
        self.config = config or ConfigManager()
        self.client = client or MCPClient(self.config)

    def save_server(self, server_id, settings, replace=False):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", server_id):
            raise ValueError("Server ID requires 1-80 letters, digits, underscores or hyphens")
        settings = deepcopy(settings)
        if settings.get("protocol") != "mcp":
            raise ValueError("New servers must use standard MCP")
        if settings.get("type") == "stdio":
            if not isinstance(settings.get("command"), str) or not settings["command"].strip():
                raise ValueError("A stdio executable is required")
            if (not isinstance(settings.get("args"), list)
                    or not all(isinstance(arg, str) for arg in settings["args"])):
                raise ValueError("stdio args must be a JSON array of strings, not a shell command")
        elif settings.get("type") == "streamable_http":
            url = urlparse(settings.get("url", ""))
            if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password:
                raise ValueError("Streamable HTTP requires an HTTP(S) MCP endpoint without embedded credentials")
        else:
            raise ValueError("Only stdio and Streamable HTTP are supported")
        for field in ("env_refs", "header_refs"):
            refs = settings.get(field, {})
            if not isinstance(refs, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in refs.items()):
                raise ValueError(f"{field} must map names to environment variable references")
        if "env" in settings or "headers" in settings or "auth" in settings:
            raise ValueError("Use environment references; inline credentials and OAuth are not supported")
        timeout = settings.get("timeout", 30)
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise ValueError("MCP timeout must be from 1 to 300 seconds")
        mappings = settings.get("capabilities", {})
        if not isinstance(mappings, dict) or any(
                not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in mappings.items()):
            raise ValueError("Capabilities must map stable capability to exact tool name")
        categories = settings.get("categories", [])
        if not isinstance(categories, list) or any(
                category not in self.config.load_tools_config()["categories"] for category in categories):
            raise ValueError("Select known categories")
        settings["status"] = "inactive"
        settings["tool_confirmation_required"] = True
        def change(old):
            if old is not None and not replace:
                raise ValueError("Server ID already exists; edit that server explicitly instead of overwriting it")
            return {**(old or {}), **settings}
        return self.config.update_mcp_server(server_id, change)

    def discover(self, server_id, confirmed=False):
        if not confirmed:
            raise ValueError("Confirm execution: connection tests may download and run third-party software")
        server = self.config.load_mcp_config().get(server_id)
        if server is None:
            raise ValueError(f"Unknown MCP server: {server_id}")
        if server.get("type") == "stdio" and not shutil.which(server.get("command", "")):
            raise ValueError(f"Executable not installed: {server.get('command')}")
        info = self.client.get_server_info(server_id)
        if info.get("error"):
            raise RuntimeError(info["error"])
        if server.get("protocol") == "mcp":
            tools = info.get("tools", [])
            if not isinstance(tools, list) or len(tools) > 256:
                raise ValueError("Invalid MCP discovery result")
            names = set()
            for tool in tools:
                if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                        or not tool["name"] or tool["name"] in names):
                    raise ValueError("MCP discovery requires unique tool names")
                names.add(tool["name"])
                if not isinstance(tool.get("inputSchema"), dict):
                    raise ValueError("Discovered tools require an inputSchema object")
                try:
                    Draft202012Validator.check_schema(tool["inputSchema"])
                except SchemaError as exc:
                    raise ValueError(f"Invalid inputSchema for tool {tool['name']}: {exc.message}") from exc
            mappings = server.get("capabilities", {})
            if any(name not in names for name in mappings.values()):
                raise ValueError("Capability mapping does not match discovered tool names")
            self.config.save_tool_discovery(server_id, {
                "config_version": server_version(server), "discovered_at": utcnow(), "tools": tools,
                "schema_fingerprint": version_of(tools),
            })
        return info

    def connect_server(self, server_id, settings, confirmed=False):
        if not confirmed:
            raise ValueError("Confirm execution: connection tests may download and run third-party software")
        self.save_server(server_id, settings)
        try:
            info = self.discover(server_id, confirmed=True)
            def disable_discovered(config):
                for tool in info.get("tools", []):
                    config["tools"].setdefault(f"mcp:{server_id}:{tool['name']}", {})["enabled"] = False
            self.config.update_tools_config(disable_discovered)
            self.set_server_enabled(server_id, True)
            return info
        except (ValueError, RuntimeError) as exc:
            raise RuntimeError(f"Connection saved as disabled; verification failed: {exc}") from exc

    def set_server_enabled(self, server_id, enabled):
        servers = self.config.load_mcp_config()
        server = servers.get(server_id)
        if server is None:
            raise ValueError(f"Unknown MCP server: {server_id}")
        if enabled and server.get("protocol") == "mcp":
            snapshot = self.config.load_tool_discovery().get("servers", {}).get(server_id, {})
            if snapshot.get("config_version") != server_version(server):
                raise ValueError("Discover tools for the current connection before enabling")
            if any(name not in {tool["name"] for tool in snapshot["tools"]}
                   for name in server.get("capabilities", {}).values()):
                raise ValueError("Capability mapping does not match discovered tool names")
        expected = version_of(server)
        def change(current):
            if current is None or version_of(current) != expected:
                raise ValueError("Server configuration changed; reload before enabling or disabling")
            return {**current, "status": "active" if enabled else "inactive"}
        self.config.update_mcp_server(server_id, change)

    def delete_server(self, server_id):
        servers = self.config.load_mcp_config()
        if server_id not in servers:
            raise ValueError(f"Unknown MCP server: {server_id}")
        self.config.update_mcp_server(server_id, lambda current: None)

    def update_tool(self, tool_id, override):
        def change(settings):
            existing = settings["tools"].get(tool_id, {})
            settings["tools"][tool_id] = {
                **existing, **override, "policy": {**existing.get("policy", {}), **override.get("policy", {})}}
        self.config.update_tools_config(change)

    def set_default(self, capability, tool_id):
        ToolCatalog(self.config).resolve(capability, tool_id)
        self.config.update_tools_config(lambda settings: settings["default_providers"].update({capability: tool_id}))
