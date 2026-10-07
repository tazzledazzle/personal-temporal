"""
FastAPI lifespan context manager — startup and shutdown hooks.

Startup:
1. configure_structlog — must happen before any log call
2. create_all tables — creates schema for all models registered on Base.metadata

Shutdown:
1. engine.dispose — closes all pooled connections cleanly

Using @asynccontextmanager lifespan is the current idiom (FastAPI 0.93+).
The deprecated on_event("startup") / on_event("shutdown") is NOT used.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.logging import configure_structlog


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: startup before yield, shutdown after yield.
    """
    # Startup
    configure_structlog(json_logs=get_settings().log_json)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    # Shutdown
    await engine.dispose()
