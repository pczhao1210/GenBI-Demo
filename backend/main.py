from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.routers import chat, database, mcp, llm, runs, semantics, tools, profiles
from utils.resources import BusyError

app = FastAPI(
    title="GenBI API",
    description="生成式BI数据库查询API",
    version="1.0.0"
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(chat.router, prefix="/api/chat", tags=["聊天"])
app.include_router(database.router, prefix="/api/database", tags=["数据库"])
app.include_router(mcp.router, prefix="/api/mcp", tags=["MCP"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
app.include_router(runs.router, prefix="/api/runs", tags=["Runs"])
app.include_router(semantics.router, prefix="/api/semantics", tags=["Semantics"])
app.include_router(tools.router, prefix="/api/tools", tags=["Tools"])
app.include_router(profiles.router, prefix="/api/profiles", tags=["Profiles"])


@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc), "success": False})


@app.exception_handler(RuntimeError)
async def execution_failed(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc), "success": False})


@app.exception_handler(BusyError)
async def busy(request, exc):
    return JSONResponse(status_code=503, headers={"Retry-After": "1"},
                        content={"detail": str(exc), "success": False, "run_id": getattr(exc, "run_id", None)})

@app.get("/")
async def root():
    return {"message": "GenBI API服务运行中"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}