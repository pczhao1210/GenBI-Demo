from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import sys
import os
# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    from utils.config_manager import ConfigManager
    from utils.llm_client import LLMClient
except ImportError:
    # 如果导入失败，尝试相对导入
    ConfigManager = None
    LLMClient = None

router = APIRouter()

class QueryRequest(BaseModel):
    question: str
    database: str

class AnalyzeRequest(BaseModel):
    question: str
    database: str

class OptimizeChainRequest(BaseModel):
    original_chain: List[Dict[str, Any]]
    feedback: str

class GenerateSQLRequest(BaseModel):
    question: str = Field(..., description="用户的查询问题", example="显示前10行数据")
    database: str = Field(default="athena", description="数据库类型，支持 mysql 或 athena", example="athena")

class GenerateSQLResponse(BaseModel):
    sql: Optional[str] = Field(None, description="生成的SQL语句", example="SELECT * FROM table_name LIMIT 10")
    success: bool = Field(..., description="是否成功生成SQL", example=True)
    error: Optional[str] = Field(None, description="错误信息（如果有）", example=None)

@router.post("/query")
async def query_data(request: QueryRequest):
    """处理查询请求"""
    return {
        "intent": "query",
        "question": request.question,
        "database": request.database,
        "tables": ["customers", "orders"],
        "sql": "SELECT * FROM customers LIMIT 100",
        "status": "success"
    }

@router.post("/analyze")
async def analyze_data(request: AnalyzeRequest):
    """处理分析请求"""
    return {
        "intent": "analysis",
        "question": request.question,
        "database": request.database,
        "analysis_chain": [
            {"step": 1, "action": "查询基础数据", "description": "获取相关表数据"},
            {"step": 2, "action": "数据清洗", "description": "处理异常值"},
            {"step": 3, "action": "趋势分析", "description": "计算趋势指标"}
        ],
        "status": "pending"
    }

@router.post("/optimize-chain")
async def optimize_chain(request: OptimizeChainRequest):
    """优化分析链"""
    return {
        "optimized_chain": request.original_chain,
        "feedback_applied": request.feedback,
        "status": "optimized"
    }

@router.post("/generate-sql", response_model=GenerateSQLResponse)
async def generate_sql(request: GenerateSQLRequest):
    """
    生成SQL查询语句
    
    根据用户的自然语言问题生成对应的SQL查询语句。
    
    - **question**: 用户的查询问题（例如："显示前10行数据"）
    - **database**: 数据库类型，支持 "mysql" 或 "athena"
    
    返回生成的SQL语句，方便系统集成使用。
    """
    try:
        if ConfigManager is None or LLMClient is None:
            raise HTTPException(status_code=500, detail="系统配置错误，无法加载必要模块")
            
        config_manager = ConfigManager()
        
        # 加载LLM配置
        llm_config = config_manager.load_llm_config()
        if not llm_config:
            raise HTTPException(status_code=400, detail="LLM配置未找到")
        
        # 加载Schema配置
        schema_config = config_manager.load_schema_config().get(request.database, {})
        if not schema_config:
            raise HTTPException(status_code=400, detail=f"{request.database.upper()}的Schema配置未找到")
        
        schema_info = schema_config.get("tables", {})
        table_descriptions = schema_config.get("descriptions", {})
        
        # 构建提示
        prompt = f"""数据库查询

用户问题: {request.question}

数据库Schema:
"""
        
        for table, columns in schema_info.items():
            table_desc = table_descriptions.get(table, "")
            prompt += f"\n\n表: {table}"
            if table_desc:
                prompt += f" - {table_desc}"
            prompt += "\n"
            
            if columns:
                prompt += "| 列名 | 类型 | 描述 |\n"
                prompt += "| --- | --- | --- |\n"
                for col in columns:
                    name = col.get("name", "")
                    col_type = col.get("type", "")
                    comment = col.get("comment", "")
                    prompt += f"| {name} | {col_type} | {comment} |\n"
        
        prompt += "\n\n请根据用户问题和数据库schema生成SQL查询。只返回SQL语句，不要其他内容。"
        
        # 调用LLM
        llm_client = LLMClient(llm_config)
        sql_response = llm_client.generate_sql(prompt)
        
        if not sql_response:
            return GenerateSQLResponse(sql=None, success=False, error="LLM生成SQL失败")
        
        # 提取SQL
        import re
        sql_match = re.search(r'```sql\s*([\s\S]*?)\s*```', sql_response)
        if sql_match:
            sql = sql_match.group(1).strip()
        else:
            sql_match = re.search(r'```\s*([\s\S]*?)\s*```', sql_response)
            if sql_match:
                sql = sql_match.group(1).strip()
            else:
                sql = sql_response.strip()
        
        return GenerateSQLResponse(sql=sql, success=True)
        
    except HTTPException:
        raise
    except Exception as e:
        return GenerateSQLResponse(sql=None, success=False, error=str(e))