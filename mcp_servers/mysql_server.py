#!/usr/bin/env python3
"""
MySQL MCP Server
提供MySQL查询功能的MCP工具服务器
"""

import json
import sys
import pymysql
from typing import Dict, Any, List

class MySQLServer:
    def __init__(self):
        self.connection = None
        self.config = {}
    
    def initialize(self, config: Dict[str, Any]):
        """初始化MySQL连接"""
        self.config = config
        try:
            self.connection = pymysql.connect(
                host=config.get('host', 'localhost'),
                port=config.get('port', 3306),
                user=config.get('username'),
                password=config.get('password'),
                database=config.get('database'),
                charset='utf8mb4'
            )
        except Exception as e:
            raise Exception(f"MySQL连接失败: {str(e)}")
    
    def execute_query(self, sql: str) -> Dict[str, Any]:
        """执行MySQL查询"""
        if not self.connection:
            return {"error": "MySQL连接未初始化"}
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql)
                
                if sql.strip().upper().startswith('SELECT'):
                    # 查询操作
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    
                    # 应用行数限制
                    max_rows = self.config.get('max_rows', 100)
                    if len(rows) > max_rows:
                        rows = rows[:max_rows]
                    
                    # 转换为列表格式
                    formatted_rows = [list(row) for row in rows]
                    
                    return {
                        "success": True,
                        "data": {
                            "columns": columns,
                            "rows": formatted_rows,
                            "row_count": len(formatted_rows)
                        }
                    }
                else:
                    # 非查询操作
                    self.connection.commit()
                    return {
                        "success": True,
                        "affected_rows": cursor.rowcount
                    }
                    
        except Exception as e:
            return {"error": f"执行查询时出错: {str(e)}"}
    
    def get_tables(self) -> Dict[str, Any]:
        """获取数据库表列表"""
        try:
            result = self.execute_query("SHOW TABLES")
            if result.get("success"):
                tables = [row[0] for row in result["data"]["rows"]]
                return {"success": True, "tables": tables}
            else:
                return result
        except Exception as e:
            return {"error": f"获取表列表时出错: {str(e)}"}
    
    def describe_table(self, table_name: str) -> Dict[str, Any]:
        """获取表结构"""
        try:
            result = self.execute_query(f"DESCRIBE {table_name}")
            if result.get("success"):
                columns = []
                for row in result["data"]["rows"]:
                    columns.append({
                        "name": row[0],
                        "type": row[1],
                        "null": row[2],
                        "key": row[3],
                        "default": row[4],
                        "extra": row[5]
                    })
                
                return {"success": True, "columns": columns}
            else:
                return result
        except Exception as e:
            return {"error": f"获取表结构时出错: {str(e)}"}

def handle_mcp_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """处理MCP请求"""
    server = MySQLServer()
    
    method = request.get("method")
    params = request.get("params", {})
    
    # 如果请求中包含配置信息，先初始化服务器
    if "config" in params:
        try:
            server.initialize(params.get("config", {}))
        except Exception as e:
            return {"error": str(e)}
    
    if method == "initialize":
        return {"result": {"success": True, "message": "MySQL服务器初始化成功"}}
    
    elif method == "execute_query":
        return {"result": server.execute_query(params.get("sql"))}
    
    elif method == "get_tables":
        return {"result": server.get_tables()}
    
    elif method == "describe_table":
        return {"result": server.describe_table(params.get("table_name"))}
    
    else:
        return {"error": f"未知方法: {method}"}

def main():
    """MCP服务器主循环"""
    print("MySQL MCP Server 启动中...", file=sys.stderr)
    
    for line in sys.stdin:
        try:
            request = json.loads(line.strip())
            response = handle_mcp_request(request)
            print(json.dumps(response))
            sys.stdout.flush()
        except json.JSONDecodeError:
            print(json.dumps({"error": "无效的JSON请求"}))
        except Exception as e:
            print(json.dumps({"error": f"处理请求时出错: {str(e)}"}))

if __name__ == "__main__":
    main()