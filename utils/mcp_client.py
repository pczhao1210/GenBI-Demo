import json
import subprocess
import os
from typing import Dict, Any, List

class MCPClient:
    def __init__(self):
        self.processes = {}
        self.server_instances = {}
        self._server_info_cache = {}  # 缓存服务器信息
    
    def call_mcp_server(self, server_type: str, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """调用MCP服务器"""
        try:
            # 构建请求
            request = {
                "method": method,
                "params": params or {}
            }
            
            # 获取服务器路径 - 优先使用标准版本（已优化）
            use_optimized = params.get("use_optimized", False) if params else False
            if use_optimized and os.path.exists(os.path.join("mcp_servers", f"{server_type}_server_optimized.py")):
                server_path = os.path.join("mcp_servers", f"{server_type}_server_optimized.py")
            else:
                server_path = os.path.join("mcp_servers", f"{server_type}_server.py")
            
            # 启动进程 - 使用虚拟环境中的Python
            python_path = "/home/azureuser/Playground/GenBI-Demo/.venv/bin/python"
            if not os.path.exists(python_path):
                python_path = "python"  # 回退到系统Python
                
            process = subprocess.Popen(
                [python_path, server_path],
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
        
        # 获取服务器路径 - 优先使用标准版本（已优化）
        use_optimized = config.get("use_optimized", False)
        if use_optimized and os.path.exists(os.path.join("mcp_servers", f"{server_type}_server_optimized.py")):
            server_path = os.path.join("mcp_servers", f"{server_type}_server_optimized.py")
        else:
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
    
    def get_server_info(self, server_type: str) -> Dict[str, Any]:
        """获取MCP服务器信息"""
        # 检查缓存
        if server_type in self._server_info_cache:
            return self._server_info_cache[server_type]
        
        # 调用服务器获取信息
        result = self.call_mcp_server(server_type, "get_server_info")
        
        if "result" in result:
            # 缓存结果
            self._server_info_cache[server_type] = result["result"]
            return result["result"]
        
        return {"error": f"无法获取服务器 {server_type} 的信息"}
    
    def discover_available_servers(self) -> Dict[str, Dict[str, Any]]:
        """发现可用的MCP服务器"""
        import os
        server_info = {}
        
        # 扫描mcp_servers目录
        mcp_servers_dir = "mcp_servers"
        if os.path.exists(mcp_servers_dir):
            for file in os.listdir(mcp_servers_dir):
                if file.endswith("_server.py") and not file.startswith("__"):
                    server_name = file.replace("_server.py", "")
                    try:
                        info = self.get_server_info(server_name)
                        if "error" not in info:
                            server_info[server_name] = info
                    except Exception as e:
                        server_info[server_name] = {
                            "name": server_name,
                            "error": f"无法获取服务器信息: {str(e)}",
                            "status": "unavailable"
                        }
        
        return server_info