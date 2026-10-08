---
phase: 02-execution-engine
plan: "02"
subsystem: runs
tags: [execution-engine, saga, background-tasks, sqlalchemy, httpx, respx]
dependency_graph:
  requires: [02-01]
  provides: [EXEC-01, EXEC-02, EXEC-03, RESIL-01, RESIL-02]
  affects: [app/runs, tests/conftest.py]
tech_stack:
  added:
    - respx==0.23.1 (upgraded from 0.21.1 — incompatible with httpcore 1.0.9)
  patterns:
    - self-import pattern for module-level patchable AsyncSessionLocal
    - persist-before-dispatch: commit RUNNING state before HTTP call
    - background task session isolation: executor owns its own AsyncSession
    - field_validator mode="before" for JSON blob parsing in Pydantic v2
key_files:
  created:
    - app/runs/schemas.py
    - app/runs/repository.py
    - app/runs/executor.py
    - app/runs/router.py
    - migrations/versions/0002_add_step_executions.py
  modified:
    - app/runs/models.py (REPLACED — expanded stub with WorkflowStepExecution)
    - app/main.py (added runs_router)
    - tests/conftest.py (added test_engine fixture, executor patch)
    - pyproject.toml (respx 0.21.1 -> 0.23.1)
decisions:
  - "Upgraded respx from 0.21.1 to 0.23.1: respx 0.21.1 incompatible with httpcore 1.0.9 — httpcore now sends method as bytes (b'POST') but respx Method.parse compared against string 'POST', causing AllMockedAssertionError on every mock route lookup"
  - "RunResponse uses field_validator(mode='before') instead of model_validate override: Pydantic v2 validates input_payload as dict before custom override code could run, causing ValidationError on string JSON blob from DB"
  - "error_detail timeout message uses 'timeout' (not 'timed out') to satisfy test assertion: 'timeout' in error_detail.lower()"
metrics:
  duration: "~15 minutes"
  completed: "2026-10-07"
  tasks_completed: 4
  files_changed: 9
---

# Phase 02 Plan 02: Execution Engine Summary

Async workflow execution engine with per-step HTTP dispatch, persist-before-dispatch commit semantics, and full test coverage via respx mocking. All 20 tests pass.

## What Was Built

Implemented the full execution engine for the Multi-Step Workflow Executor:

- **WorkflowRun model** expanded from stub: added `current_step_index`, `input_payload`, `started_at`, `completed_at`, `error_detail`; retained `created_at` and `version` from Phase 1 stub
- **WorkflowStepExecution model** (new): per-step execution history with `status`, `http_status_code`, `error_detail`, Phase 3 compensation stubs
- **RunRepo**: `create`, `get_by_id`, `list_steps_by_run_id` with `_write_lock` on writes
- **execute_run background task**: drives PENDING→RUNNING→COMPLETED/FAILED; persist-before-dispatch on every state transition; self-import pattern makes `AsyncSessionLocal` patchable for test isolation
- **Runs router**: `POST /workflows/{name}/runs` (202), `GET /runs/{id}` (200/404), `GET /runs/{id}/steps` (200/404)
- **conftest.py refactored**: `test_engine` fixture shared by `db_session`, `client`, and `client_no_auth`; `client` patches `app.runs.executor.AsyncSessionLocal` to test engine
- **Alembic migration 0002**: expands workflow_runs, creates workflow_step_executions

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] respx 0.21.1 incompatible with httpcore 1.0.9**
- **Found during:** Task 1 verification run (first test execution)
- **Issue:** `respx.mock` intercepted HTTP calls but could not match routes. httpcore 1.0.9 passes method as bytes (`b'POST'`); respx 0.21.1 `Method.parse` returned bytes from `httpx.Request.method`; route pattern stored as string `'POST'`; bytes != string comparison always failed → `AllMockedAssertionError: RESPX: <Request(b'POST', ...)> not mocked!`
- **Fix:** Upgraded respx from 0.21.1 to 0.23.1 which handles bytes/string method comparison correctly. Updated `pyproject.toml` dev dependency.
- **Files modified:** `pyproject.toml`

**2. [Rule 1 - Bug] Pydantic v2 rejects string input_payload before custom override runs**
- **Found during:** Task 3a (test_run_completes_successfully failure)
- **Issue:** `RunResponse.model_validate` override called `super().model_validate()` first, which tried to validate `input_payload` as `dict` before the string→dict conversion. Pydantic v2 raised `ValidationError: Input should be a valid dictionary [input_value='{"key": "value"}']`
- **Fix:** Replaced `model_validate` override with `@field_validator("input_payload", mode="before")` which fires before type coercion. Changed field type to `dict | str | None` to allow string input.
- **Files modified:** `app/runs/schemas.py`

**3. [Rule 1 - Bug] error_detail string "timed out" did not satisfy "timeout" assertion**
- **Found during:** Task 3a (test_step_timeout_fails_run failure)
- **Issue:** Executor set `error_detail = f"Step '{step.name}' timed out after {timeout}s"`. Test asserts `"timeout" in body["error_detail"].lower()`. The string "timed out" does NOT contain the substring "timeout" as one word.
- **Fix:** Changed error message to `f"Step '{step.name}' timeout after {timeout}s"` which contains "timeout" as required.
- **Files modified:** `app/runs/executor.py`

## Threat Surface Scan

No new threat surface beyond what the plan's threat model documents:
- T-2-01 (SSRF on execute_url): execute_url validated at workflow creation; executor calls stored URL only
- T-2-02 (error_detail leakage): only HTTP status code and timeout message stored; step response body never captured
- T-2-03 (DoS via step duration): `httpx.Timeout(step.timeout_seconds or 30)` enforced
- T-2-04 (run_id guessable): `str(uuid4())` used for all run IDs
- T-2-05 (input_payload in DB): JSON blob stored in plaintext; accepted per threat register

## Known Stubs

None — all fields are wired and functional. Phase 3 compensation columns (`compensation_status`, `compensated_at`, `compensation_error`) are nullable DB columns intentionally left null until CompensationCoordinator is implemented in Phase 3.

## Self-Check

Files created:
- /Users/terenceschumacher/dev/october-portfolio-projects/10-7-26-interview/app/runs/schemas.py: FOUND
- /Users/terenceschumacher/dev/october-portfolio-projects/10-7-26-interview/app/runs/repository.py: FOUND
- /Users/terenceschumacher/dev/october-portfolio-projects/10-7-26-interview/app/runs/executor.py: FOUND
- /Users/terenceschumacher/dev/october-portfolio-projects/10-7-26-interview/app/runs/router.py: FOUND
- /Users/terenceschumacher/dev/october-portfolio-projects/10-7-26-interview/migrations/versions/0002_add_step_executions.py: FOUND

Acceptance criteria:
- pytest tests/ exits 0 (20 tests): PASSED
- grep -c '_write_lock' app/runs/executor.py >= 3: 7 (PASSED)
- grep -c 'TimeoutException' app/runs/executor.py >= 1: 1 (PASSED)
- grep -c 'lazy="selectin"' app/runs/models.py >= 1: 2 (PASSED)
- grep -c 'executor_module.AsyncSessionLocal' tests/conftest.py >= 1: 2 (PASSED)
- python -c "from app.main import app; print('OK')" exits 0: PASSED
- ls migrations/versions/0002_*.py: FOUND

## Self-Check: PASSED
