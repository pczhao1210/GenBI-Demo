from mcp.server.fastmcp import FastMCP

server = FastMCP("GenBI test fixture")


@server.tool()
def echo(value: int) -> dict:
    return {"value": value}


@server.tool()
def fail() -> dict:
    raise ValueError("fixture failure")


if __name__ == "__main__":
    server.run(transport="stdio")
