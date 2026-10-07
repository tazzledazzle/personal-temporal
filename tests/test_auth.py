"""
PLAT-01: Tests for X-API-Key header authentication.

All endpoints (except GET /health) require a valid X-API-Key header.
Missing or wrong key returns 401. Valid key returns the expected response.

These tests import app fixtures from conftest.py which imports from app.main —
intentional RED gate for Wave 1 TDD.
"""

import pytest


async def test_missing_api_key_returns_401(client_no_auth):
    """
    PLAT-01: GET /workflows without X-API-Key header must return 401.

    No key supplied at all — verify the auth dependency fires and rejects the request.
    """
    response = await client_no_auth.get("/workflows")
    assert response.status_code == 401, (
        f"Expected 401 without X-API-Key, got {response.status_code}. "
        "Ensure verify_api_key is a Security dependency on all workflow routes."
    )


async def test_wrong_api_key_returns_401(client_no_auth):
    """
    PLAT-01: GET /workflows with a wrong X-API-Key value must return 401.

    Supplying any key that does not match the configured API_KEY must be rejected.
    """
    response = await client_no_auth.get(
        "/workflows",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401, (
        f"Expected 401 with wrong X-API-Key, got {response.status_code}. "
        "Ensure secrets.compare_digest rejects non-matching keys."
    )


async def test_valid_api_key_returns_200(client):
    """
    PLAT-01: GET /workflows with a valid X-API-Key must return 200.

    The client fixture provides X-API-Key: test-api-key which matches TEST_API_KEY.
    An empty list is a valid 200 response when no workflows have been registered.
    """
    response = await client.get("/workflows")
    assert response.status_code == 200, (
        f"Expected 200 with valid X-API-Key, got {response.status_code}. "
        "Ensure GET /workflows returns 200 (possibly empty list) for authenticated requests."
    )
