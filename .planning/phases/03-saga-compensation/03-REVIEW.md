---
phase: 03-saga-compensation
reviewed: 2026-10-07T00:00:00Z
depth: standard
files_reviewed: 1
files_reviewed_list:
  - tests/test_compensation.py
findings:
  critical: 2
  warning: 3
  info: 1
  total: 6
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-10-07
**Depth:** standard
**Files Reviewed:** 1
**Status:** issues_found

## Summary

`tests/test_compensation.py` is a test suite for saga compensation behavior that does not yet have a corresponding implementation (`app/runs/compensator.py` and `CompensationCoordinator` are missing). The tests are well-structured and the intentions are clear, but several defects make the suite unreliable or incorrect as written:

1. Two tests query the database **outside** the `respx.mock` context manager, which means those queries go to the live test DB session — but they do so after the mock context has exited. If background tasks complete inside the `async with respx.mock:` block (as the comment at lines 8–11 asserts), reading state after the block is correct for compensation status — but the `run_id` is extracted inside the block while the `steps_response` fetch runs outside it. For the GET endpoints this is fine since they hit the local ASGI app, but the pattern is inconsistent across tests and fragile.
2. The critical problem: `respx.mock` intercepts `httpx.AsyncClient` calls at the library level, but `executor.py` creates its own `httpx.AsyncClient()` instance inside `execute_run` (line 60). `respx.mock` as a context manager uses `respx.mock` (the global router), which patches the default httpx transport globally when used as a context manager via `respx.mock` — this **does** intercept all httpx calls including those from the executor's own client. However, the scope mismatch between where `respx.mock` is entered and when the background task actually fires is the real bug (see CR-01).
3. `StepExecutionResponse` schema (in `app/runs/schemas.py`) is missing the three compensation fields (`compensation_status`, `compensation_error`, `compensated_at`) that the tests assert on. The tests will raise `KeyError` at runtime even if compensation runs correctly.
4. The workflow `POST /workflows` in every test uses `await client.post("/workflows", json=COMP_WORKFLOW)` without checking the response — a duplicate-workflow insert on the second test that reuses the same `"name": "comp-wf"` may 409 or silently succeed depending on the implementation.

---

## Critical Issues

### CR-01: respx mock scope does not cover background task execution — tests will pass vacuously or raise UnroutableError

**File:** `tests/test_compensation.py:43-54` (and all other `async with respx.mock:` blocks)

**Issue:** The `async with respx.mock:` context manager patches httpx transports while the block is entered, then restores them when the block exits. `BackgroundTasks` in FastAPI with `ASGITransport` are awaited synchronously inside `await client.post(...)` — the ASGI lifecycle does run background tasks before the response is returned to the test — **but only if the implementation uses the patched `AsyncSessionLocal`**. The executor creates `httpx.AsyncClient()` inside `execute_run`. `respx.mock` as an `async with` context manager uses `respx.mock` (global router) and patches `httpx.AsyncClient` globally while active, so the transport interception does cover in-background-task calls as long as the background task completes before `__aexit__`.

The **actual** bug is that `test_compensation_called_on_step_failure` (and `test_run_status_compensated_when_all_succeed`) register the workflow with `await client.post("/workflows", json=COMP_WORKFLOW)` **outside** the `async with respx.mock:` block, then open the mock block and start the run. At that point the respx mock is active and will intercept executor calls. This is correct. However, the GET calls to `/runs/{run_id}/steps` and `/runs/{run_id}` are made **inside** the mock block — these hit the ASGI app which queries SQLite, not an HTTP endpoint respx is intercepting. Since respx by default uses `assert_all_called=True` in some configurations and the mock routes are not scoped, any unexpected httpx call from within the mock block (e.g., if the compensator also uses httpx internally and is called during the GET handler) would raise. More critically: if `app/runs/compensator.py` does **not** exist, the import at line 15 (`from app.runs.compensator import CompensationCoordinator`) will raise `ModuleNotFoundError` at collection time, and **all six tests will be skipped/errored with a collection failure** rather than failing individually. This is effectively a blocker for the entire test file.

**Fix:** The import guard should be conditional or the module must be created before these tests are collected. For now, add a skip marker or move the import inside the test function body until the implementation exists. Once implemented, verify the compensator is wired into `execute_run` or the router so background task execution actually triggers it:

```python
# Option A — guard the import so the rest of the suite isn't blocked:
try:
    from app.runs.compensator import CompensationCoordinator
except ImportError:
    CompensationCoordinator = None  # type: ignore

# ... then in each test:
if CompensationCoordinator is None:
    pytest.skip("CompensationCoordinator not implemented yet")
```

Or create the module as a stub immediately so pytest can collect it.

---

### CR-02: StepExecutionResponse schema missing compensation fields — tests will raise KeyError

**File:** `tests/test_compensation.py:51-55, 98-103, 119-126`

**Issue:** Every test that calls `GET /runs/{run_id}/steps` and inspects compensation results does so by accessing `s["compensation_status"]`, `s["compensated_at"]`, and `s["compensation_error"]` on the response JSON. The `StepExecutionResponse` Pydantic schema in `app/runs/schemas.py:20-29` has **no** fields for these three attributes. Even though the ORM model (`WorkflowStepExecution`) defines them at lines 60-62, Pydantic will silently drop unknown model attributes when serializing via `model_validate` with `from_attributes=True`. The response JSON will therefore lack these keys, and `s["compensation_status"]` will raise `KeyError`, making every compensation assertion fail at the wrong layer.

**Fix:** Add the three fields to `StepExecutionResponse`:

```python
class StepExecutionResponse(BaseModel):
    id: str
    step_index: int
    step_name: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    http_status_code: int | None
    error_detail: str | None
    # Phase 3 compensation fields
    compensation_status: str | None = None
    compensated_at: datetime | None = None
    compensation_error: str | None = None
    model_config = {"from_attributes": True}
```

---

## Warnings

### WR-01: Workflow registration not isolated between tests — second test using same workflow name may 409 or silently collide

**File:** `tests/test_compensation.py:42, 60, 87, 108, 130, 146`

**Issue:** Every test calls `await client.post("/workflows", json=COMP_WORKFLOW)` where `COMP_WORKFLOW` has `"name": "comp-wf"`. Each test uses the same `client` fixture, but `client` depends on `test_engine` which is a **function-scoped** fixture (pytest-asyncio defaults to function scope). Since `test_engine` creates a fresh DB per test, isolation is provided by the fixture scope. However, if the fixture scope were ever changed to `session` or `module`, all tests would break with duplicate-key errors. More immediately, the lack of response-checking means a `409 Conflict` (if the workflow endpoint returns one) would go undetected and the subsequent `POST /workflows/comp-wf/runs` would either 404 or use a stale definition. This should be asserted.

**Fix:** Assert the registration succeeds:

```python
reg_response = await client.post("/workflows", json=COMP_WORKFLOW)
assert reg_response.status_code in (200, 201), f"Workflow registration failed: {reg_response.text}"
```

---

### WR-02: test_compensation_lifo_order does not assert compensation is complete before checking call_order

**File:** `tests/test_compensation.py:77-82`

**Issue:** The test exits the `async with respx.mock:` block at line 82 (implicitly, after `await client.post(...)`) and then asserts `call_order`. The comment at line 78 states "Compensation completes before post() returns" — this relies on ASGITransport completing all background tasks synchronously. If this invariant ever breaks (e.g., if the compensator spawns a new `asyncio.Task` rather than awaiting directly inside the `BackgroundTask`), `call_order` may be empty or partial at assertion time, producing a flaky test rather than a definitive failure. There is no assertion that compensation was triggered at all before checking order.

**Fix:** Add an assertion that both entries are present before checking order, and add a guard for the empty case:

```python
assert len(call_order) == 2, (
    f"Expected 2 compensation calls, got {len(call_order)}: {call_order}. "
    "Compensation may not have run — check executor wiring."
)
assert call_order == ["comp-b", "comp-a"], (
    f"Expected LIFO order [comp-b, comp-a], got {call_order}"
)
```

---

### WR-03: test_compensation_skips_steps_without_compensate_url has dead variable step_c that is never asserted

**File:** `tests/test_compensation.py:120-126`

**Issue:** `step_c` is fetched at line 120 with a default of `None` (`next((s for s in body if ...), None)`) but is never asserted on. The comment at lines 119-121 explains what the expected behavior is, but no assertion captures it. If the compensator incorrectly sets `compensation_status` on `step-c`, this test will not catch it. Additionally, the comment ("step-c completed before failing") contradicts the mock setup: `exec-c` returns 500 at line 112, so `step-c` actually **failed**, not completed.

**Fix:** Either assert that `step_c` has `compensation_status == None` (no compensation attempted on a failed step with no compensate_url), or assert it is absent from the response if the schema filters it:

```python
# step-c failed (HTTP 500); it should not be compensated
if step_c is not None:
    assert step_c["compensation_status"] is None, (
        f"step-c should have no compensation_status, got {step_c['compensation_status']}"
    )
```

Also correct the misleading comment: `step-c` received a 500 response (it failed), it did not "complete before failing."

---

## Info

### IN-01: Module-level import of non-existent symbol documents RED state as a code comment, but causes collection failure

**File:** `tests/test_compensation.py:15`

**Issue:** The comment `# RED — does not exist yet` acknowledges this is a red-phase TDD import, but pytest will fail to collect the entire module with `ModuleNotFoundError` rather than skipping or xfailing individual tests. This means unrelated test failures will appear in CI even for test runs that don't target this file, if the test runner imports all test modules at collection time (which pytest does by default).

**Fix:** Use a `pytest.importorskip` guard or a `try/except ImportError` at module level with a `pytestmark` to skip all tests in the file until the implementation exists:

```python
# At top of file, after other imports:
compensator_mod = pytest.importorskip(
    "app.runs.compensator",
    reason="CompensationCoordinator not implemented yet",
)
CompensationCoordinator = compensator_mod.CompensationCoordinator
```

This will skip all tests in the file rather than erroring at collection, which is the correct behavior for TDD red-phase tests.

---

_Reviewed: 2026-10-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
