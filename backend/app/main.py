import os

import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import router as v1_router
from app.config import settings
from app.database import engine
from app.logging_config import configure_logging
from app.prompts import prompt_registry

# LangSmith 追踪：必须在任何 LangChain/LangGraph 导入创建 client 之前设置这些环境变量。
# LangGraph 会自动读取这些环境变量，graph.py 里不需要额外改代码。
if settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

configure_logging()
logger = structlog.get_logger()
prompt_registry.validate_all()

app = FastAPI(
    title="问津 Agent API",
    version="0.1.0",
    description="高考志愿智能辅助决策平台后端 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1")


@app.get("/health")
async def health():
    """健康检查接口，供负载均衡器和监控系统探活使用。"""
    return {"status": "ok", "env": settings.env}


@app.on_event("startup")
async def startup():
    """
    应用启动时执行：
    1. 校验数据库连通性（迁移由 Alembic 单独处理，这里不做）
    2. 创建 ARQ 连接池并挂到 app.state 上，供路由处理函数使用
    """
    # 数据库连通性检查
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected")
    except Exception as e:
        logger.warning("db_connection_check_failed", error=str(e))

    # 用于投递后台任务的 ARQ 连接池
    try:
        app.state.arq_pool = await create_pool(
            RedisSettings.from_dsn(settings.redis_url)
        )
        logger.info("arq_pool_created")
    except Exception as e:
        logger.warning("arq_pool_creation_failed", error=str(e))
        app.state.arq_pool = None


@app.on_event("shutdown")
async def shutdown():
    """优雅关闭时清理各连接。"""
    arq_pool = getattr(app.state, "arq_pool", None)
    if arq_pool:
        await arq_pool.aclose()

    await engine.dispose()
    logger.info("app_shutdown_complete")
