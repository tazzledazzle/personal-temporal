"""
Integration test suite: full register → execute → compensate flow.

RED gate — these tests are committed BEFORE the wiring changes that make them pass.
Plan 04-03 will fix any failures surfaced here.

Key design decisions:
- Uses NamedTemporaryFile SQLite (NOT in-memory, NOT StaticPool) — mirrors production
- Mocks outbound HTTP with respx (no real network calls leave the process)
- Patches executor_module.AsyncSessionLocal so the background task uses the test DB
- Polling loop waits up to 2 seconds for the background executor to reach a terminal state
"""

import asyncio
import os
import tempfile

# Set API_KEY BEFORE any app imports so pydantic-settings picks it up
os.environ.setdefault("API_KEY", "integration-test-key")

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.runs.executor as executor_module
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INT_API_KEY = "integration-test-key"
TERMINAL_STATES = {"COMPLETED", "FAILED", "COMPENSATED", "COMPENSATION_FAILED"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def integration_engine():
    """Real NamedTemporaryFile SQLite engine with NullPool + WAL PRAGMAs."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_url = f"sqlite+aiosqlite:///{tmp.name}"

    engine = create_async_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    os.unlink(tmp.name)


@pytest.fixture
async def integration_client(integration_engine):
    """
    AsyncClient wired to the integration_engine.

    Patches:
    1. app.dependency_overrides[get_db] — routes request-scoped sessions to the test DB
    2. executor_module.AsyncSessionLocal — routes the background executor to the test DB
    """
    get_settings.cache_clear()  # force re-read so INT_API_KEY is picked up

    TestSession = async_sessionmaker(
        bind=integration_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    original_factory = executor_module.AsyncSessionLocal
    executor_module.AsyncSessionLocal = TestSession

    async def override_get_db():
        async with TestSession() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": INT_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    executor_module.AsyncSessionLocal = original_factory


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _wait_for_terminal(
    client: AsyncClient,
    run_id: str,
    max_iters: int = 20,
    sleep_s: float = 0.1,
) -> dict:
    """
    Poll GET /runs/{run_id} until status is in TERMINAL_STATES.

    Returns the response JSON when a terminal state is reached.
    Raises AssertionError if the terminal state is not reached within max_iters iterations.
    """
    for _ in range(max_iters):
        await asyncio.sleep(sleep_s)
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200, f"GET /runs/{run_id} returned {response.status_code}"
        data = response.json()
        if data["status"] in TERMINAL_STATES:
            return data
    raise AssertionError(
        f"Run {run_id} did not reach a terminal state within {max_iters * sleep_s}s. "
        f"Last status: {data['status']}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_full_workflow_happy_path(integration_client):
    """
    Truth 1 — Happy path: both steps succeed, run reaches COMPLETED.

    Register a 2-step workflow, execute it with both steps mocked to 200,
    poll for COMPLETED, assert all step statuses are COMPLETED.
    """
    # Register workflow
    reg = await integration_client.post(
        "/workflows",
        json={
            "name": "int-happy",
            "steps": [
                {"name": "step-1", "execute_url": "http://mock-svc/step1"},
                {"name": "step-2", "execute_url": "http://mock-svc/step2"},
            ],
        },
    )
    assert reg.status_code == 201, f"Register failed: {reg.text}"

    async with respx.mock(assert_all_called=False) as mock:
        mock.post("http://mock-svc/step1").mock(return_value=httpx.Response(200))
        mock.post("http://mock-svc/step2").mock(return_value=httpx.Response(200))

        r = await integration_client.post("/workflows/int-happy/runs", json={})
        assert r.status_code == 202, f"Execute failed: {r.text}"
        run_id = r.json()["run_id"]

        run_data = await _wait_for_terminal(integration_client, run_id)

    assert run_data["status"] == "COMPLETED", f"Expected COMPLETED, got {run_data['status']}"

    steps_r = await integration_client.get(f"/runs/{run_id}/steps")
    assert steps_r.status_code == 200, f"GET /runs/{run_id}/steps returned {steps_r.status_code}"
    steps = steps_r.json()
    assert len(steps) == 2, f"Expected 2 steps, got {len(steps)}"
    assert all(s["status"] == "COMPLETED" for s in steps), (
        f"Not all steps COMPLETED: {[s['status'] for s in steps]}"
    )


async def test_compensation_triggered_on_step_failure(integration_client):
    """
    Truth 2 — Compensation triggered: step-2 returns 500, run compensates step-1.

    Register a 2-step workflow with compensate_urls, execute with step-2 failing (500),
    poll for terminal state, assert run status is COMPENSATED or COMPENSATION_FAILED,
    assert step-1 has compensation_status set (compensate_url was called),
    assert step-2 has status == "FAILED".
    """
    reg = await integration_client.post(
        "/workflows",
        json={
            "name": "int-comp-fail",
            "steps": [
                {
                    "name": "step-1",
                    "execute_url": "http://mock-svc/s1",
                    "compensate_url": "http://mock-svc/comp1",
                },
                {
                    "name": "step-2",
                    "execute_url": "http://mock-svc/s2",
                    "compensate_url": "http://mock-svc/comp2",
                },
            ],
        },
    )
    assert reg.status_code == 201, f"Register failed: {reg.text}"

    async with respx.mock(assert_all_called=False) as mock:
        mock.post("http://mock-svc/s1").mock(return_value=httpx.Response(200))
        mock.post("http://mock-svc/s2").mock(return_value=httpx.Response(500))
        mock.post("http://mock-svc/comp1").mock(return_value=httpx.Response(200))
        mock.post("http://mock-svc/comp2").mock(return_value=httpx.Response(200))

        r = await integration_client.post("/workflows/int-comp-fail/runs", json={})
        assert r.status_code == 202, f"Execute failed: {r.text}"
        run_id = r.json()["run_id"]

        run_data = await _wait_for_terminal(integration_client, run_id)

    assert run_data["status"] in {"COMPENSATED", "COMPENSATION_FAILED"}, (
        f"Expected COMPENSATED or COMPENSATION_FAILED, got {run_data['status']}"
    )

    steps_r = await integration_client.get(f"/runs/{run_id}/steps")
    assert steps_r.status_code == 200
    steps = {s["step_name"]: s for s in steps_r.json()}

    assert steps["step-1"]["compensation_status"] is not None, (
        "step-1 should have been compensated (compensation_status should not be None)"
    )
    assert steps["step-2"]["status"] == "FAILED", (
        f"step-2 should have status FAILED, got {steps['step-2']['status']}"
    )


async def test_compensation_triggered_on_timeout(integration_client):
    """
    Truth 3 — Step timeout triggers compensation: step-2 raises TimeoutException.

    Register a 2-step workflow, execute with step-2 raising TimeoutException via respx
    side_effect, poll for terminal state, assert run status is a terminal compensation
    state, assert step-1 compensation_status is not None (compensate_url was called).
    """
    reg = await integration_client.post(
        "/workflows",
        json={
            "name": "int-comp-timeout",
            "steps": [
                {
                    "name": "step-1",
                    "execute_url": "http://mock-svc/t1",
                    "compensate_url": "http://mock-svc/tcomp1",
                },
                {
                    "name": "step-2",
                    "execute_url": "http://mock-svc/t2",
                    "compensate_url": "http://mock-svc/tcomp2",
                    "timeout_seconds": 1,
                },
            ],
        },
    )
    assert reg.status_code == 201, f"Register failed: {reg.text}"

    async with respx.mock(assert_all_called=False) as mock:
        mock.post("http://mock-svc/t1").mock(return_value=httpx.Response(200))
        mock.post("http://mock-svc/t2").mock(side_effect=httpx.TimeoutException("timeout"))
        mock.post("http://mock-svc/tcomp1").mock(return_value=httpx.Response(200))

        r = await integration_client.post("/workflows/int-comp-timeout/runs", json={})
        assert r.status_code == 202, f"Execute failed: {r.text}"
        run_id = r.json()["run_id"]

        run_data = await _wait_for_terminal(integration_client, run_id)

    assert run_data["status"] in {"COMPENSATED", "COMPENSATION_FAILED", "FAILED"}, (
        f"Expected terminal compensation state, got {run_data['status']}"
    )

    steps_r = await integration_client.get(f"/runs/{run_id}/steps")
    assert steps_r.status_code == 200
    steps = {s["step_name"]: s for s in steps_r.json()}

    assert steps["step-1"]["compensation_status"] is not None, (
        "step-1 should have been compensated after step-2 timeout"
    )
