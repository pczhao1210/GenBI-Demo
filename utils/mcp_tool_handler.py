#!/usr/bin/env python3
"""
符合MCP协议的工具调用系统
实现标准的MCP client-server交互模式，支持LLM工具调用
"""

import json
import sys
from typing import Dict, Any, List, Optional
from utils.mcp_tools_registry import mcp_tool_registry
from utils.mcp_client import MCPClient

class MCPToolCallHandler:
    """处理符合MCP协议的工具调用"""
    
    def __init__(self):
        self.mcp_client = MCPClient()
        self.tool_registry = mcp_tool_registry
    
    def generate_tool_definitions_for_llm(self) -> List[Dict[str, Any]]:
        """
        生成符合OpenAI Functions格式的工具定义，供LLM使用
        这些定义基于MCP工具注册表，确保一致性
        """
        llm_tools = []
        
        for tool in self.tool_registry.list_tools():
            # 转换MCP工具定义为OpenAI Functions格式
            llm_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"]
                }
            }
            
            # 添加注释信息到描述中
            annotations = tool.get("annotations", {})
            if annotations:
                audience = annotations.get("audience", [])
                destructive = annotations.get("destructiveHint", False)
                
                enhanced_desc = tool["description"]
                if audience:
                    enhanced_desc += f"\n适用用户: {', '.join(audience)}"
                if destructive:
                    enhanced_desc += "\n⚠️ 注意: 此工具可能会修改数据，请谨慎使用"
                
                llm_tool["function"]["description"] = enhanced_desc
            
            llm_tools.append(llm_tool)
        
        return llm_tools
    
    def execute_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具调用，遵循MCP协议标准
        """
        # 获取工具定义
        tool_def = self.tool_registry.get_tool(tool_name)
        if not tool_def:
            return {
                "error": f"未知工具: {tool_name}",
                "code": "TOOL_NOT_FOUND"
            }
        
        # 验证输入参数
        validation_result = self._validate_arguments(tool_def["inputSchema"], arguments)
        if not validation_result["valid"]:
            return {
                "error": f"参数验证失败: {validation_result['error']}",
                "code": "INVALID_PARAMS"
            }
        
        # 根据工具名称路由到相应的执行函数
        try:
            if tool_name.startswith("athena_"):
                return self._execute_athena_tool(tool_name, arguments)
            elif tool_name.startswith("mysql_"):
                return self._execute_mysql_tool(tool_name, arguments)
            elif tool_name.startswith("web_"):
                return self._execute_web_tool(tool_name, arguments)
            else:
                return {
                    "error": f"不支持的工具类型: {tool_name}",
                    "code": "UNSUPPORTED_TOOL"
                }
        except Exception as e:
            return {
                "error": f"工具执行异常: {str(e)}",
                "code": "EXECUTION_ERROR"
            }
    
    def _validate_arguments(self, schema: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
        """验证工具参数是否符合schema定义"""
        try:
            # 简化的JSON Schema验证
            required_fields = schema.get("required", [])
            properties = schema.get("properties", {})
            
            # 检查必需字段
            for field in required_fields:
                if field not in arguments:
                    return {
                        "valid": False,
                        "error": f"缺少必需参数: {field}"
                    }
            
            # 检查字段类型
            for field, value in arguments.items():
                if field in properties:
                    expected_type = properties[field].get("type")
                    if expected_type and not self._check_type(value, expected_type):
                        return {
                            "valid": False,
                            "error": f"参数 {field} 类型不匹配，期望: {expected_type}"
                        }
            
            return {"valid": True}
        except Exception as e:
            return {
                "valid": False,
                "error": f"参数验证异常: {str(e)}"
            }
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """检查值是否符合预期类型"""
        if expected_type == "string":
            return isinstance(value, str)
        elif expected_type == "integer":
            return isinstance(value, int)
        elif expected_type == "number":
            return isinstance(value, (int, float))
        elif expected_type == "boolean":
            return isinstance(value, bool)
        elif expected_type == "object":
            return isinstance(value, dict)
        elif expected_type == "array":
            return isinstance(value, list)
        return True  # 未知类型，允许通过
    
    def _execute_athena_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行Athena相关工具"""
        config = arguments.get("config", {})
        
        if tool_name == "athena_query":
            sql = arguments["sql"]
            database = arguments.get("database", "default")
            
            result = self.mcp_client.call_mcp_server_with_config(
                "athena",
                "execute_query",
                config,
                {"sql": sql, "database": database}
            )
            
            if "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "code": "QUERY_FAILED"
                }
            
            return {
                "success": True,
                "data": result.get("result", {}),
                "tool": tool_name,
                "execution_metadata": {
                    "database": database,
                    "query_length": len(sql)
                }
            }
        
        elif tool_name == "athena_describe_table":
            table_name = arguments["table_name"]
            database = arguments.get("database", "default")
            
            result = self.mcp_client.call_mcp_server_with_config(
                "athena",
                "describe_table",
                config,
                {"table_name": table_name, "database": database}
            )
            
            if "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "code": "DESCRIBE_FAILED"
                }
            
            return {
                "success": True,
                "columns": result.get("result", {}).get("columns", []),
                "tool": tool_name,
                "execution_metadata": {
                    "table": table_name,
                    "database": database
                }
            }
    
    def _execute_mysql_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行MySQL相关工具"""
        config = arguments.get("config", {})
        
        if tool_name == "mysql_query":
            sql = arguments["sql"]
            
            result = self.mcp_client.call_mcp_server_with_config(
                "mysql",
                "execute_query",
                config,
                {"sql": sql}
            )
            
            if "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "code": "QUERY_FAILED"
                }
            
            return {
                "success": True,
                "data": result.get("result", {}),
                "tool": tool_name,
                "execution_metadata": {
                    "query_length": len(sql),
                    "database": config.get("database", "unknown")
                }
            }
        
        elif tool_name == "mysql_describe_table":
            table_name = arguments["table_name"]
            
            result = self.mcp_client.call_mcp_server_with_config(
                "mysql",
                "describe_table",
                config,
                {"table_name": table_name}
            )
            
            if "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "code": "DESCRIBE_FAILED"
                }
            
            return {
                "success": True,
                "columns": result.get("result", {}).get("columns", []),
                "tool": tool_name,
                "execution_metadata": {
                    "table": table_name
                }
            }
    
    def _execute_web_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行Web相关工具"""
        
        if tool_name == "web_search":
            query = arguments["query"]
            max_results = arguments.get("max_results", 5)
            
            result = self.mcp_client.call_mcp_server(
                "playwright",
                "search_web",
                {"query": query, "max_results": max_results}
            )
            
            if "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "code": "SEARCH_FAILED"
                }
            
            return {
                "success": True,
                "results": result.get("result", []),
                "tool": tool_name,
                "search_metadata": {
                    "query": query,
                    "max_results": max_results
                }
            }
        
        elif tool_name == "web_fetch":
            url = arguments["url"]
            
            result = self.mcp_client.call_mcp_server(
                "playwright",
                "fetch_page",
                {"url": url}
            )
            
            if "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "code": "FETCH_FAILED"
                }
            
            return {
                "success": True,
                "content": result.get("result", {}),
                "tool": tool_name,
                "execution_metadata": {
                    "url": url
                }
            }
    
    def handle_llm_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        处理来自LLM的工具调用列表
        返回每个工具调用的结果
        """
        results = []
        
        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id", "")
            function_name = tool_call.get("function", {}).get("name", "")
            arguments_str = tool_call.get("function", {}).get("arguments", "{}")
            
            try:
                # 解析参数
                arguments = json.loads(arguments_str)
                
                # 执行工具调用
                result = self.execute_tool_call(function_name, arguments)
                
                # 构建响应
                tool_result = {
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                    "role": "tool"
                }
                
                results.append(tool_result)
                
            except json.JSONDecodeError as e:
                error_result = {
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({
                        "error": f"参数解析失败: {str(e)}",
                        "code": "INVALID_JSON"
                    }, ensure_ascii=False),
                    "role": "tool"
                }
                results.append(error_result)
            
            except Exception as e:
                error_result = {
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({
                        "error": f"工具调用异常: {str(e)}",
                        "code": "EXECUTION_ERROR"
                    }, ensure_ascii=False),
                    "role": "tool"
                }
                results.append(error_result)
        
        return results

# 创建全局工具调用处理器实例
mcp_tool_handler = MCPToolCallHandler()

def get_llm_tools() -> List[Dict[str, Any]]:
    """获取供LLM使用的工具定义"""
    return mcp_tool_handler.generate_tool_definitions_for_llm()

def handle_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """处理LLM工具调用"""
    return mcp_tool_handler.handle_llm_tool_calls(tool_calls)

if __name__ == "__main__":
    # 测试工具定义生成
    print("🔧 生成LLM工具定义")
    print("=" * 50)
    
    tools = get_llm_tools()
    for tool in tools:
        print(f"📋 {tool['function']['name']}")
        print(f"   📝 {tool['function']['description'][:100]}...")
        print()
    
    print(f"📊 总计: {len(tools)} 个工具可供LLM使用")