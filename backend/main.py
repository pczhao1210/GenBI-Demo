from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import chat, database, mcp, llm

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

@app.get("/")
async def root():
    return {"message": "GenBI API服务运行中"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}