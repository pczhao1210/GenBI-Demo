import asyncio
import json
from contextlib import AsyncExitStack
from datetime import timedelta


class StandardMCPClient:
    def __init__(self, settings):
        self.settings = settings

    async def request(self, method, params):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        timeout = self.settings.get("timeout", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("MCP timeout must be positive")
        async with asyncio.timeout(timeout), AsyncExitStack() as stack:
            transport = self.settings.get("type", "stdio")
            if transport == "stdio":
                command = self.settings.get("command")
                args = self.settings.get("args", [])
                if not isinstance(command, str) or not command or not isinstance(args, list):
                    raise ValueError("Standard MCP stdio requires command and args")
                streams = await stack.enter_async_context(stdio_client(
                    StdioServerParameters(command=command, args=args)))
            elif transport == "streamable_http":
                streams = await stack.enter_async_context(streamablehttp_client(self.settings["url"]))
            else:
                raise ValueError(f"Unsupported standard MCP transport: {transport}")
            session = await stack.enter_async_context(ClientSession(
                streams[0], streams[1], read_timeout_seconds=timedelta(seconds=timeout)))
            initialized = await session.initialize()
            if method == "get_server_info":
                listing = await session.list_tools()
                return {"result": {"name": initialized.serverInfo.name, "protocol": initialized.protocolVersion,
                                   "tools": [tool.model_dump(mode="json") for tool in listing.tools]}}
            tool = self.settings.get("tools", {}).get(method, method)
            result = await session.call_tool(tool, arguments=params)
            if result.isError:
                raise RuntimeError(f"MCP tool {tool} failed: {result.content}")
            payload = result.structuredContent
            if payload is None:
                content = [item.model_dump(mode="json") for item in result.content]
                payload = {"content": content}
                if len(content) == 1 and content[0].get("type") == "text":
                    try:
                        parsed = json.loads(content[0]["text"])
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        payload = parsed
            return {"result": payload}

    def call(self, method, params):
        try:
            return asyncio.run(self.request(method, params))
        except Exception as exc:
            raise RuntimeError(f"Standard MCP call failed: {exc}") from exc
