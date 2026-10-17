import asyncio
import json
import os
import threading
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta

from utils.tool_catalog import version_of

_session_slots = threading.BoundedSemaphore(16)
logger = logging.getLogger(__name__)


def _error_detail(error):
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(dict.fromkeys(_error_detail(item) for item in error.exceptions[:4]))[:1000]
    return f"{type(error).__name__}: {error}"[:1000]


class StandardMCPClient:
    def __init__(self, settings):
        self.settings = settings

    @asynccontextmanager
    async def connect(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        timeout = self.settings.get("timeout", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("MCP timeout must be positive")
        async with AsyncExitStack() as stack:
            if not _session_slots.acquire(blocking=False):
                raise RuntimeError("Global MCP session budget exhausted")
            stack.callback(_session_slots.release)
            transport = self.settings.get("type", "stdio")
            if transport == "stdio":
                command, args = self.settings.get("command"), self.settings.get("args", [])
                if (not isinstance(command, str) or not command or not isinstance(args, list)
                        or not all(isinstance(arg, str) for arg in args)):
                    raise ValueError("Standard MCP stdio requires command and string args")
                env = self._environment("env_refs")
                reasoning = ("reasoning.sequential_thinking" in self.settings.get("capabilities", {})
                             or self.settings.get("template") == "sequential_thinking")
                if reasoning:
                    env["DISABLE_THOUGHT_LOGGING"] = "true"
                stderr = stack.enter_context(open(os.devnull, "w"))
                streams = await stack.enter_async_context(stdio_client(
                    StdioServerParameters(command=command, args=args, cwd=self.settings.get("cwd"),
                                          env=env or None), errlog=stderr))
            elif transport == "streamable_http":
                streams = await stack.enter_async_context(streamablehttp_client(
                    self.settings["url"], headers=self._environment("header_refs"),
                    timeout=timedelta(seconds=timeout)))
            else:
                raise ValueError(f"Unsupported standard MCP transport: {transport}")
            session = await stack.enter_async_context(ClientSession(
                streams[0], streams[1], read_timeout_seconds=timedelta(seconds=timeout)))
            async with asyncio.timeout(timeout):
                initialized = await session.initialize()
            yield session, initialized

    def _environment(self, field):
        result = {}
        for target, name in self.settings.get(field, {}).items():
            if not isinstance(name, str) or name not in os.environ:
                raise ValueError(f"Missing environment variable reference for {field}: {target}")
            result[target] = os.environ[name]
        return result

    async def on_session(self, session, initialized, method, params):
        async with asyncio.timeout(self.settings.get("timeout", 30)):
            if method == "get_server_info":
                listing = await session.list_tools()
                tools = list(listing.tools)
                while listing.nextCursor:
                    listing = await session.list_tools(cursor=listing.nextCursor)
                    tools.extend(listing.tools)
                    if len(tools) > 256:
                        raise RuntimeError("MCP discovery tool limit exceeded")
                return {"result": {"name": initialized.serverInfo.name, "protocol": initialized.protocolVersion,
                                   "tools": [tool.model_dump(mode="json") for tool in tools]}}
            tool = self.settings.get("tools", {}).get(method, method)
            result = await session.call_tool(tool, arguments=params)
            if result.isError:
                reasoning = ("reasoning.sequential_thinking" in self.settings.get("capabilities", {})
                             or self.settings.get("template") == "sequential_thinking")
                detail = "" if reasoning else ": " + "; ".join(
                    item.text for item in result.content if hasattr(item, "text"))[:500]
                raise RuntimeError(f"MCP tool failed: {tool}{detail}")
            content = [item.model_dump(mode="json") for item in result.content]
            payload = result.structuredContent
            if payload is None:
                payload = {"content": content}
                if len(content) == 1 and content[0].get("type") == "text":
                    try:
                        parsed = json.loads(content[0]["text"])
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        payload = parsed
            if not isinstance(payload, dict):
                payload = {"structured_content": payload, "content": content}
            return {"result": payload, "mcp_content": content,
                    "mcp_structured_content": result.structuredContent}

    async def request(self, method, params):
        async with self.connect() as (session, initialized):
            return await self.on_session(session, initialized, method, params)

    def call(self, method, params):
        try:
            return asyncio.run(self.request(method, params))
        except Exception as exc:
            stateful = ("reasoning.sequential_thinking" in self.settings.get("capabilities", {})
                        or self.settings.get("template") == "sequential_thinking")
            detail = type(exc).__name__ if stateful else _error_detail(exc)
            raise RuntimeError(f"Standard MCP call failed: {detail}") from exc


class RunMCPContext:
    """Each transport is entered, used and exited by one owner task on a stable loop."""

    def __init__(self, max_sessions=4, idle_seconds=60):
        self.max_sessions = max_sessions
        self.idle_seconds = idle_seconds
        self.sessions = {}
        self.closed = False
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="genbi-mcp", daemon=True)
        self.thread.start()

    async def _serve(self, client, queue):
        error = None
        try:
            async with client.connect() as (session, initialized):
                while True:
                    try:
                        request = await asyncio.wait_for(queue.get(), self.idle_seconds)
                    except TimeoutError:
                        return
                    if request is None:
                        return
                    method, params, response = request
                    try:
                        result = await client.on_session(session, initialized, method, params)
                        if not response.done():
                            response.set_result(result)
                    except Exception as exc:
                        stateful = ("reasoning.sequential_thinking" in client.settings.get("capabilities", {})
                                    or client.settings.get("template") == "sequential_thinking")
                        detail = type(exc).__name__ if stateful else _error_detail(exc)
                        if not response.done():
                            response.set_exception(RuntimeError(f"MCP call failed: {detail}"))
                        if stateful:
                            return
        except Exception as exc:
            stateful = ("reasoning.sequential_thinking" in client.settings.get("capabilities", {})
                        or client.settings.get("template") == "sequential_thinking")
            detail = type(exc).__name__ if stateful else _error_detail(exc)
            error = RuntimeError(f"MCP session failed: {detail}")
            logger.warning("MCP session %s failed (%s)", version_of(client.settings)[:12], type(exc).__name__)
        finally:
            while not queue.empty():
                request = queue.get_nowait()
                if request is not None and not request[2].done():
                    request[2].set_exception(error or RuntimeError("MCP session closed"))

    async def _call(self, settings, method, params):
        key = version_of(settings)
        if key in self.sessions and self.sessions[key][1].done():
            if ("reasoning.sequential_thinking" in settings.get("capabilities", {})
                    or settings.get("template") == "sequential_thinking"):
                raise RuntimeError("Stateful MCP session lost; restart planning from the public plan summary")
            del self.sessions[key]
        if key not in self.sessions:
            expired = [key for key, (_, task) in self.sessions.items() if task.done()]
            for expired_key in expired:
                del self.sessions[expired_key]
            if len(self.sessions) >= self.max_sessions:
                raise RuntimeError("Run MCP session budget exhausted")
            queue = asyncio.Queue()
            task = asyncio.create_task(self._serve(StandardMCPClient(settings), queue))
            self.sessions[key] = (queue, task)
        queue, task = self.sessions[key]
        response = self.loop.create_future()
        queue.put_nowait((method, params, response))
        done, _ = await asyncio.wait((response, task), return_when=asyncio.FIRST_COMPLETED)
        if response not in done:
            response.cancel()
            raise RuntimeError("MCP session closed before a response; call outcome may be unknown")
        return response.result()

    def call(self, settings, method, params):
        if self.closed:
            raise RuntimeError("MCP run context is closed")
        future = asyncio.run_coroutine_threadsafe(self._call(settings, method, params), self.loop)
        return future.result()

    async def _close(self):
        for queue, task in self.sessions.values():
            if not task.done():
                queue.put_nowait(None)
        await asyncio.gather(*(task for _, task in self.sessions.values()))
        self.sessions.clear()

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                asyncio.run_coroutine_threadsafe(self._close(), self.loop).result()
            finally:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.thread.join(5)
                self.loop.close()
