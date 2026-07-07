"""Database engine and session management for PRGuard AI using SQLAlchemy and asyncpg."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from prguard_ai.config.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Adjust database URL scheme if necessary for asyncpg
db_url = settings.database_url
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Initialize asynchronous engine and sessionmaker
engine = create_async_engine(
    db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    future=True,
)


async def init_db() -> None:
    """Initialize database tables asynchronously."""
    from prguard_ai.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def run_async(coro: Coroutine[Any, Any, T]) -> Any:
    """
    Safely execute an asynchronous coroutine from either sync or async environments.
    If there is already a running event loop in the current thread, schedule it as a task
    (fire-and-forget). Otherwise, execute it synchronously using asyncio.run().
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return loop.create_task(coro)
    else:
        return asyncio.run(coro)
