import json
import subprocess
import os
from typing import Dict, Any, List

class MCPClient:
    def __init__(self):
        self.processes = {}
        self.server_instances = {}
    
    def call_mcp_server(self, server_type: str, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """调用MCP服务器"""
        try:
            # 构建请求
            request = {
                "method": method,
                "params": params or {}
            }
            
            # 获取服务器路径
            server_path = os.path.join("mcp_servers", f"{server_type}_server.py")
            
            # 启动进程
            process = subprocess.Popen(
                ["python", server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 发送请求
            stdout, stderr = process.communicate(json.dumps(request) + "\n")
            
            if process.returncode == 0:
                try:
                    return json.loads(stdout.strip())
                except json.JSONDecodeError as e:
                    return {"error": f"无法解析MCP服务器响应: {stdout}"}
            else:
                return {"error": f"MCP服务器错误: {stderr}"}
                
        except Exception as e:
            return {"error": f"调用MCP服务器失败: {str(e)}"}
    
    def call_mcp_server_with_config(self, server_type: str, method: str, config: Dict[str, Any], params: Dict[str, Any] = None) -> Dict[str, Any]:
        """调用MCP服务器，并在同一请求中包含配置信息"""
        # 合并参数
        full_params = params or {}
        full_params["config"] = config
        
        # 构建请求
        request = {
            "method": method,
            "params": full_params
        }
        
        # 获取服务器路径
        server_path = os.path.join("mcp_servers", f"{server_type}_server.py")
        
        try:
            # 启动进程
            process = subprocess.Popen(
                ["python", server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 发送请求
            stdout, stderr = process.communicate(json.dumps(request) + "\n")
            
            if process.returncode == 0:
                try:
                    return json.loads(stdout.strip())
                except json.JSONDecodeError as e:
                    return {"error": f"无法解析MCP服务器响应: {stdout}"}
            else:
                return {"error": f"MCP服务器错误: {stderr}"}
                
        except Exception as e:
            return {"error": f"调用MCP服务器失败: {str(e)}"}
    
    def get_tables(self, database_type: str, config: Dict[str, Any]) -> List[str]:
        """获取数据库表列表"""
        # 在同一请求中初始化并获取表
        result = self.call_mcp_server_with_config(database_type, "get_tables", config, {"database": config.get("database", "default")})
        if "result" in result and isinstance(result["result"], dict) and "success" in result["result"] and result["result"]["success"]:
            return result["result"].get("tables", [])
        return []
    
    def describe_table(self, database_type: str, config: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        """获取表结构"""
        # 在同一请求中初始化并获取表结构
        result = self.call_mcp_server_with_config(
            database_type, 
            "describe_table", 
            config, 
            {"table_name": table_name, "database": config.get("database", "default")}
        )
        if "result" in result and isinstance(result["result"], dict) and "success" in result["result"] and result["result"]["success"]:
            return result["result"].get("columns", [])
        return []