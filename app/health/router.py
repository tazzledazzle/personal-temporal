"""
GET /health — public endpoint, no auth required.

Returns 200 with database probe result when healthy, 503 when DB is unreachable.
Health is an infrastructure probe; load balancers and k8s liveness probes cannot
inject API keys, so auth is explicitly excluded (PLAT-03, Assumption A1).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """
    Probe the database with SELECT 1 and return service health status.

    Response body:
    - status: "healthy" | "unhealthy"
    - database: "healthy" | "unhealthy"
    - version: APP_VERSION env var value (default "0.1.0")
    """
    try:
        await db.execute(text("SELECT 1"))
        db_status = "healthy"
        status_code = 200
    except Exception:
        db_status = "unhealthy"
        status_code = 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if status_code == 200 else "unhealthy",
            "database": db_status,
            "version": get_settings().app_version,
        },
    )
