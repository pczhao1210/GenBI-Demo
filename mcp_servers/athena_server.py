#!/usr/bin/env python3
"""
AWS Athena MCP Server
提供Athena查询功能的MCP工具服务器
"""

import json
import sys
import boto3
import pandas as pd
from typing import Dict, Any, List
import time

class AthenaServer:
    def __init__(self):
        self.client = None
        self.config = {}
    
    def initialize(self, config: Dict[str, Any]):
        """初始化Athena客户端"""
        self.config = config
        self.client = boto3.client(
            'athena',
            region_name=config.get('region', 'us-east-1'),
            aws_access_key_id=config.get('aws_access_key_id'),
            aws_secret_access_key=config.get('aws_secret_access_key')
        )
    
    def execute_query(self, sql: str, database: str = None) -> Dict[str, Any]:
        """执行Athena查询"""
        if not self.client:
            return {"error": "Athena客户端未初始化"}
        
        try:
            # 打印调试信息
            print(f"执行查询: {sql} (数据库: {database})", file=sys.stderr)
            
            # 构建查询参数
            query_params = {
                'QueryString': sql,
                'QueryExecutionContext': {
                    'Database': database or 'default'
                }
            }
            
            # 只有当s3_output_location被明确设置时才添加ResultConfiguration
            s3_output = self.config.get('s3_output_location')
            if s3_output:
                query_params['ResultConfiguration'] = {
                    'OutputLocation': s3_output
                }
            
            # 打印查询参数
            print(f"查询参数: {query_params}", file=sys.stderr)
            
            # 启动查询
            response = self.client.start_query_execution(**query_params)
            
            query_id = response['QueryExecutionId']
            print(f"查询ID: {query_id}", file=sys.stderr)
            
            # 等待查询完成
            while True:
                result = self.client.get_query_execution(QueryExecutionId=query_id)
                status = result['QueryExecution']['Status']['State']
                print(f"查询状态: {status}", file=sys.stderr)
                
                if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                    break
                time.sleep(1)
            
            if status == 'SUCCEEDED':
                # 获取查询结果
                results = self.client.get_query_results(QueryExecutionId=query_id)
                
                # 转换为DataFrame格式
                columns = [col['Label'] for col in results['ResultSet']['ResultSetMetadata']['ColumnInfo']]
                print(f"列名: {columns}", file=sys.stderr)
                
                rows = []
                all_rows = results['ResultSet']['Rows']
                
                # 如果有数据行
                if len(all_rows) > 0:
                    # 如果第一行是标题行，则从第二行开始
                    data_rows = all_rows[1:] if len(all_rows) > 1 else []
                    for row in data_rows:
                        row_data = [cell.get('VarCharValue', '') for cell in row['Data']]
                        rows.append(row_data)
                
                # 应用行数限制
                max_rows = self.config.get('max_rows', 100)
                if len(rows) > max_rows:
                    rows = rows[:max_rows]
                
                print(f"查询结果行数: {len(rows)}", file=sys.stderr)
                
                return {
                    "success": True,
                    "data": {
                        "columns": columns,
                        "rows": rows,
                        "row_count": len(rows),
                        "query_id": query_id
                    }
                }
            else:
                error_reason = result['QueryExecution']['Status'].get('StateChangeReason', '未知错误')
                print(f"查询失败原因: {error_reason}", file=sys.stderr)
                return {"error": f"查询失败: {error_reason}"}
                
        except Exception as e:
            print(f"查询异常: {str(e)}", file=sys.stderr)
            return {"error": f"执行查询时出错: {str(e)}"}
    
    def get_tables(self, database: str = 'default') -> Dict[str, Any]:
        """获取数据库表列表"""
        try:
            # 如果没有客户端，返回错误
            if not self.client:
                return {"error": "Athena客户端未初始化"}
            
            # 尝试两种方式获取表列表
            tables = []
            
            # 方式1: 使用SHOW TABLES命令
            try:
                # 构建查询参数
                query_params = {
                    'QueryString': f"SHOW TABLES IN {database}",
                    'QueryExecutionContext': {
                        'Database': database
                    }
                }
                
                # 只有当s3_output_location被明确设置时才添加ResultConfiguration
                s3_output = self.config.get('s3_output_location')
                if s3_output:
                    query_params['ResultConfiguration'] = {
                        'OutputLocation': s3_output
                    }
                
                # 启动查询
                response = self.client.start_query_execution(**query_params)
                query_id = response['QueryExecutionId']
                
                # 等待查询完成
                while True:
                    result = self.client.get_query_execution(QueryExecutionId=query_id)
                    status = result['QueryExecution']['Status']['State']
                    
                    if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                        break
                    time.sleep(1)
                
                if status == 'SUCCEEDED':
                    # 获取查询结果
                    results = self.client.get_query_results(QueryExecutionId=query_id)
                    
                    # 转换为DataFrame格式
                    rows = []
                    all_rows = results['ResultSet']['Rows']
                    
                    # 检查是否有标题行
                    if len(all_rows) > 0:
                        # 如果第一行是标题行，则从第二行开始
                        data_rows = all_rows[1:] if len(all_rows) > 1 else []
                        for row in data_rows:
                            row_data = [cell.get('VarCharValue', '') for cell in row['Data']]
                            rows.append(row_data)
                    
                    # 打印调试信息
                    print(f"SHOW TABLES查询结果: {rows}", file=sys.stderr)
                    
                    # 提取表名
                    for row in rows:
                        if row and len(row) > 0:
                            tables.append(row[0])
            except Exception as e:
                print(f"SHOW TABLES命令失败: {str(e)}", file=sys.stderr)
            
            # 方式2: 尝试直接查询数据库同名表
            if not tables:
                try:
                    # 尝试查询数据库同名表
                    query_params = {
                        'QueryString': f"SELECT * FROM {database} LIMIT 1",
                        'QueryExecutionContext': {
                            'Database': database
                        }
                    }
                    
                    if s3_output:
                        query_params['ResultConfiguration'] = {
                            'OutputLocation': s3_output
                        }
                    
                    response = self.client.start_query_execution(**query_params)
                    query_id = response['QueryExecutionId']
                    
                    while True:
                        result = self.client.get_query_execution(QueryExecutionId=query_id)
                        status = result['QueryExecution']['Status']['State']
                        
                        if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                            break
                        time.sleep(1)
                    
                    if status == 'SUCCEEDED':
                        # 如果查询成功，说明表存在
                        tables.append(database)
                        print(f"数据库同名表存在: {database}", file=sys.stderr)
                except Exception as e:
                    print(f"查询数据库同名表失败: {str(e)}", file=sys.stderr)
            
            # 方式3: 尝试查询defects表
            if not tables:
                try:
                    # 尝试查询defects表
                    query_params = {
                        'QueryString': "SELECT * FROM defects LIMIT 1",
                        'QueryExecutionContext': {
                            'Database': database
                        }
                    }
                    
                    if s3_output:
                        query_params['ResultConfiguration'] = {
                            'OutputLocation': s3_output
                        }
                    
                    response = self.client.start_query_execution(**query_params)
                    query_id = response['QueryExecutionId']
                    
                    while True:
                        result = self.client.get_query_execution(QueryExecutionId=query_id)
                        status = result['QueryExecution']['Status']['State']
                        
                        if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                            break
                        time.sleep(1)
                    
                    if status == 'SUCCEEDED':
                        # 如果查询成功，说明表存在
                        tables.append('defects')
                        print("表defects存在", file=sys.stderr)
                except Exception as e:
                    print(f"查询defects表失败: {str(e)}", file=sys.stderr)
            
            return {"success": True, "tables": tables}
                
        except Exception as e:
            return {"error": f"获取表列表时出错: {str(e)}"}
    
    def describe_table(self, table_name: str, database: str = 'default') -> Dict[str, Any]:
        """获取表结构"""
        try:
            # 如果没有客户端，返回错误
            if not self.client:
                return {"error": "Athena客户端未初始化"}
            
            print(f"尝试获取表结构: {table_name} (数据库: {database})", file=sys.stderr)
            
            # 方式1: 使用DESCRIBE命令
            columns = []
            try:
                # 构建查询参数
                query_params = {
                    'QueryString': f"DESCRIBE {database}.{table_name}",
                    'QueryExecutionContext': {
                        'Database': database
                    }
                }
                
                # 只有当s3_output_location被明确设置时才添加ResultConfiguration
                s3_output = self.config.get('s3_output_location')
                if s3_output:
                    query_params['ResultConfiguration'] = {
                        'OutputLocation': s3_output
                    }
                
                print(f"查询参数: {query_params}", file=sys.stderr)
                
                # 启动查询
                response = self.client.start_query_execution(**query_params)
                query_id = response['QueryExecutionId']
                
                # 等待查询完成
                while True:
                    result = self.client.get_query_execution(QueryExecutionId=query_id)
                    status = result['QueryExecution']['Status']['State']
                    print(f"查询状态: {status}", file=sys.stderr)
                    
                    if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                        break
                    time.sleep(1)
                
                if status == 'SUCCEEDED':
                    # 获取查询结果
                    results = self.client.get_query_results(QueryExecutionId=query_id)
                    
                    # 转换为DataFrame格式
                    rows = []
                    all_rows = results['ResultSet']['Rows']
                    
                    # 检查是否有标题行
                    if len(all_rows) > 0:
                        # 如果第一行是标题行，则从第二行开始
                        data_rows = all_rows[1:] if len(all_rows) > 1 else []
                        for row in data_rows:
                            row_data = [cell.get('VarCharValue', '') for cell in row['Data']]
                            rows.append(row_data)
                    
                    print(f"查询结果行数: {len(rows)}", file=sys.stderr)
                    
                    for row in rows:
                        if len(row) >= 2:
                            columns.append({
                                "name": row[0],
                                "type": row[1],
                                "comment": row[2] if len(row) > 2 else ""
                            })
                else:
                    error_reason = result['QueryExecution']['Status'].get('StateChangeReason', '未知错误')
                    print(f"查询失败原因: {error_reason}", file=sys.stderr)
            except Exception as e:
                print(f"DESCRIBE命令失败: {str(e)}", file=sys.stderr)
            
            # 方式2: 如果上面失败，尝试直接查询表并获取列信息
            if not columns:
                try:
                    print("尝试直接查询表获取列信息", file=sys.stderr)
                    
                    # 构建查询参数
                    query_params = {
                        'QueryString': f"SELECT * FROM {table_name} LIMIT 1",
                        'QueryExecutionContext': {
                            'Database': database
                        }
                    }
                    
                    if s3_output:
                        query_params['ResultConfiguration'] = {
                            'OutputLocation': s3_output
                        }
                    
                    # 启动查询
                    response = self.client.start_query_execution(**query_params)
                    query_id = response['QueryExecutionId']
                    
                    # 等待查询完成
                    while True:
                        result = self.client.get_query_execution(QueryExecutionId=query_id)
                        status = result['QueryExecution']['Status']['State']
                        
                        if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                            break
                        time.sleep(1)
                    
                    if status == 'SUCCEEDED':
                        # 获取查询结果
                        results = self.client.get_query_results(QueryExecutionId=query_id)
                        
                        # 从元数据中提取列信息
                        column_info = results['ResultSet']['ResultSetMetadata']['ColumnInfo']
                        
                        for col in column_info:
                            columns.append({
                                "name": col['Label'],
                                "type": col['Type'],
                                "comment": ""
                            })
                        
                        print(f"从查询结果中提取到 {len(columns)} 个列", file=sys.stderr)
                except Exception as e:
                    print(f"直接查询表失败: {str(e)}", file=sys.stderr)
            
            if columns:
                return {"success": True, "columns": columns}
            else:
                return {"error": "无法获取表结构"}
                
        except Exception as e:
            return {"error": f"获取表结构时出错: {str(e)}"}

def handle_mcp_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """处理MCP请求"""
    method = request.get("method")
    params = request.get("params", {})
    
    if method == "get_server_info":
        # 返回服务器信息
        return {
            "result": {
                "name": "athena",
                "description": "AWS Athena数据库查询服务",
                "capabilities": ["database_query", "sql_execution", "data_analysis"],
                "type": "stdio",
                "version": "1.0.0",
                "methods": ["initialize", "execute_query", "get_tables", "describe_table"],
                "status": "ready"
            }
        }
    
    elif method == "initialize":
        server = AthenaServer()
        config = params.get("config", {})
        server.initialize(config)
        
        return {"success": True, "initialized": True}
    
    elif method == "execute_query":
        server = AthenaServer()
        config = params.get("config", {})
        server.initialize(config)
        
        return {"result": server.execute_query(
            params.get("sql"), 
            params.get("database", "default")
        )}
    
    elif method == "get_tables":
        server = AthenaServer()
        config = params.get("config", {})
        server.initialize(config)
        
        return {"result": server.get_tables(params.get("database", "default"))}
    
    elif method == "describe_table":
        server = AthenaServer()
        config = params.get("config", {})
        server.initialize(config)
        
        return {"result": server.describe_table(
            params.get("table_name"),
            params.get("database", "default")
        )}
    
    else:
        return {"error": f"未知方法: {method}"}

def main():
    """MCP服务器主循环"""
    print("Athena MCP Server 启动中...", file=sys.stderr)
    
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