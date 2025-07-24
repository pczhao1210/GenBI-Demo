from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any, List

router = APIRouter()

class TestConnectionRequest(BaseModel):
    provider: str
    config: Dict[str, Any]

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: str
    temperature: float = 0.7

@router.post("/test-connection")
async def test_llm_connection(request: TestConnectionRequest):
    """测试LLM连接"""
    return {
        "status": "success",
        "provider": request.provider,
        "message": "连接测试成功"
    }

@router.get("/models")
async def get_available_models(provider: str):
    """获取可用模型列表"""
    models = {
        "openai": ["gpt-4", "gpt-3.5-turbo", "gpt-4-turbo"],
        "azure_openai": ["gpt-4", "gpt-35-turbo"],
        "custom": ["llama2", "codellama"]
    }
    return {"models": models.get(provider, [])}

@router.post("/chat")
async def chat_with_llm(request: ChatRequest):
    """调用LLM进行对话"""
    return {
        "response": "这是一个模拟的LLM响应",
        "model": request.model,
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    }