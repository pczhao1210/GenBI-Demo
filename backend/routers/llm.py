from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from utils.bi_service import BIService
from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient

router = APIRouter()
Provider = Literal["openai", "openai_sdk", "azure_openai", "custom"]


class TestConnectionRequest(BaseModel):
    provider: Provider
    config: Dict[str, Any]


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]] = Field(min_length=1)
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0, le=2)


@router.post("/test-connection")
def test_llm_connection(request: TestConnectionRequest):
    if not request.config:
        raise ValueError("LLM configuration is required")
    client = LLMClient({**request.config, "provider": request.provider})
    response = client.generate_response("Reply with OK.", request_type="query")
    return {"status": "success", "provider": request.provider, "response": response}


@router.get("/models")
def get_available_models(provider: Provider):
    config = ConfigManager().load_llm_config()
    return {"models": LLMClient({**config, "provider": provider}).list_models()}


@router.post("/chat")
def chat_with_llm(request: ChatRequest):
    result = BIService().llm.chat(request.messages, model=request.model, temperature=request.temperature)
    return {"response": result["content"], "tool_calls": result.get("tool_calls"), "model": request.model}
