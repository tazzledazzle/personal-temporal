"""
FastAPI application factory.

Router mounts:
- /health    — public (no auth), health probe
- /workflows — authenticated (Security(verify_api_key)), stub until Plan 03

Middleware:
- CorrelationIdMiddleware: injects X-Correlation-ID into structlog context

Exception handlers:
- NotFoundError → 404
- ConflictError → 409
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from app.core.auth import verify_api_key
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import CorrelationIdMiddleware
from app.health.router import router as health_router
from app.lifespan import lifespan

# Stub workflows router — Plan 03 will replace this with the full implementation.
# Required now so test_auth.py::test_valid_api_key_returns_200 (GET /workflows → 200) passes.
from fastapi import APIRouter, Security

_workflows_stub_router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Security(verify_api_key)],
)


@_workflows_stub_router.get("")
async def list_workflows_stub():
    """Stub: returns empty list. Plan 03 replaces this with full CRUD."""
    return []


app = FastAPI(
    title="Workflow Executor",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware — must be added before routers
app.add_middleware(CorrelationIdMiddleware)

# Routers
app.include_router(health_router)          # public — no auth dependency
app.include_router(_workflows_stub_router)  # authenticated stub

# Exception handlers
@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc) or "Not found"})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc) or "Conflict"})
