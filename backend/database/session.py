from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from backend.config.settings import settings
from backend.core.logging_config import get_logger

logger = get_logger(__name__)

SYNC_DATABASE_URL = f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
ASYNC_DATABASE_URL = f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"

engine = create_engine(
    SYNC_DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)
async_engine_options: dict[str, Any] = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
}
if settings.DATABASE_USE_NULL_POOL:
    async_engine_options["poolclass"] = NullPool
else:
    async_engine_options.update(
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT_SECONDS,
    )
async_engine = create_async_engine(ASYNC_DATABASE_URL, **async_engine_options)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


# Yield one non-blocking database session for the current request.
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        yield db
