---
phase: "01"
plan: "01"
subsystem: test-infrastructure
tags: [tdd, red-gate, pytest, conftest, pyproject]
dependency_graph:
  requires: []
  provides:
    - pyproject.toml with pinned deps and asyncio_mode=auto
    - tests/conftest.py with StaticPool engine and fixture set
    - 5 RED test files covering all Phase 1 requirements
  affects: []
tech_stack:
  added:
    - pytest==9.0.3
    - pytest-asyncio==1.4.0
    - httpx==0.28.1
    - pytest-cov==7.1.0
    - fastapi[standard]==0.142.2 (pinned in pyproject.toml)
    - sqlalchemy[asyncio]==2.1.4
    - aiosqlite==0.22.1
    - alembic==1.20.0
    - structlog==26.1.0
    - pydantic-settings==2.15.0
    - uvicorn[standard]==0.54.0
  patterns:
    - TDD RED gate — test files importing from non-existent app.* intentionally fail
    - StaticPool in-memory SQLite engine with WAL + busy_timeout PRAGMAs
    - ASGITransport for in-process async HTTP testing
    - dependency_overrides for db session injection in tests
key_files:
  created:
    - pyproject.toml
    - tests/conftest.py
    - tests/test_database.py
    - tests/test_auth.py
    - tests/test_health.py
    - tests/test_workflows.py
    - tests/test_logging.py
  modified: []
decisions:
  - "asyncio_mode=auto in pyproject.toml eliminates per-test @pytest.mark.asyncio decorator"
  - "StaticPool forces all async coroutines through one in-memory connection — prevents per-connection isolation issue"
  - "client_no_auth fixture is separate from client (not a parameter) for clarity at test call site"
  - "X-Correlation-ID header echo used as Phase 1 proxy for full structlog JSON output verification (deferred to Phase 4 integration tests)"
metrics:
  duration: "108 seconds"
  completed_date: "2026-10-07"
  tasks_completed: 2
  files_created: 7
---

# Phase 1 Plan 01: RED Gate Test Infrastructure Summary

**One-liner:** pytest-asyncio test harness with StaticPool conftest and 5 RED test files importing from non-existent app.* modules (exit code 4 confirms RED gate)

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | pyproject.toml + conftest.py test infrastructure | 96a0792 | pyproject.toml, tests/conftest.py |
| 2 | RED test stubs — all 5 test files | 5188e7e | tests/test_{database,auth,health,workflows,logging}.py |

## Artifacts Created

**pyproject.toml**
- `[build-system]` using setuptools
- `[project]` name="workflow-executor", version="0.1.0", requires-python=">=3.11"
- All 7 core deps pinned (fastapi, uvicorn, sqlalchemy, aiosqlite, alembic, structlog, pydantic-settings)
- `[project.optional-dependencies].dev` with 4 test packages
- `[tool.pytest.ini_options]`: asyncio_mode="auto", testpaths=["tests"]

**tests/conftest.py**
- `TEST_API_KEY = "test-api-key"` constant
- `db_session` fixture: StaticPool in-memory engine with WAL + busy_timeout PRAGMAs via `event.listens_for(engine.sync_engine, "connect")`, creates all tables, yields AsyncSession
- `client` fixture: overrides `get_db`, `AsyncClient` with `ASGITransport(app=app)` and `X-API-Key: test-api-key`
- `client_no_auth` fixture: same but without X-API-Key header

**Test files (all RED — app.* does not exist)**
- `test_database.py`: WAL mode PRAGMA assertion + asyncio.Lock isinstance check (RESIL-04)
- `test_auth.py`: 401 missing key, 401 wrong key, 200 valid key (PLAT-01)
- `test_health.py`: GET /health 200 + public access (PLAT-03)
- `test_workflows.py`: create 201, get 200, list 200, delete 204, 404 (DEFN-01/02/03)
- `test_logging.py`: x-correlation-id response header (PLAT-02)

## RED Gate Verification

```
$ pytest tests/ -x -q
ImportError while loading conftest 'tests/conftest.py'.
tests/conftest.py:15: in <module>
    from app.main import app
E   ModuleNotFoundError: No module named 'app'
Exit code: 4
```

pytest exits non-zero (4) — RED gate confirmed. No app.* implementation files created.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All test files have real assertions. conftest.py has no stub data.

## Threat Flags

None. This plan creates only test infrastructure files. No new network endpoints, auth paths, or production code introduced.

## TDD Gate Compliance

RED gate: PASS — `test(01-01)` commits exist before any implementation. pytest exits 4 (non-zero).
GREEN gate: Deferred to Plans 02 and 03.

## Self-Check: PASSED

- [x] pyproject.toml exists with asyncio_mode="auto"
- [x] tests/conftest.py exists with StaticPool, ASGITransport, dependency_overrides
- [x] All 5 test files exist with real assertions
- [x] pytest exits 4 (non-zero) — RED gate confirmed
- [x] Both task commits exist: 96a0792, 5188e7e
