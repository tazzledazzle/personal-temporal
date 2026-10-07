"""
structlog configuration and CorrelationIdMiddleware.

Design decisions (RESEARCH.md Pattern 5):
- clear_contextvars() BEFORE bind_contextvars() — prevents request context leak across
  asyncio tasks (RESEARCH.md Pitfall 5)
- CorrelationIdMiddleware echoes X-Correlation-ID in response header (PLAT-02)
- configure_structlog() called once at app startup via lifespan
"""

import logging
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def configure_structlog(json_logs: bool = True) -> None:
    """
    Configure structlog with contextvars integration.

    Args:
        json_logs: If True, renders JSON. If False, renders console output (dev mode).
    """
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that injects a correlation ID into structlog context
    and echoes it back in the X-Correlation-ID response header.

    Order of operations is critical (RESEARCH.md Pitfall 5):
    1. clear_contextvars() — wipe any context from a prior request on this asyncio task
    2. bind_contextvars() — bind fresh context for this request
    3. call_next(request) — process the request
    4. set response header — echo correlation_id back to the caller
    """

    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        # REQUIRED: clear before bind to prevent cross-request context leak
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            path=str(request.url.path),
            method=request.method,
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
