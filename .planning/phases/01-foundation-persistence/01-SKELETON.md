---
phase: 01-foundation-persistence
created: 2026-10-07
status: draft
---

# Walking Skeleton — Multi-Step Workflow Executor

## Phase Goal

**As a** developer evaluating this service, **I want to** register a workflow definition and immediately query it back through a healthy, authenticated API, **so that** I can verify the full stack (auth middleware → route handler → async DB layer → SQLite) is wired correctly before building the execution engine.

---

## Architectural Decisions

These decisions are locked for all subsequent phases. Changing them requires a deliberate phase-split decision.

### Framework & Server

| Decision | Value | Rationale |
|----------|-------|-----------|
| REST framework | FastAPI 0.142.2 | Native async, auto OpenAPI, `APIKeyHeader` built-in, `lifespan` context manager |
| ASGI server | uvicorn[standard] 0.54.0 | Standard FastAPI server; `[standard]` adds `httptools` + `uvloop` |
| Workers | **1 (hardcoded in Dockerfile CMD)** | SQLite single-writer constraint; multi-worker = file lock contention = data corruption |

### Database

| Decision | Value | Rationale |
|----------|-------|-----------|
| Database | SQLite | Zero-infra, self-contained; async migration path to Postgres straightforward |
| ORM | SQLAlchemy 2.1.4 async + aiosqlite 0.22.1 | Only async-native combo for SQLite; `async_sessionmaker` + `expire_on_commit=False` required |
| Pool (production) | `NullPool` | Prevents connection pool issues with SQLite file locking |
| Pool (test) | `StaticPool` | Forces all async calls through one in-memory connection |
| Migration tool | Alembic 1.20.0 (`alembic init -t async`) | First-party SQLAlchemy tool; async template required |
| WAL mode | `PRAGMA journal_mode=WAL` on every connection | Concurrent readers + single writer; persists per-file |
| Busy timeout | `PRAGMA busy_timeout=5000` on every connection | Connection-scoped; must be set via `event.listens_for(engine.sync_engine, "connect")` |
| Synchronous | `PRAGMA synchronous=NORMAL` | Balanced durability/performance |
| Concurrency guard | `asyncio.Lock()` at module level in `core/database.py` | Serializes all write coroutines within the single process |
| Optimistic lock | `version: Mapped[int]` column on all mutable models | Prevents lost updates under concurrent write contention |

### Authentication

| Decision | Value | Rationale |
|----------|-------|-----------|
| Auth scheme | API key (`X-API-Key` header) | Simpler than JWT for interview demo; JWT adds complexity without showcasing the engine |
| Key storage | `pydantic-settings SecretStr` from env var `API_KEY` | Type-safe, masked in repr/logs |
| Key comparison | `secrets.compare_digest()` | Timing-safe; prevents brute-force enumeration |
| Scope | All endpoints except `GET /health` | Health is a public infrastructure probe |

### Logging

| Decision | Value | Rationale |
|----------|-------|-----------|
| Library | structlog 26.1.0 | `contextvars` integration; `bind_contextvars()` propagates across async boundaries |
| Format | JSON (production), ConsoleRenderer (dev) | Controlled by `LOG_JSON` env var |
| Context injection | `CorrelationIdMiddleware` via `BaseHTTPMiddleware` | Binds `correlation_id`, `path`, `method` on every request; `clear_contextvars()` first |
| Correlation ID | `X-Correlation-ID` header (generated as UUID if absent) | Echoed back in response header |

### Settings

| Decision | Value | Rationale |
|----------|-------|-----------|
| Settings class | `pydantic-settings BaseSettings` + `SettingsConfigDict(env_file=".env")` | Type coercion, `.env` support, `SecretStr` masking |
| Cache | `@lru_cache` on `get_settings()` | Single settings instance per process |

### Testing

| Decision | Value | Rationale |
|----------|-------|-----------|
| Async test mode | `asyncio_mode = "auto"` in `pyproject.toml` | Eliminates per-test `@pytest.mark.asyncio`; missing this causes silent test skips |
| DB isolation | `StaticPool` + `:memory:` per test session | Prevents cross-test contamination; same PRAGMAs as production |
| HTTP client | `httpx.AsyncClient(transport=ASGITransport(app=app))` | Fully async; sync `TestClient` blocks the event loop |
| Auth override | `app.dependency_overrides[get_db]` in conftest | Standard FastAPI test pattern |

### Compensation / Execution Pattern

| Decision | Value | Rationale |
|----------|-------|-----------|
| Saga pattern | Orchestration (single coordinator) | One service owns all state; easier to reason about than choreography |
| Execution dispatch | FastAPI `BackgroundTasks` (Phase 2) | Decoupled from ASGI; swappable to Celery by changing one call-site |
| Persist-before-dispatch | Mandatory | Every state change written to DB before outbound HTTP; crash leaves auditable state |

---

## Directory Layout

```
/
├── app/
│   ├── main.py                    # FastAPI app factory + lifespan; mounts all routers
│   ├── lifespan.py                # @asynccontextmanager startup/shutdown
│   │
│   ├── core/
│   │   ├── config.py              # pydantic-settings Settings; get_settings() with @lru_cache
│   │   ├── database.py            # create_engine(); AsyncSessionLocal; _write_lock; get_db()
│   │   ├── auth.py                # APIKeyHeader; verify_api_key() with secrets.compare_digest
│   │   ├── logging.py             # configure_structlog(); CorrelationIdMiddleware
│   │   └── exceptions.py          # StaleDataError, NotFoundError, ConflictError
│   │
│   ├── workflows/
│   │   ├── models.py              # WorkflowDefinition, WorkflowStep (SQLAlchemy mapped columns)
│   │   ├── schemas.py             # CreateWorkflowRequest, WorkflowResponse, StepSchema (Pydantic v2)
│   │   ├── repository.py          # WorkflowRepo: create, get_by_name, list_all, delete_by_name
│   │   └── router.py              # POST /workflows, GET /workflows, GET /workflows/{name}, DELETE /workflows/{name}
│   │
│   ├── runs/
│   │   └── models.py              # WorkflowRun stub (schema only; populated Phase 2)
│   │
│   └── health/
│       └── router.py              # GET /health — public; DB probe via SELECT 1
│
├── migrations/                    # alembic init -t async output
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py
│
├── tests/
│   ├── conftest.py                # StaticPool engine, db_session, client, client_no_auth fixtures
│   ├── test_health.py             # PLAT-03: health smoke tests
│   ├── test_auth.py               # PLAT-01: API key tests
│   ├── test_workflows.py          # DEFN-01, DEFN-02, DEFN-03: CRUD tests
│   ├── test_database.py           # RESIL-04: WAL mode + asyncio.Lock tests
│   └── test_logging.py            # PLAT-02: correlation_id in log output
│
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                 # asyncio_mode="auto"; pinned dependencies
├── .env.example
└── alembic.ini
```

---

## End-to-End Request Flow

```
HTTP Request
    │
    ▼
CorrelationIdMiddleware
    clear_contextvars() → bind_contextvars(correlation_id, path, method)
    │
    ▼
APIKeyHeader Security dependency
    secrets.compare_digest(provided, expected) → 401 if fail
    │
    ▼
FastAPI Route Handler (workflows/router.py)
    Pydantic validation → 422 on bad input
    │
    ▼
WorkflowRepo (repository.py)
    asyncio.Lock → async with session.begin() → SQL → commit
    │
    ▼
AsyncSession → aiosqlite thread pool
    PRAGMA journal_mode=WAL + busy_timeout=5000 on every connection
    │
    ▼
SQLite file (/app/data/workflows.db)
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | — | API key for `X-API-Key` header; minimum 32 chars recommended |
| `DATABASE_URL` | Yes | `sqlite+aiosqlite:////app/data/workflows.db` | SQLite file path (aiosqlite driver) |
| `LOG_JSON` | No | `true` | `true` = JSON logs; `false` = console renderer |
| `APP_VERSION` | No | `0.1.0` | Returned by `GET /health` |

---

## Phase 1 Delivery Checklist

- [ ] `pyproject.toml` with pinned versions + `asyncio_mode = "auto"`
- [ ] Async SQLite engine factory with WAL + busy_timeout + asyncio.Lock
- [ ] `WorkflowDefinition` + `WorkflowStep` SQLAlchemy models with `version` column
- [ ] `WorkflowRun` model stub (schema only; needed for DEFN-03 delete guard)
- [ ] Pydantic v2 schemas: `CreateWorkflowRequest`, `WorkflowResponse`
- [ ] `WorkflowRepo`: `create`, `get_by_name`, `list_all`, `delete_by_name` (with active-run guard)
- [ ] `POST /workflows` → 201, `GET /workflows` → 200, `GET /workflows/{name}` → 200/404, `DELETE /workflows/{name}` → 204/404/409
- [ ] `GET /health` (public) → 200 healthy / 503 DB unreachable
- [ ] `verify_api_key` dependency with `secrets.compare_digest`; 401 on missing/wrong key
- [ ] `CorrelationIdMiddleware` binding `correlation_id` via contextvars
- [ ] Alembic migration for initial schema
- [ ] Dockerfile (`--workers 1` in CMD) + docker-compose.yml (named volume)
- [ ] pytest suite: conftest + 5 test files, all green
- [ ] `pytest tests/ -x -q` exits 0

---

*Walking Skeleton recorded: 2026-10-07*
