---
phase: 03-saga-compensation
verified: 2026-10-07T00:00:00Z
status: gaps_found
score: 1/4 must-haves verified
overrides_applied: 0
gaps:
  - truth: "When any step fails, the executor automatically compensates all previously-completed steps in strict reverse-completion order"
    status: failed
    reason: "app/runs/compensator.py does not exist. CompensationCoordinator is not implemented. executor.py has no compensation logic — on step failure it sets run.status='FAILED' and returns immediately with no compensate_url calls."
    artifacts:
      - path: "app/runs/compensator.py"
        issue: "MISSING — module does not exist"
      - path: "app/runs/executor.py"
        issue: "Exits on step failure (line 101: return) with no compensation call chain"
    missing:
      - "Create app/runs/compensator.py with CompensationCoordinator class implementing LIFO compensate_url dispatch"
      - "Wire CompensationCoordinator into executor.py execute_run on step failure path"

  - truth: "Compensation continues even if individual compensate calls fail"
    status: failed
    reason: "No compensation implementation exists. The continue-on-failure behavior is not present in any module."
    artifacts:
      - path: "app/runs/compensator.py"
        issue: "MISSING"
    missing:
      - "CompensationCoordinator must catch per-step compensation errors, record them, and continue to the next step"

  - truth: "All outcomes are recorded per-step (compensated_at on success, compensation_error on failure, final run status COMPENSATED or COMPENSATION_FAILED)"
    status: failed
    reason: "ORM model columns exist (compensation_status, compensated_at, compensation_error in models.py lines 60-62) but are never written. StepExecutionResponse schema (app/runs/schemas.py) does not expose these fields — they are omitted from API responses. Run status values COMPENSATED and COMPENSATION_FAILED are referenced only in a notin_() filter in workflows/repository.py and are never set by any executor logic."
    artifacts:
      - path: "app/runs/schemas.py"
        issue: "StepExecutionResponse missing compensation_status, compensated_at, compensation_error fields — Pydantic will silently drop ORM values; tests will raise KeyError"
      - path: "app/runs/executor.py"
        issue: "Never writes to compensation_status, compensated_at, or compensation_error columns; never sets run.status to COMPENSATED or COMPENSATION_FAILED"
    missing:
      - "Add compensation_status, compensated_at, compensation_error to StepExecutionResponse in app/runs/schemas.py"
      - "Set run.status to COMPENSATED or COMPENSATION_FAILED after compensation chain completes"

  - truth: "6 compensation tests in tests/test_compensation.py import and pass against a real CompensationCoordinator"
    status: failed
    reason: "tests/test_compensation.py exists with 6 real test functions and 6 async with respx.mock: blocks (Wave 1 RED gate is complete and verified). However, the tests fail at collection time with ModuleNotFoundError: No module named 'app.runs.compensator'. They cannot pass until Wave 2 (implementation) is complete."
    artifacts:
      - path: "tests/test_compensation.py"
        issue: "File is substantive (not a stub) — 6 real assertions with proper respx patterns. But all 6 tests error at pytest collection; none pass."
    missing:
      - "Implement Wave 2: app/runs/compensator.py, executor.py update, schemas.py update"
---

# Phase 03: Saga Compensation — Verification Report

**Phase Goal:** When any step fails, the executor automatically compensates all previously-completed steps in strict reverse-completion order; compensation continues even if individual compensate calls fail; all outcomes are recorded per-step.
**Verified:** 2026-10-07
**Status:** GAPS FOUND
**Re-verification:** No — initial verification

---

## Context: Two-Wave Phase, One Wave Complete

Phase 3 was designed as a two-wave TDD cycle. Wave 1 (RED gate) is the only plan written and executed.
Wave 2 (GREEN gate — implementation) has not been planned or executed.

- Wave 1 complete: `tests/test_compensation.py` exists with 6 failing tests (RED gate confirmed)
- Wave 2 absent: `app/runs/compensator.py` does not exist; `executor.py` has no compensation logic

The ROADMAP.md progress table marks Phase 3 as "Complete (2026-10-07)" — this is incorrect. The phase
goal requires observable behavior in the running service, not only a test file.

---

## Goal Achievement

### Observable Truths (Phase Goal — Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `GET /runs/{run_id}/steps` shows previously-completed steps' compensate_url called in LIFO order when any step fails | FAILED | executor.py exits on failure (line 101 `return`) with no compensate_url dispatch; compensator module is absent |
| 2 | A 5xx compensation response does not stop the remaining compensation chain | FAILED | No compensation chain exists anywhere in the codebase |
| 3 | `GET /runs/{run_id}/steps` records `compensated_at` and `compensation_error` per step | FAILED | ORM columns exist but are never written; schema response excludes them |
| 4 | `GET /runs/{run_id}` shows `COMPENSATED` or `COMPENSATION_FAILED` based on outcome | FAILED | These status values exist only in a notin_() filter (workflows/repository.py:64); never assigned |

**Score: 0/4 roadmap truths verified**

### Plan Frontmatter Must-Haves (Wave 1 RED Gate Truths)

These truths are scoped to Wave 1 only. They do NOT cover the phase goal — they confirm only that
the RED gate was correctly committed.

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `pytest tests/test_compensation.py --collect-only` exits with ImportError (RED gate confirmed) | VERIFIED | Confirmed: `ModuleNotFoundError: No module named 'app.runs.compensator'` — exit code 1 |
| 2 | `tests/test_compensation.py` exists with 6 real assertions — not empty stubs | VERIFIED | File exists, 159 lines, 6 test functions each with real assertions against compensation_status, compensated_at, compensation_error, run status |
| 3 | All tests use `async with respx.mock:` context manager (not @respx.mock decorator) | VERIFIED | `grep -c 'async with respx.mock'` → 6 |
| 4 | LIFO order test captures call_order via side_effect callbacks | VERIFIED | Lines 63-82: two async side_effect functions record to call_order list |

**Wave 1 score: 4/4 — RED gate is complete and correctly structured**

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_compensation.py` | RED gate: 6 failing tests importing CompensationCoordinator | VERIFIED | Exists, 159 lines, 6 test functions, correct import at line 15 |
| `app/runs/compensator.py` | CompensationCoordinator: LIFO dispatch, continue-on-failure, outcome recording | MISSING | File does not exist — `ls app/runs/` confirms absence |
| `app/runs/executor.py` (updated) | Calls CompensationCoordinator on step failure instead of returning | STUB | Exists but compensation call absent; step failure path exits at line 101 with no rollback |
| `app/runs/schemas.py` (updated) | StepExecutionResponse includes compensation_status, compensated_at, compensation_error | MISSING | Three fields absent from schema; ORM values would be silently dropped by Pydantic |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tests/test_compensation.py` | `app.runs.compensator` | `from app.runs.compensator import CompensationCoordinator` | NOT_WIRED | Import produces ModuleNotFoundError; RED gate intentional |
| `app/runs/executor.py` | `app.runs.compensator` | CompensationCoordinator call on step failure | NOT_WIRED | No import or call of any compensation module in executor.py |
| `app/runs/executor.py` | run.status = "COMPENSATED" / "COMPENSATION_FAILED" | Direct assignment after compensation chain | NOT_WIRED | Only "FAILED" and "COMPLETED" are ever assigned in executor.py |
| `app/runs/schemas.py` | `WorkflowStepExecution` compensation columns | Field declarations in StepExecutionResponse | NOT_WIRED | Three ORM columns exist in models.py but have no matching schema fields |

---

## Data-Flow Trace (Level 4)

Not applicable — no compensation data flows at all. The `compensation_status`, `compensated_at`,
and `compensation_error` ORM columns exist in `app/runs/models.py` (lines 60-62) and are correctly
defined, but no code path ever writes to them. The `StepExecutionResponse` schema does not include
them, so even if they were written they would not reach the API consumer.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| pytest RED gate confirmed | `pytest tests/test_compensation.py --collect-only` | exit 1, ModuleNotFoundError | PASS (RED gate correct) |
| Existing 20 tests unaffected | `pytest tests/ --ignore=tests/test_compensation.py -x -q` | 20 passed, exit 0 | PASS |
| Compensation tests pass | `pytest tests/test_compensation.py -q` | Cannot run — collection fails | FAIL |

---

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|---------|
| COMP-01 | When any step fails, executor calls each previously-completed step's compensate_url in reverse order; no compensate_url steps silently skipped; continues on individual failure | BLOCKED | executor.py has no compensate_url dispatch logic; compensator module absent |
| COMP-02 | Per-step compensation outcome recorded; final run status reflects whether compensation succeeded | BLOCKED | ORM columns exist but never written; schema excludes them; COMPENSATED/COMPENSATION_FAILED never set |

Both requirements declared in PLAN frontmatter are BLOCKED. REQUIREMENTS.md marks both as
"Complete" in the traceability table — this is premature. The checkboxes at lines 19-20 of
REQUIREMENTS.md mark COMP-01 and COMP-02 complete, but no implementation supports them.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/runs/executor.py` | 101 | `return` on step failure with no compensation call | BLOCKER | Phase goal not achievable until this branch invokes compensation |
| `app/runs/schemas.py` | — | Compensation fields absent from StepExecutionResponse | BLOCKER | Tests will raise KeyError even after compensator is implemented |
| `.planning/ROADMAP.md` | 19 | Phase 3 marked `[x]` Complete (2026-10-07) | WARNING | Phase goal not achieved; marking it complete is misleading |
| `.planning/REQUIREMENTS.md` | 19-20 | COMP-01 and COMP-02 marked `[x]` complete | WARNING | Traceability table is incorrect; requirements not yet satisfied |

---

## Human Verification Required

None. All gaps are programmatically observable (missing files, missing schema fields, absent
executor logic).

---

## Gaps Summary

Phase 3 has two waves. Wave 1 (TDD RED gate) is complete and correctly implemented:
`tests/test_compensation.py` exists with 6 substantive test functions, all using
`async with respx.mock:`, and pytest confirms the expected `ModuleNotFoundError` at collection.

Wave 2 (implementation) has not been planned or executed. Three categories of work are missing:

**1. Compensator module absent**
`app/runs/compensator.py` does not exist. `CompensationCoordinator` (or equivalent) must be
created implementing: LIFO iteration over completed steps, per-step HTTP POST to compensate_url,
continue-on-failure error handling, and per-step outcome recording.

**2. Executor not updated**
`executor.py` returns immediately on step failure (line 101) with `run.status = "FAILED"`.
It must instead call the compensator, then set `run.status` to `COMPENSATED` or
`COMPENSATION_FAILED` based on the compensation chain result.

**3. Schema fields missing**
`StepExecutionResponse` in `app/runs/schemas.py` has no `compensation_status`, `compensated_at`,
or `compensation_error` fields. Without these, compensation results written by the compensator
would be silently dropped by Pydantic and tests would raise KeyError.

The root cause is a single missing wave. All four roadmap success criteria fail from the same
source: the GREEN gate wave was never planned or executed.

---

_Verified: 2026-10-07_
_Verifier: Claude (gsd-verifier)_
