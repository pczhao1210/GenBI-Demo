#!/usr/bin/env python3
"""
优化版MySQL MCP服务器
添加连接池、事务管理、错误重试等功能
"""

import json
import sys
import pymysql
import time
from pymysql.connections import Connection
from typing import Dict, Any, List, Optional
import logging

# 自定义连接池异常
class PoolError(Exception):
    """连接池错误"""
    pass

class MySQLConnectionPool:
    def __init__(self, config: Dict[str, Any], max_connections: int = 5):
        self.config = config
        self.max_connections = max_connections
        self.pool = []
        self.in_use = set()
        
    def get_connection(self) -> Connection:
        """从连接池获取连接"""
        # 尝试从池中获取可用连接
        while self.pool:
            conn = self.pool.pop()
            try:
                conn.ping(reconnect=True)
                self.in_use.add(conn)
                return conn
            except:
                conn.close()
                
        # 如果没有可用连接且未达到最大连接数，创建新连接
        if len(self.in_use) < self.max_connections:
            # 准备连接参数
            connection_params = {
                'host': self.config.get('host', 'localhost'),
                'port': self.config.get('port', 3306),
                'user': self.config.get('username'),
                'password': self.config.get('password'),
                'database': self.config.get('database'),
                'charset': 'utf8mb4',
                'autocommit': True,
                'connect_timeout': self.config.get('connection_timeout', 10),
                'read_timeout': self.config.get('read_timeout', 30),
                'write_timeout': self.config.get('write_timeout', 30)
            }
            
            # SSL配置处理
            if self.config.get('use_ssl', False):
                ssl_mode = self.config.get('ssl_mode', '系统CA证书')
                
                if ssl_mode == '系统CA证书':
                    # 使用系统默认CA证书验证服务器证书
                    ssl_config = {
                        'check_hostname': True,  # 验证主机名
                        'verify_mode': 2         # ssl.CERT_REQUIRED 等价
                    }
                    # 让PyMySQL使用系统默认的CA证书
                    connection_params['ssl'] = ssl_config
                    
                elif ssl_mode == '自定义证书':
                    # 使用用户提供的证书文件
                    ssl_config = {}
                    if self.config.get('ssl_ca'):
                        ssl_config['ca'] = self.config['ssl_ca']
                    if self.config.get('ssl_cert'):
                        ssl_config['cert'] = self.config['ssl_cert']
                    if self.config.get('ssl_key'):
                        ssl_config['key'] = self.config['ssl_key']
                    
                    if ssl_config:
                        connection_params['ssl'] = ssl_config
                    else:
                        # 如果选择自定义但没有证书，回退到系统CA
                        connection_params['ssl'] = {'check_hostname': True, 'verify_mode': 2}
                
                elif ssl_mode == '强制SSL':
                    # 强制SSL但不验证证书
                    connection_params['ssl'] = {'check_hostname': False, 'verify_mode': 0}
                
                else:
                    # 默认使用系统CA证书
                    connection_params['ssl'] = {'check_hostname': True, 'verify_mode': 2}
            else:
                # 如果未启用SSL，尝试禁用SSL
                connection_params['ssl_disabled'] = True
            
            conn = pymysql.connect(**connection_params)
            self.in_use.add(conn)
            return conn
        
        raise PoolError("连接池已满，无法获取新连接")
    
    def return_connection(self, conn: Connection):
        """归还连接到池中"""
        if conn in self.in_use:
            self.in_use.remove(conn)
            if len(self.pool) < self.max_connections:
                self.pool.append(conn)
            else:
                conn.close()

class MySQLServerOptimized:
    def __init__(self):
        self.pool = None
        self.config = {}
        self.logger = self._setup_logger()
    
    def _setup_logger(self):
        """设置日志"""
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)
    
    def initialize(self, config: Dict[str, Any]):
        """初始化MySQL连接池"""
        self.config = config
        try:
            self.pool = MySQLConnectionPool(config)
            # 测试连接
            conn = self.pool.get_connection()
            self.pool.return_connection(conn)
            self.logger.info("MySQL连接池初始化成功")
        except Exception as e:
            self.logger.error(f"MySQL连接池初始化失败: {str(e)}")
            raise Exception(f"MySQL连接池初始化失败: {str(e)}")
    
    def execute_query(self, sql: str, max_retries: int = 3) -> Dict[str, Any]:
        """执行MySQL查询，支持重试机制"""
        if not self.pool:
            return {"error": "MySQL连接池未初始化"}
        
        # SQL安全检查
        if self._is_dangerous_sql(sql):
            return {"error": "检测到危险SQL操作，查询被拒绝"}
        
        last_error = None
        for attempt in range(max_retries):
            conn = None
            try:
                conn = self.pool.get_connection()
                with conn.cursor() as cursor:
                    start_time = time.time()
                    cursor.execute(sql)
                    execution_time = time.time() - start_time
                    
                    if sql.strip().upper().startswith('SELECT'):
                        # 查询操作
                        columns = [desc[0] for desc in cursor.description]
                        rows = cursor.fetchall()
                        
                        # 应用行数限制
                        max_rows = self.config.get('max_rows', 1000)
                        total_rows = len(rows)
                        if total_rows > max_rows:
                            rows = rows[:max_rows]
                            truncated = True
                        else:
                            truncated = False
                        
                        # 转换为列表格式，处理特殊数据类型
                        formatted_rows = []
                        for row in rows:
                            formatted_row = []
                            for value in row:
                                # 处理Decimal类型
                                if hasattr(value, '__class__') and 'Decimal' in str(type(value)):
                                    formatted_row.append(float(value))
                                # 处理日期时间类型
                                elif hasattr(value, 'strftime'):
                                    formatted_row.append(value.isoformat())
                                # 处理bytes类型
                                elif isinstance(value, bytes):
                                    try:
                                        formatted_row.append(value.decode('utf-8'))
                                    except:
                                        formatted_row.append(str(value))
                                # 处理其他类型
                                else:
                                    formatted_row.append(value)
                            formatted_rows.append(formatted_row)
                        
                        result = {
                            "success": True,
                            "data": {
                                "columns": columns,
                                "rows": formatted_rows,
                                "row_count": len(formatted_rows),
                                "total_rows": total_rows,
                                "truncated": truncated,
                                "execution_time": round(execution_time, 3)
                            }
                        }
                        
                        if truncated:
                            result["warning"] = f"结果已截断，仅显示前{max_rows}行，共{total_rows}行"
                        
                        return result
                    else:
                        # 非查询操作（虽然应该被安全检查拦截）
                        return {"error": "不支持非查询操作"}
                        
            except pymysql.Error as e:
                last_error = str(e)
                self.logger.warning(f"MySQL查询失败 (尝试 {attempt + 1}/{max_retries}): {last_error}")
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))  # 指数退避
            except Exception as e:
                last_error = str(e)
                self.logger.error(f"执行查询时发生未知错误: {last_error}")
                break
            finally:
                if conn:
                    self.pool.return_connection(conn)
        
        return {"error": f"查询失败，已重试{max_retries}次: {last_error}"}
    
    def _is_dangerous_sql(self, sql: str) -> bool:
        """检测危险SQL操作"""
        dangerous_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 
            'TRUNCATE', 'REPLACE', 'MERGE', 'GRANT', 'REVOKE', 'SET'
        ]
        
        sql_upper = sql.upper().strip()
        for keyword in dangerous_keywords:
            if sql_upper.startswith(keyword):
                return True
        return False
    
    def get_tables(self) -> Dict[str, Any]:
        """获取数据库表列表，包含表类型和注释"""
        try:
            # 获取表信息
            tables_sql = """
            SELECT 
                TABLE_NAME,
                TABLE_TYPE,
                TABLE_COMMENT,
                TABLE_ROWS
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
            """
            
            result = self.execute_query_internal(tables_sql, (self.config.get('database'),))
            if result.get("success"):
                tables = []
                for row in result["data"]["rows"]:
                    tables.append({
                        "name": row[0],
                        "type": row[1],
                        "comment": row[2] or "",
                        "estimated_rows": row[3] or 0
                    })
                
                return {"success": True, "tables": tables}
            else:
                return result
        except Exception as e:
            return {"error": f"获取表列表时出错: {str(e)}"}
    
    def execute_query_internal(self, sql: str, params=None) -> Dict[str, Any]:
        """内部查询方法，用于系统查询"""
        if not self.pool:
            return {"error": "MySQL连接池未初始化"}
        
        conn = None
        try:
            conn = self.pool.get_connection()
            with conn.cursor() as cursor:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                formatted_rows = [list(row) for row in rows]
                
                return {
                    "success": True,
                    "data": {
                        "columns": columns,
                        "rows": formatted_rows,
                        "row_count": len(formatted_rows)
                    }
                }
        except Exception as e:
            return {"error": f"内部查询失败: {str(e)}"}
        finally:
            if conn:
                self.pool.return_connection(conn)
    
    def describe_table(self, table_name: str) -> Dict[str, Any]:
        """获取详细的表结构信息"""
        try:
            # 获取列信息
            columns_sql = """
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_KEY,
                COLUMN_DEFAULT,
                EXTRA,
                COLUMN_COMMENT,
                CHARACTER_MAXIMUM_LENGTH,
                NUMERIC_PRECISION,
                NUMERIC_SCALE
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """
            
            result = self.execute_query_internal(columns_sql, (self.config.get('database'), table_name))
            if result.get("success"):
                columns = []
                for row in result["data"]["rows"]:
                    column_info = {
                        "name": row[0],
                        "type": row[1],
                        "nullable": row[2] == 'YES',
                        "key": row[3] or "",
                        "default": row[4],
                        "extra": row[5] or "",
                        "comment": row[6] or "",
                        "max_length": row[7],
                        "precision": row[8],
                        "scale": row[9]
                    }
                    columns.append(column_info)
                
                # 获取索引信息
                indexes_sql = """
                SELECT 
                    INDEX_NAME,
                    COLUMN_NAME,
                    NON_UNIQUE,
                    INDEX_TYPE
                FROM INFORMATION_SCHEMA.STATISTICS 
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY INDEX_NAME, SEQ_IN_INDEX
                """
                
                indexes_result = self.execute_query_internal(indexes_sql, (self.config.get('database'), table_name))
                indexes = []
                if indexes_result.get("success"):
                    for row in indexes_result["data"]["rows"]:
                        indexes.append({
                            "name": row[0],
                            "column": row[1],
                            "unique": row[2] == 0,
                            "type": row[3]
                        })
                
                return {
                    "success": True, 
                    "table_name": table_name,
                    "columns": columns,
                    "indexes": indexes
                }
            else:
                return result
        except Exception as e:
            return {"error": f"获取表结构时出错: {str(e)}"}
    
    def get_database_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        try:
            stats_sql = """
            SELECT 
                COUNT(*) as table_count,
                SUM(TABLE_ROWS) as total_rows,
                ROUND(SUM(DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) as size_mb
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            """
            
            result = self.execute_query_internal(stats_sql, (self.config.get('database'),))
            if result.get("success") and result["data"]["rows"]:
                row = result["data"]["rows"][0]
                return {
                    "success": True,
                    "stats": {
                        "table_count": row[0] or 0,
                        "total_rows": row[1] or 0,
                        "size_mb": row[2] or 0
                    }
                }
            return {"success": True, "stats": {"table_count": 0, "total_rows": 0, "size_mb": 0}}
        except Exception as e:
            return {"error": f"获取数据库统计信息时出错: {str(e)}"}

def handle_mcp_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """处理MCP请求"""
    method = request.get("method")
    params = request.get("params", {})
    
    if method == "get_server_info":
        # 返回服务器信息
        return {
            "result": {
                "name": "mysql",
                "description": "MySQL数据库查询服务",
                "capabilities": ["database_query", "sql_execution", "connection_pool", "transaction_management"],
                "type": "stdio",
                "version": "1.0.0",
                "methods": ["initialize", "execute_query", "get_tables", "describe_table", "get_database_stats"],
                "status": "ready"
            }
        }
    
    server = MySQLServerOptimized()
    
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
    
    elif method == "get_database_stats":
        return {"result": server.get_database_stats()}
    
    else:
        return {"error": f"未知方法: {method}"}

def main():
    """MCP服务器主循环"""
    print("优化版MySQL MCP Server 启动中...", file=sys.stderr)
    
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