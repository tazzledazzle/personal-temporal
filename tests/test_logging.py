"""
PLAT-02: Tests for structured logging and correlation ID propagation.

The CorrelationIdMiddleware must:
- Accept an incoming X-Correlation-ID header and echo it in the response
- Generate a UUID correlation ID when no header is provided
- Echo the correlation ID in the X-Correlation-ID response header

Note: Testing that structlog JSON output contains `correlation_id` requires
log capture infrastructure (capsys / capfd / loguru interception). The
response header echo is a sufficient Phase 1 proxy — the middleware binds
the correlation_id to contextvars and also sets it on the response header.
Full structured log output verification (confirming `correlation_id` appears
in the JSON log line) is deferred to the integration test suite in Phase 4.

These tests import app fixtures from conftest.py which imports from app.main —
intentional RED gate for Wave 1 TDD.
"""

import pytest


async def test_correlation_id_in_response_header(client):
    """
    PLAT-02: GET /health response must include X-Correlation-ID header.

    The CorrelationIdMiddleware generates a UUID correlation ID for each request
    (or uses the value from the incoming X-Correlation-ID header) and echoes it
    back in the response header. This is the Phase 1 proxy for verifying that
    correlation_id is bound to the structlog context for that request.
    """
    response = await client.get("/health")
    assert "x-correlation-id" in response.headers, (
        "Expected 'x-correlation-id' in response headers. "
        "Ensure CorrelationIdMiddleware sets response.headers['X-Correlation-ID']."
    )
    correlation_id = response.headers["x-correlation-id"]
    assert correlation_id, (
        "Expected non-empty x-correlation-id header value. "
        "The middleware must set a UUID when no incoming header is present."
    )
