---
phase: 2
slug: execution-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-07
---

# Phase 2 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.4.x + httpx 0.28.x + respx 0.21.x |
| **Config file** | `pyproject.toml` (asyncio_mode = "auto") |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~8 seconds |

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v --tb=short`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| Start run (202) | 02-01 | 1 | EXEC-01 | integration | `pytest tests/test_runs.py::test_start_run_returns_202 -x -q` | ⬜ pending |
| Run completes (happy path) | 02-02 | 2 | EXEC-01 | integration | `pytest tests/test_runs.py::test_run_completes_successfully -x -q` | ⬜ pending |
| Get run status | 02-02 | 2 | EXEC-02 | integration | `pytest tests/test_runs.py::test_get_run_returns_200 -x -q` | ⬜ pending |
| Get step history | 02-02 | 2 | EXEC-03 | integration | `pytest tests/test_runs.py::test_get_run_steps -x -q` | ⬜ pending |
| Step timeout | 02-02 | 2 | RESIL-02 | integration | `pytest tests/test_runs.py::test_step_timeout_fails_run -x -q` | ⬜ pending |
| Non-2xx step fails run | 02-02 | 2 | EXEC-01 | integration | `pytest tests/test_runs.py::test_step_failure_fails_run -x -q` | ⬜ pending |
| Persistence across restart | 02-02 | 2 | RESIL-01 | integration | `pytest tests/test_runs.py::test_run_persists -x -q` | ⬜ pending |

## Wave 0 Requirements

- [ ] `tests/test_runs.py` — stubs: test_start_run_returns_202, test_run_completes_successfully, test_get_run_returns_200, test_get_run_steps, test_step_timeout_fails_run, test_step_failure_fails_run, test_get_missing_run_returns_404
- [ ] `pyproject.toml` — add `respx==0.21.1` to dev dependencies

## Manual-Only Verifications

| Behavior | Requirement | Why Manual |
|----------|-------------|------------|
| Concurrent runs don't corrupt state | RESIL-04 | Requires multi-coroutine load test |
| Run persists across uvicorn restart | RESIL-01 | Requires process lifecycle test |

## Validation Sign-Off

- [ ] All tasks have automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s

**Approval:** pending
