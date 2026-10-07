---
phase: "01"
plan: "02"
subsystem: foundation-infrastructure
tags: [green-gate, fastapi, sqlalchemy, structlog, auth, tdd]
dependency_graph:
  requires:
    - "01-01 (pyproject.toml, tests/conftest.py, RED test files)"
  provides:
    - app/core/database.py with async engine factory, WAL PRAGMAs, asyncio.Lock, expire_on_commit=False
    - app/core/auth.py with verify_api_key using secrets.compare_digest
    - app/core/logging.py with configure_structlog and CorrelationIdMiddleware
    - app/core/config.py with pydantic-settings Settings and get_settings()
    - app/health/router.py GET /health public endpoint (200/503)
    - app/main.py FastAPI app with lifespan, middleware, stub workflows router
    - app/runs/models.py WorkflowRun stub model for DEFN-03 active-run guard
    - Dockerfile with --workers 1 (single-worker constraint)
    - docker-compose.yml with named volume db_data
    - alembic.ini + migrations/env.py + script.py.mako Alembic async scaffold
  affects:
    - tests/conftest.py (updated db_session to use temp-file SQLite for WAL compatibility)
tech_stack:
  added:
    - fastapi[standard]==0.142.2 (upgraded from 0.136.1 already installed)
    - sqlalchemy[asyncio]==2.1.4 (upgraded from 2.0.51)
    - pydantic-settings==2.15.0 (upgraded from 2.14.1)
    - alembic==1.20.0 (already installed)
  patterns:
    - event.listens_for(engine.sync_engine, "connect") for PRAGMA injection (not engine directly)
    - expire_on_commit=False on async_sessionmaker (prevents DetachedInstanceError)
    - asyncio.Lock() at module level for write serialization (RESIL-04)
    - secrets.compare_digest() for timing-safe API key comparison (ASVS L1 / T-1-01)
    - clear_contextvars() before bind_contextvars() in middleware (prevents context leak)
    - @asynccontextmanager lifespan (deprecated on_event not used)
    - temp-file NullPool SQLite in tests (WAL requires on-disk file, not :memory:)
key_files:
  created:
    - app/__init__.py
    - app/core/__init__.py
    - app/core/config.py
    - app/core/database.py
    - app/core/auth.py
    - app/core/logging.py
    - app/core/exceptions.py
    - app/lifespan.py
    - app/main.py
    - app/health/__init__.py
    - app/health/router.py
    - app/runs/__init__.py
    - app/runs/models.py
    - app/workflows/__init__.py
    - Dockerfile
    - docker-compose.yml
    - .env.example
    - .env (local dev only, gitignored)
    - alembic.ini
    - migrations/env.py
    - migrations/script.py.mako
  modified:
    - tests/conftest.py (db_session: :memory: StaticPool → temp-file NullPool for WAL mode)
    - .gitignore (added Python __pycache__, .env, *.db-wal patterns)
decisions:
  - "WAL mode requires on-disk SQLite — tests/conftest.py updated to use NamedTemporaryFile + NullPool"
  - "secrets.compare_digest on api_key is None guard prevents TypeError before timing-safe compare"
  - "Module-level engine creation in database.py requires API_KEY in environment at import time — resolved via .env file (pydantic-settings auto-loads)"
  - "Stub GET /workflows router in main.py unblocks test_auth.py::test_valid_api_key_returns_200 until Plan 03 replaces it"
  - "CorrelationIdMiddleware uses BaseHTTPMiddleware — sufficient for Phase 1; note that BaseHTTPMiddleware can affect streaming responses in production (Phase 4 concern)"
metrics:
  duration: "284 seconds"
  completed_date: "2026-10-07"
  tasks_completed: 2
  files_created: 21
  files_modified: 2
---

# Phase 1 Plan 02: GREEN Gate — Core Infrastructure Summary

**One-liner:** FastAPI Walking Skeleton — async SQLite engine with WAL+busy_timeout PRAGMAs, secrets.compare_digest auth, structlog CorrelationIdMiddleware, and public health probe pass all 8 RED gate tests

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Core infrastructure (config, database engine, auth, logging, exceptions) | 305d1d6 | app/__init__.py, app/core/{__init__,config,database,auth,logging,exceptions}.py, tests/conftest.py |
| 2 | App factory, health endpoint, WorkflowRun stub, Alembic scaffold, Docker files | 6904d92 | app/lifespan.py, app/main.py, app/health/*, app/runs/*, app/workflows/__init__.py, Dockerfile, docker-compose.yml, .env.example, alembic.ini, migrations/* |

## GREEN Gate Verification

```
$ pytest tests/test_health.py tests/test_auth.py tests/test_database.py tests/test_logging.py -x -q
........
8 passed in 0.05s
```

All verification criteria from PLAN.md:

| Check | Result |
|-------|--------|
| `grep -c 'asyncio.Lock' app/core/database.py` | 2 (>= 1) |
| `grep -c 'secrets.compare_digest' app/core/auth.py` | 2 (>= 1) |
| `grep -c 'clear_contextvars' app/core/logging.py` | 3 (>= 1) |
| `grep -c 'expire_on_commit=False' app/core/database.py` | 3 (>= 1) |
| `grep -c -- '--workers 1' Dockerfile` | 1 |
| `grep -c 'db_data:' docker-compose.yml` | 2 (>= 1) |
| test_workflows.py still fails | YES (405 Method Not Allowed on POST — expected, Plan 03 handles it) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] conftest.py db_session fixture uses :memory: SQLite which cannot report WAL mode**

- **Found during:** Task 1 verification (test_wal_mode_active fails with 'memory' != 'wal')
- **Issue:** SQLite in-memory databases (`sqlite:///:memory:`) always report `journal_mode=memory` and silently ignore `PRAGMA journal_mode=WAL`. The Wave 1 conftest used `:memory:` with `StaticPool`, so the WAL PRAGMA was set but SQLite ignored it. The test correctly asserts `mode == "wal"` but in-memory SQLite cannot satisfy this.
- **Fix:** Updated `tests/conftest.py` `db_session` fixture to use a `NamedTemporaryFile` temp path with `NullPool` (same as production). This gives a real on-disk SQLite file where WAL mode is honoured. The file is cleaned up in fixture teardown via `os.unlink(tmp.name)`.
- **Files modified:** `tests/conftest.py`
- **Commit:** 305d1d6

**2. [Rule 2 - Missing critical functionality] .env file required for tests (API_KEY at module import time)**

- **Found during:** Task 1 first test run
- **Issue:** `app/core/database.py` executes `engine = create_engine(get_settings().database_url)` at module import time. `get_settings()` requires `API_KEY` to be set. Without a `.env` file or env var, import fails with a Pydantic ValidationError before any test runs.
- **Fix:** Created `.env` with `API_KEY=test-api-key` (matching `TEST_API_KEY` in conftest). Added `.env` to `.gitignore` (contains secrets). Created `.env.example` template per plan.
- **Files created:** `.env` (gitignored), `.env.example`, added `.env` pattern to `.gitignore`
- **Commit:** 305d1d6, 9889976

**3. [Rule 2 - Missing critical functionality] Stub GET /workflows router needed for test_auth.py**

- **Found during:** Task 1 planning — test_auth.py::test_valid_api_key_returns_200 calls GET /workflows expecting 200
- **Issue:** The plan notes this requirement: "Mount a placeholder workflows_router... stub with an empty router". Created `app/workflows/__init__.py` and wired a stub `GET /workflows` endpoint returning `[]` with `Security(verify_api_key)` in `app/main.py`.
- **Fix:** Added `_workflows_stub_router` inline in `app/main.py` (per plan's "OR mount directly in main.py with inline route returning []" option). Plan 03 will replace this.
- **Files created:** `app/workflows/__init__.py`, updated `app/main.py`
- **Commit:** 6904d92

## Known Stubs

- `app/main.py` `_workflows_stub_router` `GET /workflows` returns `[]` — intentional stub. Plan 03 replaces with full CRUD implementation. Tests rely on this returning 200 with empty list for auth verification only.
- `app/runs/models.py` `WorkflowRun` — schema stub only (no router, no repository). Plan 03 wires the active-run guard query against this table.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes beyond what is documented in the plan's threat model (T-1-01 through T-1-SC).

All threat mitigations implemented:
- T-1-01: `secrets.compare_digest` in `app/core/auth.py`
- T-1-02: Raw `api_key` value never passed to structlog; `SecretStr` type masks repr
- T-1-03: `db_data` named volume (not bind mount) in `docker-compose.yml`; `.env` gitignored; `*.db` already gitignored

## TDD Gate Compliance

RED gate: PASS (Wave 1 Plan 01 — `test(01-01)` commits confirmed)

GREEN gate: PASS — all 8 tests across test_health.py, test_auth.py, test_database.py, test_logging.py pass.

`feat(01-02)` commits exist after `test(01-01)` commits. Gate sequence: RED (96a0792, 5188e7e) → GREEN (305d1d6, 6904d92).

## Self-Check: PASSED

- [x] app/core/database.py exists with asyncio.Lock and expire_on_commit=False
- [x] app/core/auth.py exists with secrets.compare_digest
- [x] app/core/logging.py exists with clear_contextvars and CorrelationIdMiddleware
- [x] app/core/config.py exists with pydantic-settings Settings
- [x] app/health/router.py exists with SELECT 1 probe
- [x] app/main.py exists with lifespan and CorrelationIdMiddleware
- [x] Dockerfile exists with --workers 1
- [x] docker-compose.yml exists with db_data named volume
- [x] alembic.ini + migrations/env.py + migrations/script.py.mako exist
- [x] pytest tests/test_health.py tests/test_auth.py tests/test_database.py tests/test_logging.py exits 0 (8 passed)
- [x] test_workflows.py still fails as expected (Plan 03 deferred)
- [x] Commits 305d1d6 and 6904d92 exist
