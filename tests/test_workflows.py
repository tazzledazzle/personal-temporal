"""
DEFN-01, DEFN-02, DEFN-03: Tests for workflow definition CRUD endpoints.

POST /workflows   — create a workflow definition (201)
GET  /workflows   — list all workflow definitions (200)
GET  /workflows/{name} — retrieve definition by name (200/404)
DELETE /workflows/{name} — delete definition (204/404)

These tests import app fixtures from conftest.py which imports from app.main —
intentional RED gate for Wave 1 TDD.
"""

import pytest


# ---------------------------------------------------------------------------
# Reusable test payload
# ---------------------------------------------------------------------------

VALID_WORKFLOW_BODY = {
    "name": "test-wf",
    "steps": [
        {
            "name": "s1",
            "execute_url": "http://example.com/step",
        }
    ],
}


async def test_create_workflow_returns_201(client):
    """
    DEFN-01: POST /workflows with a valid body must return 201 and the stored definition.

    Response must include:
    - name matching the request
    - steps list with the same length as the request steps
    """
    response = await client.post("/workflows", json=VALID_WORKFLOW_BODY)
    assert response.status_code == 201, (
        f"Expected 201 on POST /workflows, got {response.status_code}. "
        f"Response body: {response.text}"
    )
    body = response.json()
    assert body["name"] == "test-wf", (
        f"Expected name='test-wf', got '{body.get('name')}'"
    )
    assert len(body["steps"]) == 1, (
        f"Expected 1 step in response, got {len(body.get('steps', []))}"
    )


async def test_get_workflow_by_name(client):
    """
    DEFN-02: GET /workflows/{name} must return 200 with the workflow definition.

    Round-trip: create then retrieve by name.
    """
    await client.post("/workflows", json=VALID_WORKFLOW_BODY)
    response = await client.get("/workflows/test-wf")
    assert response.status_code == 200, (
        f"Expected 200 on GET /workflows/test-wf, got {response.status_code}."
    )
    body = response.json()
    assert body["name"] == "test-wf", (
        f"Expected name='test-wf', got '{body.get('name')}'"
    )


async def test_list_workflows(client):
    """
    DEFN-02: GET /workflows must return 200 with at least the created workflow.

    After creating one workflow, the list must have at least one entry.
    """
    await client.post("/workflows", json=VALID_WORKFLOW_BODY)
    response = await client.get("/workflows")
    assert response.status_code == 200, (
        f"Expected 200 on GET /workflows, got {response.status_code}."
    )
    body = response.json()
    assert len(body) >= 1, (
        f"Expected at least 1 workflow in list after creation, got {len(body)}."
    )


async def test_delete_workflow_no_runs_returns_204(client):
    """
    DEFN-03: DELETE /workflows/{name} must return 204 when no active runs exist.

    In Phase 1 there are no runs, so deletion must always succeed with 204.
    """
    await client.post("/workflows", json=VALID_WORKFLOW_BODY)
    response = await client.delete("/workflows/test-wf")
    assert response.status_code == 204, (
        f"Expected 204 on DELETE /workflows/test-wf (no active runs), got {response.status_code}."
    )


async def test_get_missing_workflow_returns_404(client):
    """
    DEFN-02: GET /workflows/{name} for a non-existent workflow must return 404.
    """
    response = await client.get("/workflows/nonexistent")
    assert response.status_code == 404, (
        f"Expected 404 for GET /workflows/nonexistent, got {response.status_code}."
    )
