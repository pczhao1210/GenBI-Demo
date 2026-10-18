from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response as DownloadResponse
from pydantic import BaseModel, Field

from utils.run_service import get_run_service
from utils.presentation import export_run

router = APIRouter()


class SubmitRun(BaseModel):
    question: str = Field(min_length=1)
    database: str = "mysql"
    session_id: str | None = None
    submission_id: str = Field(min_length=1)
    plan: dict[str, Any] | None = None
    datasource_ids: list[str] | None = None
    profile_id: str | None = None


class Response(BaseModel):
    request_id: str
    plan_version: int = Field(ge=1)
    response: str


class Revision(BaseModel):
    request_id: str
    plan_version: int = Field(ge=1)
    plan: dict[str, Any]


class Feedback(BaseModel):
    request_id: str
    plan_version: int = Field(ge=1)
    feedback: str = Field(min_length=1)


def require_run(run_id):
    service = get_run_service()
    try:
        service.store.get(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc
    return service


@router.post("")
def submit(request: SubmitRun):
    service = get_run_service()
    state = service.submit(**request.model_dump())
    service.start(state["run_id"])
    return state


@router.get("")
def history(session_id: str | None = None):
    return get_run_service().store.history(session_id)


@router.get("/history")
def history_page(session_id: str | None = None, before: int | None = Query(None, ge=1),
                 limit: int = Query(20, ge=1, le=100), database: str | None = None,
                 statuses: list[str] | None = Query(None), profile_id: str | None = None):
    return get_run_service().store.history_page(session_id, before, limit, database, statuses, profile_id)


@router.get("/{run_id}")
def snapshot(run_id: str):
    return require_run(run_id).store.get(run_id)


@router.get("/{run_id}/events")
def events(run_id: str, after: int = Query(0, ge=0)):
    return require_run(run_id).store.events(run_id, after)


@router.post("/{run_id}/responses")
def respond(run_id: str, request: Response):
    service = require_run(run_id)
    state = service.respond(run_id, **request.model_dump())
    service.start(run_id)
    return state


@router.post("/{run_id}/cancel")
def cancel(run_id: str):
    return require_run(run_id).cancel(run_id)


@router.post("/{run_id}/plan")
def revise(run_id: str, request: Revision):
    return require_run(run_id).revise(run_id, **request.model_dump())


@router.post("/{run_id}/plan/feedback")
def feedback(run_id: str, request: Feedback):
    return require_run(run_id).refine(run_id, **request.model_dump())


@router.post("/{run_id}/resume")
def resume(run_id: str):
    service = require_run(run_id)
    state = service.recover(run_id)
    service.start(run_id)
    return state


@router.post("/{run_id}/retry")
def retry(run_id: str, refresh: bool = False):
    service = require_run(run_id)
    state = service.retry(run_id, refresh)
    service.start(state["run_id"])
    return state


@router.get("/{run_id}/artifacts/{artifact_id}")
def artifact(run_id: str, artifact_id: str):
    try:
        return require_run(run_id).store.artifact(run_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(404, "Artifact not found") from exc


@router.get("/{run_id}/replay")
def replay(run_id: str):
    return require_run(run_id).store.replay(run_id)


@router.get("/{run_id}/export")
def export(run_id: str, format: str = "json", artifact_id: str | None = None):
    content, media, extension = export_run(require_run(run_id).store.replay(run_id), format, artifact_id)
    return DownloadResponse(content=content, media_type=media,
                            headers={"Content-Disposition": f'attachment; filename="{run_id}.{extension}"'})
