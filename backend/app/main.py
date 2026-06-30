import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import router as v1_router
from app.config import settings
from app.database import engine

logger = structlog.get_logger()

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
    """Health check endpoint. Used by load balancer and monitoring."""
    return {"status": "ok", "env": settings.env}


@app.on_event("startup")
async def startup():
    """
    Application startup:
    1. Verify DB connectivity (migrations handled by Alembic separately)
    2. Create ARQ pool and store on app.state for use in route handlers
    """
    # DB connectivity check
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected")
    except Exception as e:
        logger.warning("db_connection_check_failed", error=str(e))

    # ARQ pool for enqueueing background jobs
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
    """Clean up connections on graceful shutdown."""
    arq_pool = getattr(app.state, "arq_pool", None)
    if arq_pool:
        await arq_pool.aclose()

    await engine.dispose()
    logger.info("app_shutdown_complete")
