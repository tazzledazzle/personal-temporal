---
phase: 03-saga-compensation
reviewed: 2026-10-07T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - tests/test_compensation.py
  - app/runs/compensator.py
  - app/runs/executor.py
  - app/runs/schemas.py
findings:
  critical: 3
  warning: 5
  info: 2
  total: 10
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-10-07
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the full saga compensation implementation: `CompensationCoordinator` (compensator.py), the `execute_run` background task (executor.py), run/step response schemas (schemas.py), and the compensation test suite (test_compensation.py).

The overall architecture is sound — LIFO ordering, continue-on-failure semantics, dependency-injected HTTP client and session, and the persist-before-dispatch invariant are all correctly implemented in intent. However, three critical defects were found:

1. `execute_run` does not catch `httpx.RequestError` (network failures) — only `TimeoutException` is caught. Any DNS failure, connection refused, or protocol error leaves the run stuck in `RUNNING` permanently, bypassing compensation entirely.
2. The `compensate()` final commit that sets `run.status = COMPENSATED` is not guarded against exceptions. A DB write failure here silently leaves the run stuck as `FAILED` with no signal to the caller, even though per-step compensation may have already been applied and committed.
3. `WorkflowRun.status` column comment and `RunResponse` schema do not enumerate `COMPENSATED` and `COMPENSATION_FAILED` as valid states, creating a self-contradictory schema contract and no Pydantic-level enforcement.

Five warnings cover: deprecated `datetime.utcnow()` used throughout, unasserted workflow-registration responses in every test, a dead `step_c` variable with no assertion, a fragile LIFO-order test that does not guard against empty `call_order`, and `run.completed_at` being committed twice (once in executor, once in compensator) with no comment explaining the intentional override.

---

## Critical Issues

### CR-01: `httpx.RequestError` not caught in `execute_run` — network failures leave run stuck in RUNNING permanently

**File:** `app/runs/executor.py:104`

**Issue:** The `try/except` block at lines 78–113 of `executor.py` only catches `httpx.TimeoutException`. The broader `httpx.RequestError` class covers all transport-level failures: `ConnectError` (connection refused, DNS failure), `RemoteProtocolError`, `ReadError`, `WriteError`, and others. If a step's `execute_url` is unreachable for any reason other than a timeout, the exception propagates out of the `for step in wf.steps:` loop, out of the `async with httpx.AsyncClient():` block, and out of `execute_run` entirely. FastAPI's `BackgroundTasks` runner catches and swallows this exception silently. The run remains in `RUNNING` status with `current_step_index` pointing to the failed step. No compensation is triggered. The caller polling `GET /runs/{run_id}` sees `RUNNING` indefinitely.

```python
# executor.py — only TimeoutException is caught, leaving ConnectError etc. unhandled:
except httpx.TimeoutException:
    ...
    await CompensationCoordinator(session, http_client).compensate(run)
    return
# httpx.ConnectError, httpx.RemoteProtocolError, etc. are NOT caught here
```

**Fix:** Add `httpx.RequestError` as a second except clause (or broaden the existing one):

```python
except httpx.TimeoutException:
    error_msg = f"Timeout after {timeout}s"
    async with _write_lock:
        step_exec.status = "FAILED"
        step_exec.error_detail = error_msg
        step_exec.completed_at = datetime.utcnow()
        run.status = "FAILED"
        run.error_detail = f"Step '{step.name}' {error_msg}"
        run.completed_at = datetime.utcnow()
        await session.commit()
    await CompensationCoordinator(session, http_client).compensate(run)
    return
except httpx.RequestError as exc:
    error_msg = f"Network error: {exc.__class__.__name__}: {exc}"
    async with _write_lock:
        step_exec.status = "FAILED"
        step_exec.error_detail = error_msg[:500]
        step_exec.completed_at = datetime.utcnow()
        run.status = "FAILED"
        run.error_detail = f"Step '{step.name}' {error_msg[:500]}"
        run.completed_at = datetime.utcnow()
        await session.commit()
    await CompensationCoordinator(session, http_client).compensate(run)
    return
```

---

### CR-02: `compensate()` final run-status commit is unguarded — DB write failure leaves run stuck as FAILED with partial compensation silently applied

**File:** `app/runs/compensator.py:99-106`, `app/runs/executor.py:102,113`

**Issue:** Inside `compensate()`, per-step compensation outcomes are committed one at a time (lines 92–93) — these individual commits persist partial progress. The final commit at lines 105–106 sets `run.status = COMPENSATED` or `COMPENSATION_FAILED`. If this final commit raises `SQLAlchemyError` (e.g., disk full, lock contention), the exception propagates up to the `execute_run` call site at line 102 (or 113) of `executor.py`. There is no `try/except` wrapping either `compensate()` call in `executor.py`:

```python
# executor.py:102 — no exception handling:
await CompensationCoordinator(session, http_client).compensate(run)
return
```

The `BackgroundTask` runner swallows the unhandled exception. The result: the run remains with `status = FAILED` and some/all steps show `compensation_status = COMPLETED` — an inconsistent state with no recovery path. A caller querying `GET /runs/{id}` cannot distinguish "compensation never triggered" from "compensation applied but final status write failed."

**Fix:** Wrap both `compensate()` call sites in `executor.py` with a broad handler that logs without re-raising:

```python
try:
    await CompensationCoordinator(session, http_client).compensate(run)
except Exception as exc:
    import structlog
    log = structlog.get_logger()
    log.error(
        "compensation_error",
        run_id=run_id,
        error=str(exc),
        error_type=type(exc).__name__,
    )
return
```

Additionally, wrap the final commit inside `compensate()` to prevent the unhandled-exception scenario:

```python
try:
    async with _write_lock:
        await self.session.commit()
except Exception as exc:
    # Per-step commits already persisted; log the aggregate-status failure
    # so operators know the run is in a partial state.
    raise  # let executor's try/except log it
```

---

### CR-03: `WorkflowRun.status` comment and `RunResponse` schema omit `COMPENSATED` / `COMPENSATION_FAILED` — schema contract is self-contradictory

**File:** `app/runs/models.py:24`, `app/runs/schemas.py:35-52`

**Issue:** `WorkflowRun.status` is documented in a comment as `# PENDING | RUNNING | COMPLETED | FAILED`. `CompensationCoordinator` writes two additional values — `COMPENSATED` and `COMPENSATION_FAILED` — that are not listed. Any developer reading the model believes only four states exist. `RunResponse.status` is typed as `str` with no constraint, so Pydantic will serialize any string from the DB column without validation. If an operator or downstream consumer builds a state machine against the documented four states, they will encounter unhandled values at runtime.

**Fix — models.py:**

```python
# PENDING | RUNNING | COMPLETED | FAILED | COMPENSATED | COMPENSATION_FAILED
status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
```

**Fix — schemas.py (add enum constraint):**

```python
from typing import Literal

class RunResponse(BaseModel):
    id: str
    workflow_def_id: str
    status: Literal[
        "PENDING", "RUNNING", "COMPLETED", "FAILED",
        "COMPENSATED", "COMPENSATION_FAILED",
    ]
    current_step_index: int
    input_payload: dict | str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_detail: str | None
    model_config = {"from_attributes": True}

    @field_validator("input_payload", mode="before")
    @classmethod
    def parse_input_payload(cls, v: Any) -> dict | None:
        if isinstance(v, str):
            return json.loads(v)
        return v
```

---

## Warnings

### WR-01: `datetime.utcnow()` is deprecated since Python 3.12 — used throughout executor and compensator

**File:** `app/runs/compensator.py:80,84,89,104` and `app/runs/executor.py:58,88,95,100,108,110,119`

**Issue:** `datetime.utcnow()` returns a naive (timezone-unaware) datetime and is formally deprecated in Python 3.12. The project targets Python 3.11+ but the deprecation warning is visible in 3.12 logs and the pattern produces naive datetimes stored in SQLite with no timezone annotation. Code comparing these timestamps to `datetime.now()` (local time) or `datetime.now(timezone.utc)` will silently produce incorrect deltas.

**Fix:** Replace all occurrences with `datetime.now(timezone.utc)` and add `timezone` to the import:

```python
from datetime import datetime, timezone

# Everywhere datetime.utcnow() appears:
datetime.now(timezone.utc)
```

Note: SQLAlchemy `DateTime` without `timezone=True` stores the value without TZ info regardless. Either use `DateTime(timezone=True)` on all timestamp columns or document that all values are UTC-naive by convention.

---

### WR-02: `run.completed_at` is committed twice — once in `executor.py` and again in `compensator.py` — with no comment explaining the intentional override

**File:** `app/runs/executor.py:100`, `app/runs/compensator.py:104`

**Issue:** When a step fails, `executor.py` commits `run.completed_at = datetime.utcnow()` at line 100 alongside `run.status = "FAILED"`. Then `compensate()` sets `run.completed_at = datetime.utcnow()` again at line 104 of `compensator.py` when writing the final `COMPENSATED` / `COMPENSATION_FAILED` status. The second write is semantically correct (the compensator timestamp is the true terminal time), but the pattern is confusing — a future developer might remove the second assignment believing `completed_at` was already set, breaking the terminal timestamp for compensated runs. The first `completed_at` assignment in executor.py is also technically premature because the run is not truly complete at the point of step failure — compensation still needs to run.

**Fix:** Remove `run.completed_at` from the failure commit in `executor.py` and let `compensate()` be the sole setter for `completed_at` on failure paths. Add a comment in `compensator.py` making this explicit:

```python
# compensator.py:104 — this is the authoritative terminal timestamp for all failure paths
run.completed_at = datetime.now(timezone.utc)
```

And in `executor.py`, remove `run.completed_at = datetime.utcnow()` from the FAILED commit blocks (lines 100 and 110), setting it only in the COMPLETED path (line 119) or deferring it entirely to the compensator for failure paths.

---

### WR-03: Workflow registration not asserted in any compensation test — silent 409 breaks subsequent assertions at the wrong layer

**File:** `tests/test_compensation.py:42,60,87,109,131,145`

**Issue:** Every test calls `await client.post("/workflows", json=COMP_WORKFLOW)` and discards the return value. Each test relies on the `test_engine` fixture (function-scoped) to provide an empty database, so the first run succeeds. If the fixture scope is ever changed, or if the registration endpoint returns a non-success status for any reason, the subsequent `POST /workflows/comp-wf/runs` will return 404 and `response.json()["run_id"]` will raise `KeyError` — the failure message will implicate the run endpoint, not the registration step.

**Fix:** Assert registration in every test:

```python
reg = await client.post("/workflows", json=COMP_WORKFLOW)
assert reg.status_code in (200, 201), f"Workflow registration failed: {reg.status_code} {reg.text}"
```

---

### WR-04: `test_compensation_lifo_order` does not guard against empty `call_order` — a wiring failure produces a confusing assertion message

**File:** `tests/test_compensation.py:80-82`

**Issue:** The final assertion is `assert call_order == ["comp-b", "comp-a"]`. If the compensator is never invoked (e.g., executor wiring is missing, or `respx.mock` scope mismatch), `call_order` will be `[]` and the assertion message will be `Expected LIFO order [comp-b, comp-a], got []` — which does not distinguish "compensation never ran" from "compensation ran in the wrong order." A developer seeing `got []` will waste time chasing a mock or import issue rather than an ordering bug.

**Fix:** Add a length assertion before the order assertion:

```python
assert len(call_order) == 2, (
    f"Expected 2 compensation calls but got {len(call_order)}: {call_order}. "
    "Check that CompensationCoordinator is wired into execute_run."
)
assert call_order == ["comp-b", "comp-a"], (
    f"Expected LIFO order [comp-b, comp-a], got {call_order}"
)
```

---

### WR-05: `test_compensation_skips_steps_without_compensate_url` assigns `step_c` but never asserts on it — the no-compensate-url contract is untested

**File:** `tests/test_compensation.py:120-126`

**Issue:** `step_c` is assigned at line 120 (with a `None` default) and then never used. The comment on lines 119–121 describes the expected behavior ("step-c has no compensate_url so its compensation_status is None"), but no assertion enforces it. If the compensator incorrectly sets `compensation_status` on step-c, this test will not catch it. Additionally, the comment "step-c completed before failing" is inaccurate: in this test's mock setup, `exec-c` returns HTTP 500, so step-c **failed** — it did not complete. Only `COMPLETED` steps are queried for compensation, so step-c is correctly excluded from the compensator's query regardless — but the comment creates confusion about why.

**Fix:**

```python
# step-c received HTTP 500 — it FAILED, so compensation is never attempted on it
if step_c is not None:
    assert step_c["compensation_status"] is None, (
        f"step-c should have no compensation_status (it failed, not completed), "
        f"got {step_c['compensation_status']}"
    )
```

---

## Info

### IN-01: `RunResponse` exposes `workflow_def_id` but the POST endpoint returns a raw `{"run_id": str}` dict — API shape inconsistency is undocumented

**File:** `app/runs/schemas.py:35-44`, `app/runs/router.py:39` (for context)

**Issue:** `POST /workflows/{name}/runs` returns `{"run_id": run.id}` (a raw dict), not a `RunResponse`. `GET /runs/{run_id}` returns `RunResponse` which has an `id` field (not `run_id`). Tests use `response.json()["run_id"]` for the POST response, then `run_response.json()["id"]` would be needed for GET (though the tests only check `status`, not `id`). This inconsistency is a latent consumer-experience issue: callers using the POST response shape will expect `run_id`, but callers introspecting the OpenAPI spec for the GET schema will find `id`.

**Suggestion:** Either align the POST response to return `RunResponse` (with HTTP 201), or define a minimal `StartRunResponse` schema with `run_id: str` and use it as the POST response model. At minimum, add a docstring to the POST router handler noting the intentional shape difference.

---

### IN-02: `input_payload` field validator in `RunResponse` does not handle `json.JSONDecodeError` — malformed DB data raises unhandled 500

**File:** `app/runs/schemas.py:46-51`

**Issue:** `parse_input_payload` calls `json.loads(v)` on line 50 without a try/except. If `input_payload` is stored as a malformed JSON string in the database (e.g., due to a bug during write or direct DB manipulation), `json.loads()` will raise `json.JSONDecodeError`, which propagates through Pydantic validation and causes `GET /runs/{run_id}` to return HTTP 500 with an unhandled exception traceback. This is a data-integrity edge case, but the failure mode is opaque.

**Suggestion:** Wrap the parse with error handling:

```python
@field_validator("input_payload", mode="before")
@classmethod
def parse_input_payload(cls, v: Any) -> dict | None:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return {"_raw": v, "_error": "malformed JSON in storage"}
    return v
```

Or raise a `ValueError` with a clear message so Pydantic surfaces a 422 instead of a 500.

---

_Reviewed: 2026-10-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
