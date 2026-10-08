---
phase: 02-execution-engine
plan: "01"
subsystem: runs
tags: [tdd, red-gate, testing, respx]
dependency_graph:
  requires: []
  provides: [tests/test_runs.py RED gate, respx dev dep]
  affects: [pyproject.toml, tests/test_runs.py]
tech_stack:
  added: [respx==0.21.1]
  patterns: [respx async context manager mock, TDD RED gate]
key_files:
  created:
    - tests/test_runs.py
  modified:
    - pyproject.toml
decisions:
  - Use respx context manager (not decorator) for explicit lifecycle control during BackgroundTasks
  - test_runs.py imports from app.runs.schemas which does not exist — intentional RED ImportError
metrics:
  duration: "< 5 minutes"
  completed: "2026-10-07"
---

# Phase 02 Plan 01: TDD RED Gate — respx + test_runs.py Summary

Wave 1 RED gate: added `respx==0.21.1` to dev deps and created `tests/test_runs.py` with 7 failing tests that import from `app.runs.schemas` (which does not yet exist), confirming pytest exits non-zero with `ModuleNotFoundError`.

## What Was Done

### Task 1: Add respx to pyproject.toml + write tests/test_runs.py (RED)

1. Added `respx==0.21.1` to `[project.optional-dependencies]` dev group in `pyproject.toml`.
2. Created `tests/test_runs.py` with 7 async test functions covering:
   - `test_start_run_returns_202` — POST /workflows/{name}/runs returns 202 with run_id
   - `test_run_completes_successfully` — run status reaches COMPLETED after BackgroundTasks
   - `test_get_run_returns_200` — GET /runs/{run_id} returns expected fields
   - `test_get_run_steps` — GET /runs/{run_id}/steps returns 2 steps with correct fields
   - `test_step_timeout_fails_run` — httpx.TimeoutException causes FAILED status
   - `test_step_failure_fails_run` — HTTP 500 from step causes FAILED status
   - `test_get_missing_run_returns_404` — nonexistent run_id returns 404
3. Installed `respx==0.21.1` via pip.
4. Confirmed RED gate: `pytest tests/test_runs.py --collect-only` exits non-zero with `ModuleNotFoundError: No module named 'app.runs.schemas'`.
5. Confirmed all 13 existing tests still pass.

## Acceptance Criteria Verification

| Criterion | Result |
|-----------|--------|
| `grep -c 'respx' pyproject.toml` >= 1 | 1 |
| `grep -c 'test_' tests/test_runs.py` >= 7 | 7 |
| `grep -c 'async with respx.mock' tests/test_runs.py` >= 6 | 7 |
| `pytest tests/test_runs.py --collect-only` exits non-zero with ImportError/ModuleNotFoundError | 2 occurrences |
| Existing 13 tests pass | 13 passed |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — `tests/test_runs.py` contains real assertions. `app.runs.schemas` intentionally does not exist yet; it will be created in Plan 02-02.

## TDD Gate Compliance

- RED gate commit: N/A (plan instructs "Do NOT use git commit — report changed files only")
- RED phase confirmed: `ModuleNotFoundError: No module named 'app.runs.schemas'` on collection

## Changed Files

- `/Users/terenceschumacher/dev/october-portfolio-projects/10-7-26-interview/pyproject.toml` — added `respx==0.21.1` to dev deps
- `/Users/terenceschumacher/dev/october-portfolio-projects/10-7-26-interview/tests/test_runs.py` — created with 7 RED tests

## Self-Check: PASSED

- [x] `tests/test_runs.py` exists and has 7 test functions
- [x] `pyproject.toml` contains `respx==0.21.1`
- [x] RED gate confirmed: `ModuleNotFoundError: No module named 'app.runs.schemas'`
- [x] 13 existing tests pass
