from typing import Any

from fastapi import APIRouter

from utils.config_manager import ConfigManager
from utils.semantics import KnowledgeIndex
from utils.resource_scope import ScopedConfig
from utils.knowledge_center import catalog_entries, preview_knowledge

router = APIRouter()


@router.get("/catalog")
def catalog(profile_id: str | None = None):
    return [{key: value for key, value in entry.items() if key != "record"}
            for entry in catalog_entries(ScopedConfig(ConfigManager(), profile_id))]


@router.get("/preview")
def preview(q: str, stage: str = "understanding", profile_id: str | None = None):
    if not q.strip():
        raise ValueError("Enter a question to preview knowledge retrieval")
    return preview_knowledge(ScopedConfig(ConfigManager(), profile_id), q, stage)


@router.get("/ontology")
def ontology(profile_id: str | None = None):
    return ScopedConfig(ConfigManager(), profile_id).load_semantics()


@router.put("/ontology")
def save_ontology(value: dict[str, Any], profile_id: str | None = None):
    ScopedConfig(ConfigManager(), profile_id).save_semantics(value)
    return {"status": "saved"}


@router.get("/knowledge")
def knowledge(profile_id: str | None = None):
    return ScopedConfig(ConfigManager(), profile_id).load_knowledge()


@router.put("/knowledge")
def save_knowledge(value: dict[str, Any], profile_id: str | None = None):
    ScopedConfig(ConfigManager(), profile_id).save_knowledge(value)
    return {"status": "saved"}


@router.get("/search")
def search(q: str, scope: str | None = None, profile_id: str | None = None):
    return KnowledgeIndex(ScopedConfig(ConfigManager(), profile_id).load_knowledge()).search(q, scope=scope)


@router.get("/methods")
def methods(profile_id: str | None = None):
    return ScopedConfig(ConfigManager(), profile_id).load_methods()


@router.put("/methods")
def save_methods(value: dict[str, Any], profile_id: str | None = None):
    ScopedConfig(ConfigManager(), profile_id).save_methods(value)
    return {"status": "saved"}


@router.get("/queries")
def queries(profile_id: str | None = None):
    return ScopedConfig(ConfigManager(), profile_id).load_query_knowledge()


@router.put("/queries")
def save_queries(value: dict[str, Any], profile_id: str | None = None):
    ScopedConfig(ConfigManager(), profile_id).save_query_knowledge(value)
    return {"status": "saved"}
