from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.logging import configure_structlog

# Import all models so Base.metadata.create_all creates every table
import app.runs.models  # noqa: F401
import app.workflows.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_structlog(json_logs=get_settings().log_json)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    await engine.dispose()
