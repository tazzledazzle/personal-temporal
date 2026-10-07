# Technology Stack

**Project:** Multi-Step Workflow Executor (Python + FastAPI + SQLite)
**Researched:** 2026-10-07
**Mode:** Ecosystem — standard 2025 stack for durable workflow executor REST service

---

## Recommended Stack

### Core Runtime

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.11+ | Runtime | Pattern match, `tomllib`, `Self` type, asyncio task groups; 3.12 perf gains are real but 3.11 is the safe minimum for interview portability |
| FastAPI | 0.142.x | REST framework | Native async, auto-generated OpenAPI, Pydantic validation, dependency injection designed for this exact use case |
| Uvicorn | 0.54.x | ASGI server | Standard FastAPI server; use `uvicorn[standard]` to include `httptools` and `uvloop` for production speed |
| Pydantic | v2 (bundled with FastAPI) | Request/response validation | Ships with FastAPI 0.100+; v2 is 5-50x faster than v1; use it for all schemas including settings |

### Database

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| SQLAlchemy | 2.1.x | ORM + async engine | 2.0 API is stable and current; `async_sessionmaker`, `select()` style queries, `AsyncAttrs` for lazy loading; 2.1 adds minor perf improvements |
| aiosqlite | 0.22.x | Async SQLite driver | The only async SQLite driver that works with SQLAlchemy's asyncio extension; wraps the stdlib `sqlite3` module in a thread executor |
| Alembic | 1.20.x | Schema migrations | First-party SQLAlchemy migration tool; use `alembic init -t async` to get async-native `env.py` template |

### HTTP Client (Outbound Step Calls)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| httpx | 0.28.x | Async HTTP client for saga step calls | Built-in to FastAPI's testing stack, supports both sync and async, HTTP/2 capable, mirrors `requests` API for low learning curve; FastAPI's `TestClient` is built on httpx |

**Why not aiohttp:** aiohttp is ~50% faster under extreme fan-out (hundreds of concurrent requests), but this service calls workflow steps sequentially per saga — not in parallel fan-out. httpx wins on DX, test integration, and maintainability at this scale.

### Auth

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| fastapi built-in `APIKeyHeader` | (bundled) | X-API-Key header extraction | FastAPI's `fastapi.security.APIKeyHeader` + `Security()` registers the scheme in OpenAPI, shows "Authorize" button in Swagger UI, and injects through dependency injection without external packages |

### Configuration

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pydantic-settings | 2.15.x | Settings management | Official Pydantic v2 split-out package; `BaseSettings` reads from env vars and `.env` files; `model_config = SettingsConfigDict(env_file=".env")` is the v2 idiom; cache with `@lru_cache` on `get_settings()` |

### Logging

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| structlog | 26.1.x | Structured logging | The right choice for a service with observable workflow state: `contextvars` integration propagates request/workflow context across async boundaries automatically; JSON output for production, pretty-print for dev; processor pipeline is composable and testable; routes through stdlib so Uvicorn's own log output stays consistent |

**Why not loguru:** loguru has a lower learning curve but weaker async context propagation. For a workflow service where every log line should carry `workflow_run_id`, `step_id`, and `correlation_id`, structlog's `bind_contextvars()` / `clear_contextvars()` in middleware is the idiomatic pattern.

**Why not stdlib logging:** Requires `python-json-logger` or similar to emit JSON; `LoggerAdapter` for context propagation is verbose and error-prone in async contexts; no benefit over structlog for a new project.

### Testing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | 8.x (latest) | Test runner | Standard |
| pytest-asyncio | 1.4.x | Async test support | Enables `async def` test functions and fixtures; use `asyncio_mode = "auto"` in `pyproject.toml` to avoid per-test `@pytest.mark.asyncio` decoration |
| httpx | 0.28.x | AsyncClient for integration tests | `AsyncClient(transport=ASGITransport(app=app))` replaces FastAPI's sync `TestClient` for async test correctness; same package as outbound HTTP client (no extra dep) |
| pytest-cov | latest | Coverage reporting | Interview showcase should show coverage |

**Testing DB strategy:** Use `sqlite+aiosqlite:///:memory:` with `StaticPool` for unit tests (single connection, no file I/O). Use a separate file-based `test.db` for integration tests that need cross-session state. Override `get_db` dependency via `app.dependency_overrides` in `conftest.py`.

### Containerization

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docker | latest | Container runtime | Interview requirement |
| python:3.11-slim | (base image) | Container base | `slim` drops dev tools and locale data; meaningfully smaller than `full`; `alpine` causes CPython compilation issues with some packages and is not worth the extra complexity |

---

## Configuration Gotchas

### SQLite WAL Mode (Critical)

Default SQLite journal mode (`DELETE`) serializes all reads and writes. For a workflow executor with async concurrency, this causes `SQLITE_BUSY` errors under any load. **Always enable WAL mode and set `busy_timeout` via SQLAlchemy connection events:**

```python
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine("sqlite+aiosqlite:///./workflows.db")

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")     # 5s retry window
    cursor.execute("PRAGMA synchronous=NORMAL;")    # safe + fast in WAL mode
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA cache_size=-64000;")     # 64 MB page cache
    cursor.close()
```

The `event.listens_for(engine.sync_engine, ...)` is required — you cannot use `engine` directly in asyncio context for sync connection events. This is documented in SQLAlchemy's asyncio extension guide (HIGH confidence, verified against official docs).

### SQLite Connection Pooling (Critical)

SQLite with aiosqlite has a **single-writer constraint** regardless of pool size. The `AsyncAdaptedQueuePool` is used by default with `create_async_engine`, which is correct. However:

- Do **not** set `pool_size` > 1 and expect parallel writes — they will serialize or busy-wait.
- For tests, use `poolclass=StaticPool` with `connect_args={"check_same_thread": False}` to force a single shared in-memory connection.
- For a file-based DB with intermittent `database is locked` errors, switch to `NullPool` — this disables connection reuse and avoids file-lock accumulation at the cost of per-request connection creation overhead (acceptable for SQLite interview scale).

```python
# Production (file-based)
engine = create_async_engine(
    "sqlite+aiosqlite:///./workflows.db",
    pool_pre_ping=True,
)

# Test (in-memory, single coroutine)
from sqlalchemy.pool import StaticPool
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

### FastAPI Dependency Injection for Async DB Sessions

Use the `Annotated` + `Depends` pattern introduced in FastAPI 0.95+. This is the current idiomatic form:

```python
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

DBSession = Annotated[AsyncSession, Depends(get_db)]
```

Route handlers then declare `db: DBSession` — no `Security` needed, no boilerplate. The context manager in `get_db` ensures the session is closed even on exceptions.

**`expire_on_commit=False` is required** on `async_sessionmaker`: without it, accessing ORM attributes after `await session.commit()` triggers lazy-load SQL that cannot execute in an async context (no running event loop for the sync lazy-load path).

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # REQUIRED for async
)
```

### BackgroundTasks Swappability Pattern

FastAPI `BackgroundTasks` run in-process on the event loop — they share CPU and memory with the API workers. The key architectural constraint: **if the server process restarts mid-task, the task is silently lost**.

For this project's scope (in-process is acceptable), the pattern for future Celery migration is to isolate dispatch behind a thin function:

```python
# app/tasks/dispatch.py
from fastapi import BackgroundTasks

def enqueue_workflow_execution(
    background_tasks: BackgroundTasks,
    run_id: str,
) -> None:
    """Dispatch point. Replace body with celery_task.delay(run_id) to migrate."""
    background_tasks.add_task(_execute_workflow, run_id)
```

Keep the actual workflow logic in a plain `async def _execute_workflow(run_id: str)` that does not depend on BackgroundTasks internals. This function becomes a Celery task body with zero changes.

### Alembic Async Setup

Use the async Alembic template:

```bash
alembic init -t async migrations
```

The standard (non-async) template generates synchronous `env.py` that will fail against an async engine. The async template uses `run_async_migrations()` correctly. Set `target_metadata = Base.metadata` in `env.py` and import all model modules before that line — Alembic's autogenerate only detects tables that have been imported.

### Docker + SQLite Volume Mount (Critical)

SQLite inside a Docker container **loses all data on container restart** unless the database file is on a mounted volume. The `.db` file must be on a volume:

```yaml
# docker-compose.yml
services:
  api:
    build: .
    volumes:
      - db_data:/app/data
    environment:
      - DATABASE_URL=sqlite+aiosqlite:////app/data/workflows.db

volumes:
  db_data:
```

Do not use a bind mount to the project directory for the DB file in production — use a named volume for portability.

### Docker Single-Worker Constraint with SQLite

SQLite does not support multiple processes writing to the same file safely. Run a **single Uvicorn process** in the container:

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

Do not use `--workers 4` or Gunicorn's multiprocessing with SQLite. This is a hard limit of SQLite's file-locking model, not a Docker issue.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Async HTTP client | httpx | aiohttp | aiohttp is faster under fan-out but no sync mode, no HTTP/2, worse DX; this service calls steps sequentially, not in parallel batches |
| HTTP client | httpx | requests | requests blocks the event loop — never use in async FastAPI route handlers or background tasks |
| Logging | structlog | loguru | loguru is simpler but `contextvars` support for async context binding is weaker; structlog's processor chain is better for production observability |
| Logging | structlog | stdlib logging | stdlib requires significant configuration boilerplate for JSON output and async context; no benefit for a new project |
| ORM | SQLAlchemy 2.x | SQLModel | SQLModel is a thin SQLAlchemy wrapper by the FastAPI author; good for simple CRUD, but adds indirection and has less community troubleshooting for async edge cases; stick to SQLAlchemy directly |
| ORM | SQLAlchemy 2.x | Tortoise ORM | Active development but smaller ecosystem; SQLAlchemy is the industry standard and the right choice for an interview showcase |
| Settings | pydantic-settings | python-decouple | pydantic-settings integrates with Pydantic's type system natively; validation, SecretStr masking, and nested models come for free |
| Migration | Alembic | manual CREATE TABLE | `CREATE TABLE IF NOT EXISTS` at startup is tempting for SQLite; Alembic is required for any realistic schema evolution and demonstrates production maturity |
| Testing async | pytest-asyncio | anyio | anyio supports trio as well as asyncio but adds complexity for a purely asyncio project; pytest-asyncio with `asyncio_mode="auto"` is simpler |

---

## What NOT to Use and Why

**SQLModel** — The FastAPI author's own ORM wrapper. Tempting because it appears in FastAPI's official docs. Avoid it for this project: it merges Pydantic models and ORM models into one class, which causes confusion when your workflow API schemas diverge from DB row shapes (they will). Keep Pydantic schemas and SQLAlchemy models separate. [LOW-MEDIUM confidence: this is a design opinion, not a technical blocker]

**encode/databases** — An older async DB library that predates SQLAlchemy's asyncio extension. No reason to use it when SQLAlchemy 2.0 handles async natively. [HIGH confidence]

**Synchronous SQLAlchemy** (`create_engine`, not `create_async_engine`) — Using sync SQLAlchemy in an async FastAPI app blocks the event loop on every DB query. The symptom is subtle: endpoints appear to work but block all other concurrent requests during I/O. [HIGH confidence, verified against FastAPI docs and SQLAlchemy asyncio docs]

**Multiple Uvicorn workers with SQLite** — See Docker section above. SQLite's write lock is process-level, not thread-level. Multiple workers will corrupt state under concurrent writes. [HIGH confidence]

**`on_event("startup")` / `on_event("shutdown")`** — Deprecated in FastAPI 0.93+. Use the `lifespan` context manager instead:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_db()
    yield
    # shutdown
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
```

**`SingletonThreadPool`** — SQLAlchemy auto-selects this pool for in-memory SQLite. It is explicitly documented as incompatible with asyncio and `create_async_engine`. Override with `StaticPool` for tests. [HIGH confidence, verified against SQLAlchemy docs]

---

## Installation

```bash
# Core application
pip install "fastapi[standard]"           # FastAPI + uvicorn + httptools + uvloop
pip install "sqlalchemy[asyncio]"         # SQLAlchemy 2.x with async support
pip install aiosqlite                     # Async SQLite driver
pip install alembic                       # Schema migrations
pip install httpx                         # Async HTTP client for outbound saga calls
pip install structlog                     # Structured logging
pip install pydantic-settings             # Settings / config management

# Development and testing
pip install pytest pytest-asyncio pytest-cov
# httpx already installed above — used for both outbound calls and AsyncClient testing
```

Pinned versions for reproducibility (as of 2026-10-07):

```
fastapi==0.142.2
uvicorn[standard]==0.54.0
sqlalchemy[asyncio]==2.1.3
aiosqlite==0.22.1
alembic==1.20.0
httpx==0.28.1
structlog==26.1.0
pydantic-settings==2.15.0
pytest==8.x
pytest-asyncio==1.4.0
pytest-cov
```

---

## Confidence Assessment

| Area | Confidence | Source | Notes |
|------|------------|--------|-------|
| FastAPI version + DI patterns | HIGH | Context7 official docs + PyPI | Verified against tiangolo.com docs |
| SQLAlchemy 2.x async patterns | HIGH | Context7 official docs + SQLAlchemy docs | `async_sessionmaker`, `expire_on_commit`, event hooks all verified |
| SQLite WAL PRAGMA pattern | HIGH | SQLAlchemy official docs + multiple production post-mortems | `engine.sync_engine` event hook is the correct async approach |
| aiosqlite + StaticPool for tests | HIGH | SQLAlchemy official docs (asyncio extension page) | Explicitly documented |
| httpx over aiohttp | MEDIUM | Multiple comparison articles; no official benchmark | Performance difference only matters at >100 concurrent outbound requests — not relevant here |
| structlog over loguru | MEDIUM | structlog official docs + community articles | Preference judgment; both are technically valid; contextvars advantage is real |
| Docker single-worker SQLite constraint | HIGH | SQLite file-locking documentation | Fundamental SQLite architectural limit |
| pytest-asyncio `asyncio_mode="auto"` | HIGH | pytest-asyncio 1.x docs | Default mode changed in 0.21; "auto" is idiomatic for 1.x |
| Alembic async template | HIGH | Alembic docs + multiple tutorials | `alembic init -t async` is the documented path for async engines |
| BackgroundTasks swappability | MEDIUM | Community patterns; no official Celery migration guide | Pattern is well-understood but the exact abstraction boundary is a design choice |

---

## Sources

- [FastAPI Official Docs — SQL Databases](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [FastAPI Official Docs — Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [FastAPI Official Docs — Settings / Environment Variables](https://fastapi.tiangolo.com/advanced/settings/)
- [FastAPI Official Docs — Docker Deployment](https://fastapi.tiangolo.com/deployment/docker/)
- [SQLAlchemy 2.0 — Asyncio Extension](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [SQLAlchemy 2.0 — SQLite Dialect / aiosqlite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- [SQLAlchemy 2.0 — Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [structlog Logging Best Practices](https://www.structlog.org/en/stable/logging-best-practices.html)
- [Setup FastAPI Project with Async SQLAlchemy 2, Alembic (berkkaraal.com)](https://berkkaraal.com/blog/2024/09/19/setup-fastapi-project-with-async-sqlalchemy-2-alembic-postgresql-and-docker/)
- [Async Testing with FastAPI and pytest (weirdsheeplabs.com)](https://weirdsheeplabs.com/blog/fast-and-furious-async-testing-with-fastapi-and-pytest)
- [FastAPI Docker Best Practices (betterstack.com)](https://betterstack.com/community/guides/scaling-python/fastapi-docker-best-practices/)
- [SQLite WAL Mode Production (daily.dev)](https://daily.dev/posts/sqlite-in-production-optimizing-wal-mode-concurrency-and-vfs-layers-for-low-latency-app-servers-wedvue3es)
- [FastAPI BackgroundTasks vs Celery (buildsmartengineering.substack.com)](https://buildsmartengineering.substack.com/p/fastapi-background-tasks-vs-celery)
- [HTTPX vs AIOHTTP (oxylabs.io)](https://oxylabs.io/blog/httpx-vs-requests-vs-aiohttp)
- [FastAPI API Key Authentication (joeriksson.se)](https://joeriksson.se/blog/fastapi-api-key-authentication/)
