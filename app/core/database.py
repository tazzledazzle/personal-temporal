"""
Async SQLite engine factory, session maker, write lock, and get_db dependency.

Key design decisions (from RESEARCH.md):
- event.listens_for(engine.sync_engine, "connect") — NOT engine directly — for PRAGMA hooks
- expire_on_commit=False — prevents DetachedInstanceError / MissingGreenlet in async context
- asyncio.Lock at module level — serializes all write coroutines in the single-worker process
- NullPool for production, StaticPool for tests
"""

import asyncio
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from app.core.config import get_settings

# Module-level write lock — serializes all write coroutines (RESIL-04)
_write_lock = asyncio.Lock()


class Base(DeclarativeBase):
    """Single DeclarativeBase for all models in the project."""
    pass


def create_engine(db_url: str, testing: bool = False) -> AsyncEngine:
    """
    Create an async SQLite engine with WAL mode and busy_timeout PRAGMAs.

    Args:
        db_url: SQLAlchemy database URL (ignored when testing=True).
        testing: If True, uses StaticPool + :memory: for test isolation.

    Returns:
        Configured AsyncEngine with WAL + busy_timeout PRAGMAs registered.
    """
    if testing:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_async_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, _):
        """Set per-connection PRAGMAs. Fires on every new connection."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA cache_size=-64000;")
        cursor.close()

    return engine


# Production engine — initialized at module load
engine = create_engine(get_settings().database_url)

# Session factory — expire_on_commit=False is NON-NEGOTIABLE for async (RESEARCH.md Pitfall 2)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession per request."""
    async with AsyncSessionLocal() as session:
        yield session
