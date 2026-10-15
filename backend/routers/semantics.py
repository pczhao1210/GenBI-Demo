from typing import Any

from fastapi import APIRouter

from utils.config_manager import ConfigManager
from utils.semantics import KnowledgeIndex

router = APIRouter()


@router.get("/ontology")
def ontology():
    return ConfigManager().load_semantics()


@router.put("/ontology")
def save_ontology(value: dict[str, Any]):
    ConfigManager().save_semantics(value)
    return {"status": "saved"}


@router.get("/knowledge")
def knowledge():
    return ConfigManager().load_knowledge()


@router.put("/knowledge")
def save_knowledge(value: dict[str, Any]):
    ConfigManager().save_knowledge(value)
    return {"status": "saved"}


@router.get("/search")
def search(q: str, scope: str | None = None):
    return KnowledgeIndex(ConfigManager().load_knowledge()).search(q, scope=scope)
