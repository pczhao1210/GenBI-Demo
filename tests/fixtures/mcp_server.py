import sys

from mcp.server.fastmcp import FastMCP

server = FastMCP("GenBI test fixture", host="127.0.0.1",
                port=int(sys.argv[1]) if len(sys.argv) > 1 else 8000, stateless_http=True)


@server.tool()
def echo(value: int) -> dict:
    return {"value": value}


@server.tool()
def fail() -> dict:
    raise ValueError("fixture failure")


if __name__ == "__main__":
    server.run(transport="streamable-http" if len(sys.argv) > 1 else "stdio")
