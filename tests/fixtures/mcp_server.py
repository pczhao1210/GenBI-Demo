import sys
import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

server = FastMCP("GenBI test fixture", host="127.0.0.1",
                port=int(sys.argv[1]) if len(sys.argv) > 1 else 8000, stateless_http=True)


@server.tool()
def echo(value: int) -> dict:
    return {"value": value}


@server.tool()
def fail() -> dict:
    raise ValueError("fixture failure")


calls = 0


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def counter() -> dict:
    global calls
    calls += 1
    return {"calls": calls, "pid": os.getpid()}


@server.tool()
def sequentialthinking(thought: str, thoughtNumber: int, totalThoughts: int,
                       nextThoughtNeeded: bool) -> dict:
    return {"thoughtNumber": thoughtNumber, "totalThoughts": totalThoughts,
            "nextThoughtNeeded": nextThoughtNeeded, "private_echo": thought}


if __name__ == "__main__":
    server.run(transport="streamable-http" if len(sys.argv) > 1 else "stdio")
