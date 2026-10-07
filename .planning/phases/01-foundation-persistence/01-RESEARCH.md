# Phase 1: Foundation & Persistence — Research

**Researched:** 2026-10-07
**Domain:** FastAPI + SQLAlchemy async + aiosqlite + structlog + pytest-asyncio — Walking Skeleton
**Confidence:** HIGH

---

## Summary

Phase 1 builds the thinnest possible end-to-end slice of the workflow executor: a FastAPI app backed by a correctly-configured async SQLite engine, workflow definition CRUD, API key authentication, a health endpoint, and structured logging. Everything subsequent phases build on lives here — the async DB engine configuration, WAL mode setup, test harness isolation strategy, and structlog middleware must all be correct before any feature code is written.

The stack is fully verified. All package versions confirmed against PyPI as of 2026-10-07. All 10 packages passed slopcheck [OK] with no removals or flags. SQLAlchemy 2.1.4 is the current latest (not 2.1.3 from earlier research); everything else in STACK.md matches current PyPI.

The single most important Phase 1 fact: **WAL mode is a file-level setting that persists after the first connection sets it, but `busy_timeout` is connection-scoped and must be set on every connection via `event.listens_for(engine.sync_engine, "connect")`**. Forgetting `busy_timeout` means WAL mode is active but concurrent writes still fail immediately on contention rather than retrying. This is the primary source of `database is locked` errors in async SQLite services that "enabled WAL mode" but still see locking failures.

**Primary recommendation:** Follow the three-layer concurrency defense (WAL + busy_timeout + asyncio.Lock + version column) from day one. Extract the engine factory into a shared function used by both production and test code — do not duplicate PRAGMA initialization.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEFN-01 | Register a named workflow definition with ordered steps (name, execute_url, optional compensate_url, timeout_seconds, retry_policy schema) | SQLAlchemy models `WorkflowDefinition` + `WorkflowStep`; Pydantic v2 request/response schemas; `POST /workflows` router |
| DEFN-02 | Retrieve a single definition by name; list all definitions | `GET /workflows/{name}` + `GET /workflows`; WorkflowRepo.get_by_name() + WorkflowRepo.list_all() |
| DEFN-03 | Delete a definition by name; reject if active runs exist (409) | `DELETE /workflows/{name}`; WorkflowRepo.delete_by_name() with active-run guard query |
| RESIL-01 | Workflow run state durably persisted; survives process restarts | Alembic migrations create schema at startup; SQLite WAL mode; named Docker volume (Phase 4 delivery, but schema defined here) |
| RESIL-04 | Concurrent writes serialized: asyncio.Lock + WAL mode + version column | Three-layer defense; `_write_lock = asyncio.Lock()` in `core/database.py`; version column on all mutable models |
| PLAT-01 | X-API-Key header auth on all endpoints; 401 without valid key | `APIKeyHeader` + `Security()` dependency; key from `pydantic-settings`; tested with and without valid key |
| PLAT-02 | Structured JSON logs via structlog with run_id, step_name, correlation_id | structlog configured in `core/logging.py`; request middleware binds `correlation_id` via `bind_contextvars()` |
| PLAT-03 | GET /health returns 200 + SQLite reachability; 503 on DB unreachable | Health router executes a probe SELECT; catches `OperationalError`; returns structured JSON with version field |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| X-API-Key validation | API / Backend | — | Header extraction and key comparison happen server-side before any route handler runs; never client-side |
| Workflow definition CRUD | API / Backend | Database / Storage | Routes own HTTP contract; repository owns SQL; Pydantic schemas bridge them |
| Async SQLite engine + WAL | Database / Storage | — | Engine configuration is infrastructure; no API layer concern |
| asyncio.Lock write serialization | API / Backend | Database / Storage | Lock lives in the process (core/database.py); enforced at the application tier before DB write |
| Structured logging + correlation_id | API / Backend | — | Middleware injects per-request context; structlog propagates via contextvars across async boundaries |
| GET /health + DB probe | API / Backend | Database / Storage | Route calls a probe query; DB tier executes it; API tier interprets result |
| Test harness (StaticPool) | Database / Storage | — | Test engine overrides production engine; ASGITransport keeps tests in-process |

---

## Standard Stack

### Core — Phase 1 Packages

| Library | Verified Version | Purpose | Why Standard |
|---------|-----------------|---------|--------------|
| fastapi | 0.142.2 | REST framework + DI + OpenAPI | Native async, `APIKeyHeader` built-in, `lifespan` context manager, `Annotated` + `Depends` DI |
| uvicorn[standard] | 0.54.0 | ASGI server | Standard FastAPI server; `[standard]` extras add `httptools` + `uvloop` |
| sqlalchemy[asyncio] | 2.1.4 | ORM + async engine | `async_sessionmaker`, `select()` API, event hooks for PRAGMA injection |
| aiosqlite | 0.22.1 | Async SQLite driver | Only async SQLite driver that works with SQLAlchemy's asyncio extension |
| alembic | 1.20.0 | Schema migrations | First-party SQLAlchemy migration tool; `alembic init -t async` for async env.py |
| structlog | 26.1.0 | Structured JSON logging | `contextvars` integration; `bind_contextvars()` propagates across async boundaries |
| pydantic-settings | 2.15.0 | Settings / env var management | Pydantic v2 native; `BaseSettings` + `SettingsConfigDict(env_file=".env")` |

### Testing — Phase 1 Packages

| Library | Verified Version | Purpose | When to Use |
|---------|-----------------|---------|-------------|
| pytest | 9.0.3 (installed) | Test runner | All tests |
| pytest-asyncio | 1.4.0 | `async def` test support | Required for all async test functions and fixtures |
| httpx | 0.28.1 | `AsyncClient` + `ASGITransport` | Integration tests that call the ASGI app in-process |
| pytest-cov | 7.1.0 | Coverage reporting | Interview showcase — run with `--cov=app` |

**Note on SQLAlchemy version:** STACK.md listed 2.1.3; current PyPI latest is **2.1.4** [VERIFIED: PyPI]. Pin to 2.1.4 in requirements.

**Installation:**

```bash
# Core application
pip install "fastapi[standard]==0.142.2"
pip install "sqlalchemy[asyncio]==2.1.4"
pip install "aiosqlite==0.22.1"
pip install "alembic==1.20.0"
pip install "structlog==26.1.0"
pip install "pydantic-settings==2.15.0"

# Development / testing
pip install "pytest-asyncio==1.4.0"
pip install "httpx==0.28.1"
pip install "pytest-cov==7.1.0"
```

---

## Package Legitimacy Audit

> All packages verified via slopcheck 0.6.1 on 2026-10-07.

| Package | Registry | Age | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|
| fastapi | PyPI | 6+ yrs | [OK] | Approved |
| sqlalchemy | PyPI | 20+ yrs | [OK] | Approved |
| aiosqlite | PyPI | 6+ yrs | [OK] | Approved |
| alembic | PyPI | 10+ yrs | [OK] | Approved |
| structlog | PyPI | 10+ yrs | [OK] | Approved |
| pydantic-settings | PyPI | 3+ yrs | [OK] | Approved |
| uvicorn | PyPI | 6+ yrs | [OK] | Approved |
| httpx | PyPI | 5+ yrs | [OK] | Approved |
| pytest-asyncio | PyPI | 8+ yrs | [OK] | Approved |
| pytest-cov | PyPI | 10+ yrs | [OK] | Approved [NOTE: slopcheck noted no source repo link, but this is a well-known pytest plugin] |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
  HTTP Request
      │
      ▼
  ┌─────────────────────────────────────────┐
  │         Starlette Middleware Stack       │
  │  correlation_id → bind_contextvars()    │  structlog context injection
  └──────────────────┬──────────────────────┘
                     │
      ┌──────────────▼──────────────┐
      │    APIKeyHeader Security     │  X-API-Key validation (401 on fail)
      └──────────────┬──────────────┘
                     │
      ┌──────────────▼──────────────┐
      │      FastAPI Route Handler   │  Pydantic validation → 422 on bad input
      │  (workflows/router.py)       │
      └──────────────┬──────────────┘
                     │ depends on
      ┌──────────────▼──────────────┐
      │    WorkflowRepo (repository) │  Business logic + optimistic lock guard
      └──────────────┬──────────────┘
                     │ asyncio.Lock
      ┌──────────────▼──────────────┐
      │    AsyncSession (SQLAlchemy) │  async with AsyncSessionLocal() as session
      └──────────────┬──────────────┘
                     │
      ┌──────────────▼──────────────┐
      │    aiosqlite (thread pool)   │  WAL mode + busy_timeout on every conn
      │    SQLite file / :memory:    │
      └─────────────────────────────┘
```

### Recommended Project Structure

```
app/
├── main.py                    # FastAPI app factory, router mounts
├── lifespan.py                # @asynccontextmanager startup/shutdown
│
├── core/
│   ├── config.py              # pydantic-settings Settings class
│   ├── database.py            # async engine, AsyncSessionLocal, _write_lock, get_db
│   ├── auth.py                # APIKeyHeader dependency, verify_api_key()
│   ├── logging.py             # structlog configuration, CorrelationIdMiddleware
│   └── exceptions.py          # StaleDataError, InvalidStateTransitionError
│
├── workflows/
│   ├── models.py              # SQLAlchemy: WorkflowDefinition, WorkflowStep
│   ├── schemas.py             # Pydantic: CreateWorkflowRequest, WorkflowResponse, StepSchema
│   ├── repository.py          # WorkflowRepo: create, get_by_name, list_all, delete
│   └── router.py              # POST /workflows, GET /workflows, GET /workflows/{name}, DELETE /workflows/{name}
│
├── health/
│   └── router.py              # GET /health
│
migrations/                    # Alembic (alembic init -t async)
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
tests/
│   ├── conftest.py            # in-memory engine, test client, auth override
│   ├── test_health.py         # GET /health smoke test
│   ├── test_auth.py           # 401 without key, 200/201 with key
│   └── test_workflows.py      # DEFN-01, DEFN-02, DEFN-03 integration tests
│
Dockerfile
docker-compose.yml
pyproject.toml                 # [tool.pytest.ini_options] asyncio_mode = "auto"
.env.example
```

### Pattern 1: Async Engine Factory with WAL PRAGMAs

**What:** Create the engine once at startup with all required PRAGMAs set via `event.listens_for(engine.sync_engine, "connect")`.
**When to use:** Always — for both production (file-based) and test (in-memory StaticPool) engines.

```python
# Source: SQLAlchemy docs — asyncio extension + SQLite dialect
# https://docs.sqlalchemy.org/en/20/dialects/sqlite.html

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool, StaticPool

def create_engine(db_url: str, testing: bool = False):
    if testing:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
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
        cursor.execute("PRAGMA cache_size=-64000;")
        cursor.close()

    return engine
```

**Critical:** `event.listens_for(engine.sync_engine, ...)` — NOT `engine` directly. The asyncio extension exposes the underlying sync engine for connection event hooks. [VERIFIED: SQLAlchemy asyncio extension docs]

### Pattern 2: async_sessionmaker with expire_on_commit=False

```python
# Source: SQLAlchemy docs — async_sessionmaker
# https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

import asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from typing import AsyncGenerator

engine = create_engine(settings.database_url)
_write_lock = asyncio.Lock()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # REQUIRED: avoids DetachedInstanceError in async
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

`expire_on_commit=False` is required. Without it, accessing ORM attributes after `await session.commit()` triggers a lazy load that fails in async context (`MissingGreenlet` / `DetachedInstanceError`). [VERIFIED: SQLAlchemy asyncio extension docs]

### Pattern 3: FastAPI DI for DB Session + Auth

```python
# Source: FastAPI docs — Dependencies + Security
# https://fastapi.tiangolo.com/tutorial/sql-databases/

from typing import Annotated
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(
    api_key: str = Security(api_key_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key

DBSession = Annotated[AsyncSession, Depends(get_db)]
APIKey = Annotated[str, Security(verify_api_key)]
```

Route handlers declare `db: DBSession, _: APIKey` — clean, no boilerplate. [VERIFIED: FastAPI docs]

### Pattern 4: asyncio.Lock for Write Serialization

```python
# core/database.py
# Source: ARCHITECTURE.md (verified against asyncio semantics)

_write_lock = asyncio.Lock()

async def write_transaction(session: AsyncSession, fn):
    """Serialize all writes through a single asyncio.Lock."""
    async with _write_lock:
        async with session.begin():
            return await fn(session)
```

The lock is module-level (process-level). In a single-worker Uvicorn process, this serializes all write coroutines. Zero overhead for this use case. [VERIFIED: asyncio documentation]

### Pattern 5: structlog Setup with Request Correlation

```python
# core/logging.py
# Source: structlog docs — contextvars integration
# https://www.structlog.org/en/stable/contextvars.html

import structlog
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import uuid

def configure_structlog(json_logs: bool = True):
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
```

`clear_contextvars()` before `bind_contextvars()` is required — without the clear, context from a previous request leaks into the next one on the same asyncio task. [VERIFIED: structlog docs]

### Pattern 6: lifespan Context Manager (not on_event)

```python
# main.py
# Source: FastAPI docs — lifespan events
# https://fastapi.tiangolo.com/advanced/events/

from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: run migrations, init engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
```

`on_event("startup")` / `on_event("shutdown")` are deprecated since FastAPI 0.93. Use `lifespan`. [VERIFIED: FastAPI docs]

### Pattern 7: pytest-asyncio Test Infrastructure

```python
# tests/conftest.py
# Source: SQLAlchemy asyncio docs + pytest-asyncio docs

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_db, Base

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Apply same PRAGMAs as production
    from sqlalchemy import event
    @event.listens_for(engine.sync_engine, "connect")
    def set_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSession = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with TestSession() as session:
        yield session

    await engine.dispose()

@pytest.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "test-api-key"},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
```

**Key decisions:**
- `StaticPool`: forces all async calls through one in-memory connection — prevents per-connection `:memory:` isolation problem
- `expire_on_commit=False`: same as production — prevents test-specific `DetachedInstanceError`
- `ASGITransport`: calls the ASGI app directly, no real TCP — faster and deterministic
- `app.dependency_overrides`: swaps `get_db` for the test session — the standard FastAPI test pattern [VERIFIED: FastAPI docs, SQLAlchemy asyncio docs]

### Pattern 8: Health Endpoint with DB Probe

```python
# health/router.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from app.core.config import get_settings

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    try:
        await db.execute(text("SELECT 1"))
        db_status = "healthy"
        status_code = 200
    except Exception as e:
        db_status = f"unhealthy: {e}"
        status_code = 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if status_code == 200 else "unhealthy",
            "database": db_status,
            "version": settings.app_version,
        },
    )
```

Note: health endpoint does NOT require auth — it is intentionally a public probe endpoint. [ASSUMED — common practice, but PLAT-03 does not explicitly exclude auth; confirm with user if needed]

### Pattern 9: Dockerfile (Single Worker — MANDATORY)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data directory for SQLite file
RUN mkdir -p /app/data

EXPOSE 8000

# MANDATORY: --workers 1 — SQLite single-writer constraint
# Multiple workers = file lock contention = data corruption
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

```yaml
# docker-compose.yml
version: "3.9"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - db_data:/app/data
    environment:
      - DATABASE_URL=sqlite+aiosqlite:////app/data/workflows.db
      - API_KEY=change-me-in-production
      - LOG_JSON=true

volumes:
  db_data:    # named volume — data survives container restarts
```

`--workers 1` is hardcoded in `CMD` (not overridable from compose without explicit CMD override) because this is a safety constraint, not a tuning parameter. [VERIFIED: SQLite file-locking documentation]

### Anti-Patterns to Avoid

- **`on_event("startup")`**: Deprecated since FastAPI 0.93 — use `lifespan` context manager.
- **`engine` directly in `event.listens_for`**: Must use `engine.sync_engine` for connection event hooks in asyncio context.
- **`expire_on_commit=True` (default)**: Causes `DetachedInstanceError` / `MissingGreenlet` on attribute access after commit.
- **`StaticPool` in production**: Only for tests — a single shared in-memory connection is not safe under real concurrent load.
- **`--workers 4` with SQLite**: Hard data corruption risk. SQLite's write lock is process-level.
- **Open write transaction across HTTP call**: Holds DB write lock for the entire outbound I/O duration. Commit before the HTTP call.
- **`asyncio.create_task` without storing the reference**: Task is garbage-collected; use `BackgroundTasks` or store reference in a set.
- **`clear_contextvars()` omitted in middleware**: Previous request context leaks into next request on the same asyncio task.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Env var / settings management | Custom `os.getenv` logic | `pydantic-settings BaseSettings` | Type coercion, `.env` file support, `SecretStr` masking, nested models |
| API key extraction from header | Custom header parsing middleware | `fastapi.security.APIKeyHeader` + `Security()` | Registers scheme in OpenAPI, shows "Authorize" in Swagger UI, no boilerplate |
| Async DB session lifecycle | Manual `session = Session(); try/finally session.close()` | `async_sessionmaker` + `async with session:` | Exception-safe teardown, async context manager handles all paths |
| PRAGMA initialization | Startup script that runs SQL directly | `event.listens_for(engine.sync_engine, "connect")` | Runs on every connection including test connections; guaranteed to fire before any query |
| Structured logging with context | `logging.LoggerAdapter` or manual JSON formatting | `structlog` with `bind_contextvars()` | Async-safe context propagation; composable processor pipeline |
| Schema migrations | `CREATE TABLE IF NOT EXISTS` at startup | Alembic with `alembic init -t async` | Required for any schema change after deployment; demonstrates production maturity |
| Integration test HTTP client | `TestClient` (sync) | `AsyncClient(transport=ASGITransport(app=app))` | Sync `TestClient` blocks the event loop; `ASGITransport` is fully async-correct |

**Key insight:** Every item in this table has a 20-200 line implementation that misses edge cases. The ecosystem solutions handle all the edge cases correctly. Phase 1 is infrastructure — use the standard tools.

---

## Common Pitfalls

### Pitfall 1: `busy_timeout` Not Set (Most Common WAL Mode Mistake)

**What goes wrong:** Developer enables `PRAGMA journal_mode=WAL` but does not set `PRAGMA busy_timeout`. WAL mode allows concurrent readers alongside one writer, but when two writes contend, the default behavior is to return `SQLITE_BUSY` immediately (0ms timeout). `aiosqlite` surfaces this as `sqlite3.OperationalError: database is locked`. Under any real concurrent load, concurrent workflow runs fail with this error.

**Why it happens:** `journal_mode=WAL` is a per-file setting (persists in the DB file). `busy_timeout` is per-connection (must be set on every new connection). Developers test with one connection, see WAL working, and miss the contention case.

**How to avoid:** Set both PRAGMAs in `event.listens_for(engine.sync_engine, "connect")`. The event fires on every connection, ensuring `busy_timeout=5000` is always active.

**Warning signs:** `OperationalError: database is locked` in logs, especially under concurrent test execution.

### Pitfall 2: `expire_on_commit=True` (Default) Causes Async Attribute Access Errors

**What goes wrong:** After `await session.commit()`, SQLAlchemy marks all loaded ORM objects as expired. Accessing any attribute triggers a lazy load — but in async context, this fails with `MissingGreenlet: greenlet_spawn has not been called` or `DetachedInstanceError`.

**Why it happens:** SQLAlchemy's lazy loading uses greenlets (gevent-style). The asyncio extension patches this, but the lazy load must happen inside an active async session. After `yield session` in `get_db`, accessing expired attributes outside the session context fails.

**How to avoid:** Set `expire_on_commit=False` on `async_sessionmaker`. Return Pydantic schemas from service functions (not raw ORM objects) so session lifecycle never matters at the API boundary.

**Warning signs:** `MissingGreenlet` or `DetachedInstanceError` on response serialization after a write endpoint.

### Pitfall 3: Test `async def` Functions That Silently Never Execute

**What goes wrong:** `async def test_something()` functions run without `@pytest.mark.asyncio` in pytest-asyncio < 0.21 (or without `asyncio_mode="auto"` in 0.21+/1.x). The test appears to pass — zero assertions, no errors — but no test body ran.

**Why it happens:** Without the asyncio mode configuration, pytest treats `async def` test functions as sync generators and skips them rather than raising an error.

**How to avoid:** Set `asyncio_mode = "auto"` in `pyproject.toml` under `[tool.pytest.ini_options]`. Verify at least one assertion fires by adding a deliberate failing assertion to a new test before writing the real assertions.

**Warning signs:** 100% pass rate with zero failing tests when the code is known to be incomplete; test count is lower than expected.

### Pitfall 4: `OperationalError: database is locked` from `SingletonThreadPool`

**What goes wrong:** SQLAlchemy auto-selects `SingletonThreadPool` for in-memory SQLite. This pool is explicitly documented as incompatible with `create_async_engine`. Under asyncio, multiple coroutines may try to acquire the single-thread pool from different threads (aiosqlite uses a thread executor), causing contention and lock errors.

**Why it happens:** The auto-selected pool for `:memory:` SQLite is thread-specific. aiosqlite wraps the synchronous `sqlite3` module in a `ThreadPoolExecutor`, which can create mismatches.

**How to avoid:** Always override with `poolclass=StaticPool` for in-memory SQLite in tests. Use `poolclass=NullPool` for file-based SQLite in production. Never let SQLAlchemy auto-select the pool for SQLite+asyncio. [VERIFIED: SQLAlchemy asyncio extension docs]

**Warning signs:** Intermittent `database is locked` in test suites, especially with concurrent fixtures.

### Pitfall 5: Leaked structlog Context Across Requests

**What goes wrong:** `bind_contextvars()` without a preceding `clear_contextvars()` accumulates context keys across requests handled by the same asyncio task. `correlation_id` from request A bleeds into request B.

**Why it happens:** asyncio tasks are reused. `contextvars.ContextVar` values persist on a task until explicitly cleared. If middleware calls `bind_contextvars(correlation_id=X)` without first clearing, the previous request's `correlation_id` remains bound until overwritten.

**How to avoid:** Always `clear_contextvars()` at the start of the middleware dispatch method, before `bind_contextvars()`.

**Warning signs:** Log lines showing `correlation_id` from a different request; log lines with stale `run_id` values after a run completes.

### Pitfall 6: `event.listens_for(engine, ...)` Instead of `engine.sync_engine`

**What goes wrong:** Registering the PRAGMA event hook on `engine` (the async engine) instead of `engine.sync_engine` results in the hook never firing. No error is raised — the PRAGMAs simply never execute.

**Why it happens:** The asyncio engine wrapper (`AsyncEngine`) does not expose connection events directly. Connection-level events must be registered on the underlying synchronous engine, accessed via `.sync_engine`.

**How to avoid:** Always `event.listens_for(engine.sync_engine, "connect")` for PRAGMA initialization.

**Warning signs:** WAL mode not enabled despite initialization code (verify with `PRAGMA journal_mode;` query in a test).

---

## Code Examples

### Workflow Definition Models (SQLAlchemy)

```python
# app/workflows/models.py
# Source: SQLAlchemy 2.x ORM docs

from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug: "order-fulfillment"
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # optimistic lock

    steps: Mapped[list["WorkflowStep"]] = relationship(
        "WorkflowStep", order_by="WorkflowStep.step_order", cascade="all, delete-orphan"
    )

class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("workflow_def_id", "step_order"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_def_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_definitions.id"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    execute_url: Mapped[str] = mapped_column(Text, nullable=False)
    compensate_url: Mapped[str | None] = mapped_column(Text)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    retry_policy: Mapped[str | None] = mapped_column(Text)  # JSON blob; schema defined, not enforced in v1
```

### Workflow Definition Schemas (Pydantic v2)

```python
# app/workflows/schemas.py

from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional
import json

class RetryPolicySchema(BaseModel):
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    max_delay_seconds: float = 30.0

class StepCreateSchema(BaseModel):
    name: str
    execute_url: HttpUrl
    compensate_url: Optional[HttpUrl] = None
    timeout_seconds: int = 30
    retry_policy: Optional[RetryPolicySchema] = None

class WorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    steps: list[StepCreateSchema]

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, v):
        if not v:
            raise ValueError("Workflow must have at least one step")
        return v

class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    steps: list["StepResponse"]
    version: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
```

### Walking Skeleton Validation Smoke Test

```python
# tests/test_health.py — the minimal proof the skeleton is alive

import pytest

async def test_health_returns_200(client):
    """Walking Skeleton smoke test: proves DB + app + auth middleware are wired."""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["database"] == "healthy"

async def test_health_without_auth_is_public(client_no_auth):
    """Health endpoint is a public probe — does not require X-API-Key."""
    response = await client_no_auth.get("/health")
    assert response.status_code == 200

async def test_protected_endpoint_requires_api_key(client_no_auth):
    """Auth middleware gate: 401 on missing key."""
    response = await client_no_auth.get("/workflows")
    assert response.status_code == 401
```

---

## Walking Skeleton Validation

### What the Smoke Test Proves

A passing smoke test for Phase 1 demonstrates:

1. **App boots without error** — `lifespan` ran, engine connected, tables created, no import errors
2. **WAL mode is active** — DB probe in health check executed against a WAL-mode connection
3. **Auth middleware fires** — Unauthenticated request to any protected endpoint returns 401
4. **DB write works** — `POST /workflows` creates a row; `GET /workflows/{name}` retrieves it from the same session-less context
5. **DB survives process restart** — Stopping and restarting the app, then querying, confirms durability (integration test or manual verification)
6. **Structured log lines have correlation_id** — Health check response includes `X-Correlation-ID` header; server log has matching `correlation_id` field

**The smoke test command:**

```bash
# Start service
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

# Probe health (no auth required)
curl http://localhost:8000/health
# Expected: {"status":"healthy","database":"healthy","version":"0.1.0"}

# Attempt protected endpoint without auth
curl http://localhost:8000/workflows
# Expected: HTTP 401

# Create a workflow definition
curl -X POST http://localhost:8000/workflows \
  -H "X-API-Key: test-key" \
  -H "Content-Type: application/json" \
  -d '{"name":"test","steps":[{"name":"s1","execute_url":"http://example.com"}]}'
# Expected: HTTP 201

# Retrieve it
curl http://localhost:8000/workflows/test -H "X-API-Key: test-key"
# Expected: HTTP 200 with definition
```

---

## TDD Task Candidates

These are the components best suited for TDD in Phase 1 — each has a clear input/output contract, testable without external dependencies.

### High TDD Value (write test first, then implement)

| Component | Test Scenario | Why TDD Fits |
|-----------|--------------|--------------|
| `verify_api_key` dependency | Valid key → passes; missing key → 401; wrong key → 401 | Pure function; total test in 3 lines |
| `WorkflowCreateRequest` Pydantic validator | Empty steps → 422; missing execute_url → 422; valid body → 201 | Schema validation is data-driven; parameterize with `pytest.mark.parametrize` |
| `WorkflowRepo.get_by_name` | Existing name → definition; missing name → None | CRUD contract; deterministic with in-memory DB |
| `WorkflowRepo.delete` with active-run guard | No active runs → success; active run exists → ConflictError | Business rule; easiest to verify before wiring to router |
| WAL mode assertion | After engine init, `PRAGMA journal_mode` returns "wal" | Infra correctness; catches the `engine` vs `engine.sync_engine` bug |
| `GET /health` DB probe | Healthy DB → 200; `OperationalError` → 503 | Mocking `db.execute` to raise tests the sad path without corrupting DB |
| `CorrelationIdMiddleware` | Request with `X-Correlation-ID` header → same value in response; request without header → generated UUID in response | Middleware behavior is fully deterministic |

### Medium TDD Value (write test concurrently)

| Component | Test Scenario |
|-----------|--------------|
| `POST /workflows` → `GET /workflows` round-trip | Create definition, list all, verify appears |
| `DELETE /workflows/{name}` | 204 on success; 404 on missing; 409 on active runs |
| `structlog` JSON output | Log contains expected fields (`correlation_id`, `level`, `timestamp`) |

### Manual Verification (not unit-testable in isolation)

| Component | Why Manual |
|-----------|----------|
| SQLite WAL mode under real concurrent writes | Requires multiple OS threads; unit test with `StaticPool` cannot simulate true concurrent file lock contention |
| `asyncio.Lock` behavior under concurrent `asyncio.create_task` | Behavioral — verify via integration test with concurrent requests, not unit test |
| Docker named volume data persistence | Requires running `docker-compose down && docker-compose up`; not automatable in pytest |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-----------------|--------------|--------|
| `on_event("startup")` / `on_event("shutdown")` | `lifespan` context manager | FastAPI 0.93 (2023) | `on_event` still works but is deprecated; `lifespan` is the current idiom |
| `@pytest.mark.asyncio` on every test | `asyncio_mode = "auto"` in `pyproject.toml` | pytest-asyncio 0.21 | No per-test decorator needed; missing this causes silent test skips |
| `Annotated[X, Depends(Y)]` | Same, but now preferred over bare `Depends(Y)` in route signatures | FastAPI 0.95 | Type-checker friendly; current idiomatic form |
| `from sqlalchemy.orm import declarative_base` | `class Base(DeclarativeBase): pass` | SQLAlchemy 2.0 | Old `declarative_base()` factory is deprecated; class-based `DeclarativeBase` is the 2.x idiom |
| `Column(String)` in model class body | `Mapped[str] = mapped_column(String)` | SQLAlchemy 2.0 | Typed mapped columns with full IDE support; old form still works but deprecated |
| `TestClient` (sync httpx) for FastAPI tests | `AsyncClient(transport=ASGITransport(app=app))` | FastAPI 0.95+ | Sync `TestClient` blocks event loop; `ASGITransport` is async-correct |

**Deprecated / avoid:**

- `encode/databases`: Predates SQLAlchemy asyncio extension; no reason to use it.
- `SQLModel`: Merges Pydantic + ORM into one class — breaks when API schemas diverge from DB shapes (they will in Phase 2+).
- `SingletonThreadPool` with asyncio: Explicitly documented as incompatible with `create_async_engine`.
- `requests` library in any async route or background task: Blocks the event loop.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.4.0 |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ --cov=app --cov-report=term-missing` |

### pyproject.toml — Required Configuration

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Missing `asyncio_mode = "auto"` causes `async def` tests to silently skip without error. This is the single most common pytest-asyncio configuration mistake. [VERIFIED: pytest-asyncio 1.x docs]

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| DEFN-01 | POST /workflows creates definition with steps | integration | `pytest tests/test_workflows.py::test_create_workflow -x` | Needs DB fixture |
| DEFN-02 | GET /workflows/{name} retrieves; GET /workflows lists | integration | `pytest tests/test_workflows.py::test_get_workflow -x` | Round-trip after DEFN-01 |
| DEFN-03 | DELETE /workflows/{name} — 204 no runs, 409 active runs | integration | `pytest tests/test_workflows.py::test_delete_workflow -x` | Active-run guard test needs WorkflowRun model stub |
| RESIL-04 | asyncio.Lock serializes writes; WAL mode active | unit | `pytest tests/test_database.py::test_wal_mode_active -x` | PRAGMA query in test fixture |
| PLAT-01 | X-API-Key required; 401 on missing/wrong key | unit | `pytest tests/test_auth.py -x` | Parameterize missing/wrong/valid key |
| PLAT-02 | Structured logs include correlation_id | unit | `pytest tests/test_logging.py::test_correlation_id_in_logs -x` | Capture structlog output in test |
| PLAT-03 | GET /health — 200 healthy; 503 DB unreachable | integration | `pytest tests/test_health.py -x` | Mock `db.execute` to raise for sad path |

### Sampling Rate

- **Per task commit:** `pytest tests/ -x -q` (fail fast, quiet output)
- **Per wave merge:** `pytest tests/ --cov=app --cov-report=term-missing`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps (Files That Must Exist Before Implementation)

- [ ] `tests/conftest.py` — in-memory StaticPool engine, `client` fixture, `db_session` fixture, `client_no_auth` fixture
- [ ] `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`
- [ ] `tests/test_health.py` — smoke test (REQ PLAT-03)
- [ ] `tests/test_auth.py` — API key validation (REQ PLAT-01)
- [ ] `tests/test_workflows.py` — CRUD tests (REQ DEFN-01, DEFN-02, DEFN-03)
- [ ] `tests/test_database.py` — WAL mode assertion (REQ RESIL-04)

---

## Security Domain

> `security_enforcement: true`, ASVS level 1.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `APIKeyHeader` + `Security()` dependency; key from env var via `pydantic-settings`; `SecretStr` type for key value |
| V3 Session Management | no | Stateless API; no sessions |
| V4 Access Control | yes | Auth dependency applied globally via router `dependencies=[Security(verify_api_key)]`; no per-route bypass |
| V5 Input Validation | yes | Pydantic v2 on all request bodies; `HttpUrl` type for step URLs; `@field_validator` for business rules |
| V6 Cryptography | no | API key comparison with `secrets.compare_digest()` to prevent timing attacks (see below) |

### Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key brute-force | Elevation of Privilege | Key should be >= 32 random bytes (256-bit entropy); key stored as `SecretStr` in settings |
| Timing attack on API key comparison | Elevation of Privilege | Use `secrets.compare_digest(provided_key, expected_key)` instead of `==` |
| SQL injection via workflow name | Tampering | SQLAlchemy parameterized queries; never string-format SQL |
| SSRF via execute_url / compensate_url | Information Disclosure | Phase 1: validate `HttpUrl` type only; Phase 2 concern: restrict to allowlisted domains if needed |
| Log injection via structured log fields | Tampering | structlog JSON renderer escapes special characters; no string interpolation in log messages |

**API key comparison — use `secrets.compare_digest`:**

```python
# core/auth.py
import secrets

async def verify_api_key(api_key: str = Security(api_key_scheme)) -> str:
    expected = get_settings().api_key.get_secret_value()
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | Yes (3.13.12) | 3.13.12 | None needed — 3.13 exceeds minimum |
| SQLite | Database | Yes (3.52.0) | 3.52.0 | — |
| Docker | Containerization | Yes | 27.0.3 | — |
| Docker Compose | Local dev orchestration | Yes | 2.29.0 | — |
| pip (PyPI) | Package install | Yes | — | — |

**Note:** Python 3.13 is installed (not 3.11). The stack targets 3.11+ minimum; 3.13 is fully compatible. The Dockerfile should pin `python:3.11-slim` for portability (interview portability concern noted in STACK.md). [VERIFIED: pip index versions confirmed all packages support Python 3.11+]

**Missing dependencies with no fallback:** None

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Health endpoint does not require X-API-Key auth (public probe) | Pattern 8, TDD Candidates | If PLAT-03 requires auth on /health, the test fixture and the unauthenticated health probe pattern need updating |
| A2 | DEFN-03 active-run check means `workflow_runs` with status not in terminal states | DEFN-03 requirement row | Phase 1 does not define WorkflowRun model; delete guard may need a stub or deferred until Phase 2 joins |
| A3 | `retry_policy` stored as JSON blob (TEXT column) in Phase 1; enforcement deferred to v2 | WorkflowStep model | If Phase 2 needs structured access to retry_policy fields, a JSON column or separate table is required |

---

## Open Questions

1. **DEFN-03 delete guard implementation in Phase 1**
   - What we know: DEFN-03 requires rejecting deletion if active runs exist. Phase 1 does not implement `workflow_runs` table.
   - What's unclear: Should Phase 1 stub the active-run check as "always allow delete" (since no runs exist yet) and make it real in Phase 2? Or should the `workflow_runs` model be created in Phase 1 even though Phase 2 populates it?
   - Recommendation: Create the `workflow_runs` table schema (empty) in Phase 1 so the delete guard query compiles and returns 0 rows. This avoids a migration in Phase 2 and satisfies DEFN-03's success criterion from day one.

2. **Health endpoint auth**
   - What we know: PLAT-03 says `GET /health` returns service status, SQLite reachability, and version. It does not specify whether auth is required.
   - What's unclear: Auth on health breaks typical infrastructure probe patterns (load balancers, k8s liveness probes cannot inject API keys easily).
   - Recommendation: Exclude `/health` from auth dependency. If the user wants auth on health, it is a 2-line change.

---

## Sources

### Primary (HIGH confidence — verified against official documentation)

- [SQLAlchemy 2.0 Asyncio Extension](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — `async_sessionmaker`, `expire_on_commit`, `event.listens_for(engine.sync_engine, ...)`, `StaticPool`
- [SQLAlchemy 2.0 SQLite Dialect](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) — WAL PRAGMA, `NullPool`, `check_same_thread`
- [FastAPI SQL Databases Tutorial](https://fastapi.tiangolo.com/tutorial/sql-databases/) — DI pattern, `Annotated` + `Depends`
- [FastAPI Advanced Events (lifespan)](https://fastapi.tiangolo.com/advanced/events/) — `asynccontextmanager` lifespan
- [FastAPI Security — API Key](https://fastapi.tiangolo.com/tutorial/security/) — `APIKeyHeader`, `Security()`
- [structlog contextvars](https://www.structlog.org/en/stable/contextvars.html) — `bind_contextvars`, `clear_contextvars`
- [pytest-asyncio 1.x docs](https://pytest-asyncio.readthedocs.io/en/latest/) — `asyncio_mode = "auto"`, fixture scoping
- PyPI registry — all package version verifications (2026-10-07)
- slopcheck 0.6.1 — all 10 packages rated [OK]

### Secondary (MEDIUM confidence — verified via cross-referencing multiple sources)

- STACK.md, ARCHITECTURE.md, PITFALLS.md — prior project research (2026-10-07), HIGH confidence per those documents' own assessments
- SQLite WAL mode production guides — multiple post-mortems confirming `busy_timeout` is the critical missing piece after enabling WAL
- [Async Testing with FastAPI and pytest](https://weirdsheeplabs.com/blog/fast-and-furious-async-testing-with-fastapi-and-pytest) — `ASGITransport` pattern verification

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified on PyPI, all slopcheck [OK], all configs cross-referenced against official docs
- Architecture patterns: HIGH — verified against SQLAlchemy asyncio extension docs and FastAPI official docs
- Pitfalls: HIGH — sourced from PITFALLS.md (HIGH confidence) + official docs cross-references

**Research date:** 2026-10-07
**Valid until:** 2026-11-07 (stable ecosystem; 30-day horizon)
