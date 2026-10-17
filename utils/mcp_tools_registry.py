"""Compatibility names and schemas derived from the unified tool catalog."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from utils.tool_catalog import compatibility_definitions


class MCPToolRegistry:
    def __init__(self):
        self.tools = {}
        for definition in compatibility_definitions():
            self.register_tool(definition)

    def register_tool(self, tool_def):
        if not all(tool_def.get(key) for key in ("name", "description", "inputSchema")):
            raise ValueError("Tool requires name, description and inputSchema")
        if tool_def["inputSchema"].get("type") != "object":
            raise ValueError("inputSchema must be a JSON Schema object")
        Draft202012Validator.check_schema(tool_def["inputSchema"])
        self.tools[tool_def["name"]] = deepcopy(tool_def)

    def get_tool(self, name):
        return deepcopy(self.tools.get(name))

    def list_tools(self):
        return deepcopy(list(self.tools.values()))

    def get_tools_by_audience(self, audience):
        return [tool for tool in self.list_tools()
                if audience in tool.get("annotations", {}).get("audience", [])]

    def to_mcp_manifest(self):
        return {"name": "GenBI-Tool-Compatibility", "version": "1.0.0",
                "description": "Compatibility view; built-in RPC is not standard MCP.",
                "tools": self.list_tools()}


mcp_tool_registry = MCPToolRegistry()


def get_available_tools():
    return mcp_tool_registry.list_tools()


def get_tool_by_name(name):
    return mcp_tool_registry.get_tool(name)
