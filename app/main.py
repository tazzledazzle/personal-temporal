from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import CorrelationIdMiddleware
from app.health.router import router as health_router
from app.lifespan import lifespan
from app.runs.router import router as runs_router
from app.workflows.router import router as workflows_router

app = FastAPI(
    title="Workflow Executor",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIdMiddleware)

app.include_router(health_router)    # public — no auth dependency
app.include_router(workflows_router)  # authenticated — all routes require X-API-Key
app.include_router(runs_router)       # authenticated — all routes require X-API-Key


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc) or "Not found"})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc) or "Conflict"})
