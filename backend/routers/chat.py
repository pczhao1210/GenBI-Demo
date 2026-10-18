from typing import Any, Dict, List, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from utils.bi_service import BIService
from utils.config_manager import ConfigManager
from utils.run_context import FrozenConfig, snapshot_config
from utils.run_store import utcnow

router = APIRouter()
DatabaseType = str


def scoped_service(profile_id):
    return BIService(config_manager=FrozenConfig(snapshot_config(ConfigManager(), profile_id)))


def resolve_query_definition(service, question, source):
    metrics = service.config.load_semantics().get("metrics", {})
    if not any(not metric.get("mappings") for metric in metrics.values()):
        return question
    sources = list(service.config.load_datasources()) if getattr(service.config, "snapshot", {}).get("profile") else [source]
    understanding = service.understand(question, source, {}, utcnow(), datasource_ids=sources)
    if understanding["clarification"]:
        raise ValueError("Clarification required: " + understanding["clarification"])
    if understanding["intent"] not in ("query", "analysis"):
        raise ValueError("A data query is required; use chat for business definition explanations")
    if understanding["requires_plan"]:
        raise ValueError("This definition requires multi-source planning; use /api/chat/analyze or chat")
    return understanding["normalized_question"]


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    database: DatabaseType = "mysql"
    datasource_id: str | None = None
    profile_id: str | None = None

    @property
    def source(self):
        return self.datasource_id or self.database


class GenerateSQLRequest(QueryRequest):
    database: DatabaseType = "athena"


class OptimizeChainRequest(BaseModel):
    original_chain: List[Dict[str, Any]] = Field(min_length=1)
    feedback: str = Field(min_length=1)
    database: DatabaseType = "athena"
    question: str = "Optimize the supplied analysis plan"
    profile_id: str | None = None


class ExecutePlanRequest(QueryRequest):
    plan: Dict[str, Any]


@router.post("/query")
def query_data(request: QueryRequest):
    service = scoped_service(request.profile_id)
    try:
        question = resolve_query_definition(service, request.question, request.source)
        return service.query(question, request.source)
    finally:
        service.close()


@router.post("/analyze")
def analyze_data(request: QueryRequest):
    service = scoped_service(request.profile_id)
    try:
        sources = list(service.config.load_datasources()) if request.profile_id else None
        plan = service.analysis_plan(request.question, request.source, datasource_ids=sources)
    finally:
        service.close()
    return {"intent": "analysis", "analysis_chain": plan["steps"], "plan": plan, "status": "pending"}


@router.post("/execute-plan")
def execute_plan(request: ExecutePlanRequest):
    return scoped_service(request.profile_id).execute_plan(request.plan, request.question, request.source)


@router.post("/optimize-chain")
def optimize_chain(request: OptimizeChainRequest):
    service = scoped_service(request.profile_id)
    try:
        plan = service.analysis_plan(
            request.question, request.database,
            previous_plan={"steps": request.original_chain}, feedback=request.feedback,
            datasource_ids=list(service.config.load_datasources()) if request.profile_id else None,
        )
    finally:
        service.close()
    return {"optimized_chain": plan["steps"], "plan": plan, "status": "optimized"}


@router.post("/generate-sql")
def generate_sql(request: GenerateSQLRequest):
    service = scoped_service(request.profile_id)
    try:
        question = resolve_query_definition(service, request.question, request.source)
        return {"sql": service.generate_sql(question, request.source), "success": True, "error": None}
    finally:
        service.close()
