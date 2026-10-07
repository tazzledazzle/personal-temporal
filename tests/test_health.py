"""
PLAT-03: Tests for GET /health endpoint.

Health endpoint is a public probe — no X-API-Key required.
Returns 200 with database reachability and version when healthy,
503 when the database is unreachable.

These tests import app fixtures from conftest.py which imports from app.main —
intentional RED gate for Wave 1 TDD.
"""

import pytest


async def test_health_returns_200(client_no_auth):
    """
    PLAT-03: GET /health must return 200 with status, database, and version fields.

    All three response fields are required:
    - status: "healthy" when DB is reachable
    - database: "healthy" when the DB probe SELECT succeeds
    - version: non-empty string (APP_VERSION env var, defaults to "0.1.0")
    """
    response = await client_no_auth.get("/health")
    assert response.status_code == 200, (
        f"Expected 200 from /health, got {response.status_code}."
    )
    body = response.json()
    assert body["status"] == "healthy", (
        f"Expected status='healthy', got '{body.get('status')}'"
    )
    assert body["database"] == "healthy", (
        f"Expected database='healthy', got '{body.get('database')}'"
    )
    assert "version" in body, (
        "Response body must include 'version' field (APP_VERSION env var)"
    )


async def test_health_no_auth_required(client_no_auth):
    """
    PLAT-03: GET /health must be publicly accessible without X-API-Key.

    Health endpoint is an infrastructure probe; load balancers and k8s liveness
    probes cannot inject API keys. Excluding /health from auth dependency is
    the standard pattern.
    """
    response = await client_no_auth.get("/health")
    assert response.status_code == 200, (
        f"Expected GET /health to be public (200), got {response.status_code}. "
        "Do not apply verify_api_key dependency to the health router."
    )
