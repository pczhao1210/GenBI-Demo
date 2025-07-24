# MCP Servers Configuration and Development Guide

## Overview

MCP (Model Context Protocol) is a standardized protocol for connecting AI assistants with various tools and data sources. This project uses MCP servers to extend GenBI's functionality, supporting database queries, file operations, and more.

## Existing MCP Servers

### 1. MySQL Server (`mysql_server.py`)
- **Function**: Connect and query MySQL database
- **Tools**: `execute_query`, `describe_table`, `get_tables`
- **Configuration**: Requires database connection information

### 2. Athena Server (`athena_server.py`)
- **Function**: Connect and query AWS Athena
- **Tools**: `execute_query`, `describe_table`, `get_tables`
- **Configuration**: Requires AWS credentials and S3 output location

## Configuring MCP Servers

### 1. Install Dependencies
```bash
pip install mcp
pip install pymysql  # MySQL support
pip install boto3    # AWS Athena support
```

### 2. Configuration File
Configure servers in `config/mcp_config.json`:

```json
{
  "mcp_servers": {
    "mysql": {
      "command": "python",
      "args": ["mcp_servers/mysql_server.py"],
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "username",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "database_name"
      }
    },
    "athena": {
      "command": "python",
      "args": ["mcp_servers/athena_server.py"],
      "env": {
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "your_access_key",
        "AWS_SECRET_ACCESS_KEY": "your_secret_key",
        "ATHENA_DATABASE": "your_database",
        "ATHENA_OUTPUT_LOCATION": "s3://your-bucket/query-results/"
      }
    }
  }
}
```

### 3. Test MCP Servers
```bash
# Test MySQL server
python mcp_servers/mysql_server.py

# Test Athena server
python mcp_servers/athena_server.py
```

## Creating New MCP Servers

### 1. Basic Structure
Create new MCP server file `mcp_servers/your_server.py`:

```python
#!/usr/bin/env python3
"""
Your Custom MCP Server
MCP server providing custom functionality
"""

import asyncio
import os
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import Resource, Tool, TextContent, ImageContent, EmbeddedResource
from pydantic import AnyUrl
import mcp.types as types

# Create server instance
server = Server("your-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List tools provided by the server
    """
    return [
        types.Tool(
            name="your_tool",
            description="Describe your tool functionality",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Parameter 1 description"
                    },
                    "param2": {
                        "type": "integer", 
                        "description": "Parameter 2 description"
                    }
                },
                "required": ["param1"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """
    Handle tool calls
    """
    if name == "your_tool":
        param1 = arguments.get("param1")
        param2 = arguments.get("param2", 0)
        
        try:
            # Implement your tool logic
            result = f"Processing result: {param1}, {param2}"
            
            return [
                types.TextContent(
                    type="text",
                    text=result
                )
            ]
        except Exception as e:
            return [
                types.TextContent(
                    type="text", 
                    text=f"Error: {str(e)}"
                )
            ]
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    # Read configuration from environment variables
    config = {
        "param1": os.getenv("YOUR_PARAM1", "default_value"),
        "param2": os.getenv("YOUR_PARAM2", "default_value")
    }
    
    # Run server
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="your-server",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Practical Example: File Operations Server

```python
#!/usr/bin/env python3
"""
File Operations MCP Server
MCP server providing file read/write operations
"""

import asyncio
import os
import json
from pathlib import Path
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
import mcp.types as types

server = Server("file-operations")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_file",
            description="Read file content",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path"
                    }
                },
                "required": ["file_path"]
            }
        ),
        types.Tool(
            name="write_file",
            description="Write file content",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path"
                    },
                    "content": {
                        "type": "string",
                        "description": "File content"
                    }
                },
                "required": ["file_path", "content"]
            }
        ),
        types.Tool(
            name="list_directory",
            description="List directory contents",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Directory path"
                    }
                },
                "required": ["directory_path"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "read_file":
        file_path = arguments["file_path"]
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return [types.TextContent(type="text", text=content)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Failed to read file: {str(e)}")]
    
    elif name == "write_file":
        file_path = arguments["file_path"]
        content = arguments["content"]
        try:
            # Ensure directory exists
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return [types.TextContent(type="text", text=f"File written successfully: {file_path}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Failed to write file: {str(e)}")]
    
    elif name == "list_directory":
        directory_path = arguments["directory_path"]
        try:
            files = []
            for item in Path(directory_path).iterdir():
                files.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })
            return [types.TextContent(type="text", text=json.dumps(files, indent=2))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Failed to list directory: {str(e)}")]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    # Set working directory restrictions (security consideration)
    allowed_paths = os.getenv("ALLOWED_PATHS", "/tmp,./data").split(",")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="file-operations",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
```

### 3. Configure New Server
Add to `config/mcp_config.json`:

```json
{
  "mcp_servers": {
    "file-operations": {
      "command": "python",
      "args": ["mcp_servers/file_operations_server.py"],
      "env": {
        "ALLOWED_PATHS": "/tmp,./data,./uploads"
      }
    }
  }
}
```

## Development Best Practices

### 1. Error Handling
- Always wrap tool logic with try-catch
- Return meaningful error messages
- Log detailed error information

### 2. Security Considerations
- Validate input parameters
- Restrict file access paths
- Use environment variables for sensitive information

### 3. Performance Optimization
- Use asynchronous operations
- Implement connection pooling (databases)
- Add appropriate timeout settings

### 4. Testing
```python
# Test tool calls
async def test_tool():
    result = await handle_call_tool("your_tool", {"param1": "test"})
    print(result)

# Run test
if __name__ == "__main__":
    asyncio.run(test_tool())
```

## Integration with GenBI

1. Place MCP server files in `mcp_servers/` directory
2. Update `config/mcp_config.json` configuration
3. Call tools through MCP client in GenBI
4. Display tool results in frontend interface

## Debugging Tips

### 1. Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add logging in tools
logger.info(f"Calling tool: {name}, arguments: {arguments}")
```

### 2. Standalone Testing
```bash
# Run server directly for testing
python mcp_servers/your_server.py
```

### 3. Use MCP Inspector
```bash
# Install MCP development tools
pip install mcp-dev-tools

# Inspect server
mcp-inspector mcp_servers/your_server.py
```

This way you can easily create and integrate new MCP servers into the GenBI system.