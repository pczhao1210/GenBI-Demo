from typing import Any, Dict, List, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from utils.bi_service import BIService

router = APIRouter()
DatabaseType = Literal["mysql", "athena"]


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    database: DatabaseType


class GenerateSQLRequest(QueryRequest):
    database: DatabaseType = "athena"


class OptimizeChainRequest(BaseModel):
    original_chain: List[Dict[str, Any]] = Field(min_length=1)
    feedback: str = Field(min_length=1)
    database: DatabaseType = "athena"
    question: str = "Optimize the supplied analysis plan"


class ExecutePlanRequest(QueryRequest):
    plan: Dict[str, Any]


@router.post("/query")
def query_data(request: QueryRequest):
    return BIService().query(request.question, request.database)


@router.post("/analyze")
def analyze_data(request: QueryRequest):
    plan = BIService().analysis_plan(request.question, request.database)
    return {"intent": "analysis", "analysis_chain": plan["steps"], "plan": plan, "status": "pending"}


@router.post("/execute-plan")
def execute_plan(request: ExecutePlanRequest):
    return BIService().execute_plan(request.plan, request.question, request.database)


@router.post("/optimize-chain")
def optimize_chain(request: OptimizeChainRequest):
    plan = BIService().analysis_plan(
        request.question, request.database,
        previous_plan={"steps": request.original_chain}, feedback=request.feedback,
    )
    return {"optimized_chain": plan["steps"], "plan": plan, "status": "optimized"}


@router.post("/generate-sql")
def generate_sql(request: GenerateSQLRequest):
    return {"sql": BIService().generate_sql(request.question, request.database),
            "success": True, "error": None}
