# MCP Servers 配置和开发指南

## 概述

MCP (Model Context Protocol) 是一个标准化协议，用于连接AI助手与各种工具和数据源。本项目使用MCP服务器来扩展GenBI的功能，支持数据库查询、文件操作等。

## 现有MCP服务器

### 1. MySQL服务器 (`mysql_server.py`)
- **功能**: 连接和查询MySQL数据库
- **工具**: `execute_query`, `describe_table`, `get_tables`
- **配置**: 需要数据库连接信息

### 2. Athena服务器 (`athena_server.py`)
- **功能**: 连接和查询AWS Athena
- **工具**: `execute_query`, `describe_table`, `get_tables`
- **配置**: 需要AWS凭证和S3输出位置

## 配置MCP服务器

### 1. 安装依赖
```bash
pip install mcp
pip install pymysql  # MySQL支持
pip install boto3    # AWS Athena支持
```

### 2. 配置文件
在 `config/mcp_config.json` 中配置服务器：

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

### 3. 测试MCP服务器
```bash
# 测试MySQL服务器
python mcp_servers/mysql_server.py

# 测试Athena服务器
python mcp_servers/athena_server.py
```

## 创建新的MCP服务器

### 1. 基本结构
创建新的MCP服务器文件 `mcp_servers/your_server.py`：

```python
#!/usr/bin/env python3
"""
Your Custom MCP Server
提供自定义功能的MCP服务器
"""

import asyncio
import os
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import Resource, Tool, TextContent, ImageContent, EmbeddedResource
from pydantic import AnyUrl
import mcp.types as types

# 创建服务器实例
server = Server("your-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    列出服务器提供的工具
    """
    return [
        types.Tool(
            name="your_tool",
            description="描述你的工具功能",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "参数1描述"
                    },
                    "param2": {
                        "type": "integer", 
                        "description": "参数2描述"
                    }
                },
                "required": ["param1"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """
    处理工具调用
    """
    if name == "your_tool":
        param1 = arguments.get("param1")
        param2 = arguments.get("param2", 0)
        
        try:
            # 实现你的工具逻辑
            result = f"处理结果: {param1}, {param2}"
            
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
                    text=f"错误: {str(e)}"
                )
            ]
    else:
        raise ValueError(f"未知工具: {name}")

async def main():
    # 从环境变量读取配置
    config = {
        "param1": os.getenv("YOUR_PARAM1", "default_value"),
        "param2": os.getenv("YOUR_PARAM2", "default_value")
    }
    
    # 运行服务器
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

### 2. 实际用例：文件操作服务器

```python
#!/usr/bin/env python3
"""
File Operations MCP Server
提供文件读写操作的MCP服务器
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
            description="读取文件内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径"
                    }
                },
                "required": ["file_path"]
            }
        ),
        types.Tool(
            name="write_file",
            description="写入文件内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容"
                    }
                },
                "required": ["file_path", "content"]
            }
        ),
        types.Tool(
            name="list_directory",
            description="列出目录内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "目录路径"
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
            return [types.TextContent(type="text", text=f"读取文件失败: {str(e)}")]
    
    elif name == "write_file":
        file_path = arguments["file_path"]
        content = arguments["content"]
        try:
            # 确保目录存在
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return [types.TextContent(type="text", text=f"文件写入成功: {file_path}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"写入文件失败: {str(e)}")]
    
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
            return [types.TextContent(type="text", text=f"列出目录失败: {str(e)}")]
    
    else:
        raise ValueError(f"未知工具: {name}")

async def main():
    # 设置工作目录限制（安全考虑）
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

### 3. 配置新服务器
在 `config/mcp_config.json` 中添加：

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

## 开发最佳实践

### 1. 错误处理
- 始终使用try-catch包装工具逻辑
- 返回有意义的错误信息
- 记录详细的错误日志

### 2. 安全考虑
- 验证输入参数
- 限制文件访问路径
- 使用环境变量存储敏感信息

### 3. 性能优化
- 使用异步操作
- 实现连接池（数据库）
- 添加适当的超时设置

### 4. 测试
```python
# 测试工具调用
async def test_tool():
    result = await handle_call_tool("your_tool", {"param1": "test"})
    print(result)

# 运行测试
if __name__ == "__main__":
    asyncio.run(test_tool())
```

## 集成到GenBI

1. 将MCP服务器文件放在 `mcp_servers/` 目录
2. 更新 `config/mcp_config.json` 配置
3. 在GenBI中通过MCP客户端调用工具
4. 在前端界面中展示工具结果

## 调试技巧

### 1. 日志记录
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 在工具中添加日志
logger.info(f"调用工具: {name}, 参数: {arguments}")
```

### 2. 独立测试
```bash
# 直接运行服务器进行测试
python mcp_servers/your_server.py
```

### 3. 使用MCP检查器
```bash
# 安装MCP开发工具
pip install mcp-dev-tools

# 检查服务器
mcp-inspector mcp_servers/your_server.py
```

这样就可以轻松创建和集成新的MCP服务器到GenBI系统中。