#!/usr/bin/env python3
"""
标准MCP工具规范 - 符合MCP 2025-06-18协议
每个工具都包含完整的schema定义、描述和参数规范
"""

from typing import Dict, Any, List
import json

class MCPToolRegistry:
    """MCP工具注册表，管理所有可用工具的定义"""
    
    def __init__(self):
        self.tools = {}
        self._register_default_tools()
        for name, capability, extra, required in (
            ("database_query", "database.query", {"sql": {"type": "string"}}, ["sql"]),
            ("database_metadata", "database.metadata", {"table": {"type": "string"}}, []),
            ("database_preview", "database.preview", {"table": {"type": "string"}}, ["table"]),
        ):
            self.register_tool({
                "name": name, "description": f"{capability} on an explicit configured datasource_id",
                "capability": capability,
                "inputSchema": {"type": "object", "additionalProperties": False,
                                "properties": {"datasource_id": {"type": "string"}, **extra},
                                "required": ["datasource_id", *required]},
            })
    
    def _register_default_tools(self):
        """注册默认的MCP工具"""
        
        # 1. Athena数据库查询工具
        self.register_tool({
            "name": "athena_query",
            "description": "Execute SQL queries against AWS Athena data warehouse. Supports complex analytical queries, aggregations, and joins across large datasets stored in S3.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL query to execute. Should be valid Athena SQL syntax."
                    },
                    "database": {
                        "type": "string",
                        "description": "Target database name in Athena catalog",
                        "default": "default"
                    },
                    "config": {
                        "type": "object",
                        "description": "Athena connection configuration",
                        "properties": {
                            "region": {"type": "string", "description": "AWS region"},
                            "aws_access_key_id": {"type": "string", "description": "AWS access key"},
                            "aws_secret_access_key": {"type": "string", "description": "AWS secret key"},
                            "s3_output_location": {"type": "string", "description": "S3 bucket for query results"}
                        },
                        "required": ["region"]
                    }
                },
                "required": ["sql", "config"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {
                        "type": "object", 
                        "properties": {
                            "columns": {"type": "array", "items": {"type": "string"}},
                            "rows": {"type": "array", "items": {"type": "array"}},
                            "row_count": {"type": "integer"}
                        }
                    },
                    "query_id": {"type": "string"},
                    "execution_time": {"type": "number"}
                }
            },
            "annotations": {
                "audience": ["data_analysts", "business_users"],
                "destructiveHint": False
            }
        })
        
        # 2. Athena表结构查询工具
        self.register_tool({
            "name": "athena_describe_table", 
            "description": "Get detailed schema information for tables in AWS Athena including column names, data types, and comments.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table to describe"
                    },
                    "database": {
                        "type": "string", 
                        "description": "Database containing the table",
                        "default": "default"
                    },
                    "config": {
                        "type": "object",
                        "description": "Athena connection configuration"
                    }
                },
                "required": ["table_name", "config"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "comment": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "annotations": {
                "audience": ["data_analysts", "developers"],
                "destructiveHint": False
            }
        })
        
        # 3. MySQL数据库查询工具
        self.register_tool({
            "name": "mysql_query",
            "description": "Execute one read-only SELECT or WITH query against MySQL with bounded result rows.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "One read-only SQL query, including SELECT and WITH queries."
                    },
                    "config": {
                        "type": "object",
                        "description": "MySQL connection configuration",
                        "properties": {
                            "host": {"type": "string", "description": "MySQL server hostname"},
                            "port": {"type": "integer", "description": "MySQL server port", "default": 3306},
                            "username": {"type": "string", "description": "Database username"},
                            "password": {"type": "string", "description": "Database password"},
                            "database": {"type": "string", "description": "Database name"},
                            "connection_timeout": {"type": "integer", "default": 10}
                        },
                        "required": ["host", "username", "password", "database"]
                    }
                },
                "required": ["sql", "config"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "columns": {"type": "array", "items": {"type": "string"}},
                            "rows": {"type": "array", "items": {"type": "array"}},
                            "affected_rows": {"type": "integer"}
                        }
                    },
                    "execution_time": {"type": "number"}
                }
            },
            "annotations": {
                "audience": ["developers", "data_analysts"],
                "destructiveHint": False
            }
        })
        
        # 4. MySQL表结构查询工具
        self.register_tool({
            "name": "mysql_describe_table",
            "description": "Get comprehensive table schema information from MySQL including columns, indexes, constraints, and statistics.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string", 
                        "description": "Name of the table to analyze"
                    },
                    "config": {
                        "type": "object",
                        "description": "MySQL connection configuration"
                    }
                },
                "required": ["table_name", "config"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object", 
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "nullable": {"type": "boolean"},
                                "key": {"type": "string"},
                                "default": {"type": "string"},
                                "extra": {"type": "string"}
                            }
                        }
                    },
                    "indexes": {"type": "array"},
                    "row_count": {"type": "integer"}
                }
            },
            "annotations": {
                "audience": ["developers", "database_administrators"],
                "destructiveHint": False
            }
        })
        
        # 5. 网页搜索工具
        self.register_tool({
            "name": "web_search",
            "description": "Search the web for current information using automated browser technology. Returns structured data from search results.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query terms. Use natural language or specific keywords."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of search results to return",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20
                    }
                },
                "required": ["query"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "snippet": {"type": "string"},
                                "published_date": {"type": "string"}
                            }
                        }
                    },
                    "search_metadata": {
                        "type": "object",
                        "properties": {
                            "total_results": {"type": "integer"},
                            "search_time": {"type": "number"}
                        }
                    }
                }
            },
            "annotations": {
                "audience": ["researchers", "analysts", "general_users"],
                "destructiveHint": False
            }
        })
        
        # 6. 网页内容抓取工具
        self.register_tool({
            "name": "web_fetch",
            "description": "Fetch and extract structured content from web pages. Handles dynamic content and returns clean, readable text.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the web page to fetch. Must be a valid HTTP/HTTPS URL."
                    }
                },
                "required": ["url"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "content": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "word_count": {"type": "integer"},
                            "load_time": {"type": "number"}
                        }
                    }
                }
            },
            "annotations": {
                "audience": ["researchers", "content_creators", "analysts"],
                "destructiveHint": False
            }
        })
    
    def register_tool(self, tool_def: Dict[str, Any]):
        """注册一个新工具"""
        name = tool_def.get("name")
        if not name:
            raise ValueError("Tool must have a name")
        
        # 验证工具定义符合MCP规范
        self._validate_tool_definition(tool_def)
        tool_def["inputSchema"].setdefault("additionalProperties", False)
        
        self.tools[name] = tool_def
    
    def _validate_tool_definition(self, tool_def: Dict[str, Any]):
        """验证工具定义符合MCP规范"""
        required_fields = ["name", "description", "inputSchema"]
        
        for field in required_fields:
            if field not in tool_def:
                raise ValueError(f"Tool definition missing required field: {field}")
        
        # 验证inputSchema格式
        input_schema = tool_def["inputSchema"]
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            raise ValueError("inputSchema must be a JSON Schema object")
    
    def get_tool(self, name: str) -> Dict[str, Any]:
        """获取特定工具定义"""
        return self.tools.get(name)
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有可用工具"""
        return list(self.tools.values())
    
    def get_tools_by_audience(self, audience: str) -> List[Dict[str, Any]]:
        """根据目标用户筛选工具"""
        filtered_tools = []
        for tool in self.tools.values():
            tool_audiences = tool.get("annotations", {}).get("audience", [])
            if audience in tool_audiences:
                filtered_tools.append(tool)
        return filtered_tools
    
    def to_mcp_manifest(self) -> Dict[str, Any]:
        """生成标准MCP服务器manifest"""
        return {
            "name": "GenBI-MCP-Server",
            "version": "1.0.0",
            "description": "GenBI生成式商业智能MCP工具服务器，提供数据库查询和网页抓取功能",
            "protocol_version": "2025-06-18",
            "capabilities": {
                "tools": {
                    "listChanged": True
                }
            },
            "tools": list(self.tools.values())
        }

# 创建全局工具注册表实例
mcp_tool_registry = MCPToolRegistry()

def get_available_tools() -> List[Dict[str, Any]]:
    """获取所有可用的MCP工具"""
    return mcp_tool_registry.list_tools()

def get_tool_by_name(name: str) -> Dict[str, Any]:
    """根据名称获取工具定义"""
    return mcp_tool_registry.get_tool(name)

if __name__ == "__main__":
    # 输出工具清单用于调试
    print("🔧 GenBI MCP工具注册表")
    print("=" * 50)
    
    for tool in mcp_tool_registry.list_tools():
        print(f"📋 {tool['name']}")
        print(f"   📝 {tool['description']}")
        print(f"   👥 目标用户: {', '.join(tool.get('annotations', {}).get('audience', []))}")
        print(f"   ⚠️  破坏性操作: {'是' if tool.get('annotations', {}).get('destructiveHint') else '否'}")
        print()
    
    print(f"📊 总计: {len(mcp_tool_registry.tools)} 个工具")