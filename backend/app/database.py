from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.env == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Sync engine for deterministic rule engine queries (no async overhead needed)
_sync_url = settings.database_url.replace("+asyncpg", "").replace("+aiosqlite", "")
sync_engine = create_engine(
    _sync_url,
    echo=settings.env == "development",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
SyncSessionLocal = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


def get_sync_db():
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()
