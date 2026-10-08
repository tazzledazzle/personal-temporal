"""
EXEC-01, EXEC-02, EXEC-03, RESIL-02: Tests for workflow run execution endpoints.

POST /workflows/{name}/runs  — start a run (202)
GET  /runs/{run_id}          — query run status (200/404)
GET  /runs/{run_id}/steps    — query step execution history (200/404)

Synchronization note: FastAPI BackgroundTasks run as part of the ASGI response lifecycle.
ASGITransport waits for the ASGI scope to close before returning from await client.post(...).
Starlette closes the scope AFTER background tasks complete. Therefore, background executor
is DONE before client.post() returns — no sleep() or polling needed.

respx note: Use 'async with respx.mock:' context manager (not @respx.mock decorator) so
the mock is explicitly active during the entire ASGI call including BackgroundTasks.
"""

import respx
import httpx
from app.runs.schemas import RunResponse  # RED — does not exist yet

WORKFLOW_BODY = {
    "name": "exec-wf",
    "steps": [
        {"name": "step-a", "execute_url": "http://mock.test/step-a"},
        {"name": "step-b", "execute_url": "http://mock.test/step-b"},
    ],
}
INPUT_PAYLOAD = {"key": "value"}


async def test_start_run_returns_202(client):
    await client.post("/workflows", json=WORKFLOW_BODY)
    async with respx.mock:
        respx.post("http://mock.test/step-a").mock(return_value=httpx.Response(200))
        respx.post("http://mock.test/step-b").mock(return_value=httpx.Response(200))
        response = await client.post("/workflows/exec-wf/runs", json={"input": INPUT_PAYLOAD})
    assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
    assert "run_id" in response.json(), f"Expected run_id in response: {response.text}"


async def test_run_completes_successfully(client):
    await client.post("/workflows", json=WORKFLOW_BODY)
    async with respx.mock:
        respx.post("http://mock.test/step-a").mock(return_value=httpx.Response(200))
        respx.post("http://mock.test/step-b").mock(return_value=httpx.Response(200))
        response = await client.post("/workflows/exec-wf/runs", json={"input": INPUT_PAYLOAD})
        # BackgroundTasks complete before client.post() returns (ASGITransport lifecycle)
        run_id = response.json()["run_id"]
        status_response = await client.get(f"/runs/{run_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "COMPLETED", f"Expected COMPLETED, got {body['status']}"
    assert body["current_step_index"] == 1, f"Expected step index 1 (step-b), got {body['current_step_index']}"
    assert body["completed_at"] is not None, "Expected completed_at to be set"


async def test_get_run_returns_200(client):
    await client.post("/workflows", json=WORKFLOW_BODY)
    async with respx.mock:
        respx.post("http://mock.test/step-a").mock(return_value=httpx.Response(200))
        respx.post("http://mock.test/step-b").mock(return_value=httpx.Response(200))
        response = await client.post("/workflows/exec-wf/runs", json={"input": INPUT_PAYLOAD})
        run_id = response.json()["run_id"]
        status_response = await client.get(f"/runs/{run_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert "status" in body
    assert "input_payload" in body
    assert "started_at" in body


async def test_get_run_steps(client):
    await client.post("/workflows", json=WORKFLOW_BODY)
    async with respx.mock:
        respx.post("http://mock.test/step-a").mock(return_value=httpx.Response(200))
        respx.post("http://mock.test/step-b").mock(return_value=httpx.Response(200))
        response = await client.post("/workflows/exec-wf/runs", json={"input": INPUT_PAYLOAD})
        run_id = response.json()["run_id"]
        steps_response = await client.get(f"/runs/{run_id}/steps")
    assert steps_response.status_code == 200
    body = steps_response.json()
    assert len(body) == 2, f"Expected 2 steps, got {len(body)}"
    assert body[0]["step_name"] == "step-a"
    assert body[0]["status"] == "COMPLETED"
    assert body[0]["http_status_code"] == 200
    assert "http_status_code" in body[0]


async def test_step_timeout_fails_run(client):
    await client.post("/workflows", json=WORKFLOW_BODY)
    async with respx.mock:
        respx.post("http://mock.test/step-a").mock(side_effect=httpx.TimeoutException("timeout"))
        response = await client.post("/workflows/exec-wf/runs", json={"input": INPUT_PAYLOAD})
        run_id = response.json()["run_id"]
        status_response = await client.get(f"/runs/{run_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "FAILED", f"Expected FAILED, got {body['status']}"
    assert "timeout" in body["error_detail"].lower(), f"Expected 'timeout' in error_detail: {body['error_detail']}"


async def test_step_failure_fails_run(client):
    await client.post("/workflows", json=WORKFLOW_BODY)
    async with respx.mock:
        respx.post("http://mock.test/step-a").mock(return_value=httpx.Response(500))
        response = await client.post("/workflows/exec-wf/runs", json={"input": INPUT_PAYLOAD})
        run_id = response.json()["run_id"]
        status_response = await client.get(f"/runs/{run_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "FAILED", f"Expected FAILED, got {body['status']}"


async def test_get_missing_run_returns_404(client):
    response = await client.get("/runs/nonexistent-id")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
