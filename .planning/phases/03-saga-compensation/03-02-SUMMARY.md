---
phase: "03"
plan: "02"
subsystem: saga-compensation
tags: [compensation, saga, executor, lifo, green-gate]
dependency_graph:
  requires: [03-01]
  provides: [CompensationCoordinator, compensation-runtime]
  affects: [app/runs/executor.py, app/runs/schemas.py]
tech_stack:
  added: []
  patterns: [saga-compensation, lifo-dispatch, continue-on-failure, dependency-injection]
key_files:
  created:
    - app/runs/compensator.py
  modified:
    - app/runs/executor.py
    - app/runs/schemas.py
decisions:
  - "CompensationCoordinator only updates run.status when at least one compensate_url was attempted — preserves FAILED semantics for workflows with no compensate_urls defined"
  - "attempted_steps tracking list distinguishes skipped steps (no compensate_url) from attempted ones for aggregate status calculation"
metrics:
  duration: "~12 minutes"
  completed: "2026-10-07"
  tasks: 4
  files_changed: 3
---

# Phase 03 Plan 02: Saga Compensation GREEN Gate Summary

Wave 2 GREEN gate: implemented the Saga compensation runtime that Wave 1 RED gate tests specify.

## What Was Built

Three concrete artifacts close the Phase 3 verification gap:

1. **`app/runs/compensator.py`** — `CompensationCoordinator` class implementing LIFO compensate_url dispatch with continue-on-failure semantics and per-step outcome recording.
2. **`app/runs/executor.py`** — Both failure branches (non-2xx HTTP response + timeout) now invoke `CompensationCoordinator(session, http_client).compensate(run)` before returning. The existing session and http_client objects are reused — no new sessions or clients created.
3. **`app/runs/schemas.py`** — `StepExecutionResponse` exposes `compensation_status`, `compensated_at`, `compensation_error` via Pydantic `from_attributes` ORM mapping.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create CompensationCoordinator | df9c7ac | app/runs/compensator.py |
| 2 | Wire coordinator into executor | ee046fb | app/runs/executor.py, app/runs/compensator.py (refined) |
| 3 | Expose compensation fields on schema | c42989f | app/runs/schemas.py |
| 4 | GREEN gate verification | — | (no file changes — 26 tests pass) |

## Test Results

- `pytest tests/test_compensation.py -q`: **6 passed, 0 failed**
- `pytest tests/ -q`: **26 passed, 0 failed**

All four COMP-01/COMP-02 behavioral truths from 03-VERIFICATION.md are now observable through the REST API.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Compensator must not overwrite run.status for workflows with no compensate_urls**

- **Found during:** Task 4 (pre-verification run of existing tests)
- **Issue:** The original compensator logic always set `run.status` to `COMPENSATED` after an empty step_execs loop, causing `test_step_timeout_fails_run` and `test_step_failure_fails_run` (which use workflows with no `compensate_url` defined) to fail because they assert `status == "FAILED"`.
- **Fix:** Track `attempted_steps` separately from `step_execs`. Only update `run.status` to `COMPENSATED`/`COMPENSATION_FAILED` when at least one compensation was actually attempted (i.e., a step had a non-null compensate_url). When zero compensations are attempted, leave `run.status` as `FAILED` (already set by executor before calling compensate).
- **Files modified:** `app/runs/compensator.py`
- **Commit:** ee046fb

## Known Stubs

None. All compensation fields are wired to live ORM data.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries were introduced. All new network calls (compensate_url POSTs) go outbound to caller-controlled URLs already in the workflow step definition.

## Self-Check: PASSED

- `app/runs/compensator.py` — EXISTS
- `app/runs/executor.py` — EXISTS
- `app/runs/schemas.py` — EXISTS
- Commit df9c7ac — EXISTS (feat(03-02): create CompensationCoordinator)
- Commit ee046fb — EXISTS (feat(03-02): wire CompensationCoordinator)
- Commit c42989f — EXISTS (feat(03-02): expose compensation fields on schema)
- 26 tests pass, 0 fail — VERIFIED
