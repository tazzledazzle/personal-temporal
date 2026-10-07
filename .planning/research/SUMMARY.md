# Project Research Summary

**Project:** Multi-Step Workflow Executor (Python + FastAPI + SQLite + Saga)
**Domain:** Durable workflow orchestration — Saga pattern coordinator
**Researched:** 2026-10-07
**Confidence:** HIGH

## Executive Summary

This is an orchestration-style Saga coordinator: a central REST service that accepts workflow definitions (ordered steps with execute/compensate HTTP URLs), runs them sequentially, persists every state transition to SQLite, and automatically compensates completed steps in reverse order on failure. The expert approach — validated against Temporal, AWS Step Functions, and Netflix Conductor — is "persist before dispatch": every state change is written to the database before any outbound HTTP call is made. This is the single most important design principle in the entire system; everything else flows from it.

The recommended stack is FastAPI 0.142 + SQLAlchemy 2.1 async + aiosqlite + httpx, all operating inside a single Uvicorn process. This is not a compromise — SQLite's single-writer constraint makes multi-process deployment actively harmful, and the asyncio concurrency model is sufficient for an interview-scale service. The architecture is explicitly designed for a clean hand-off to Celery: `WorkflowRunner.execute()` is a pure async function decoupled from FastAPI internals, so swapping `BackgroundTasks` for `celery_app.send_task()` requires changing exactly one call-site.

The top risks are all durability-related: step double-execution due to missing idempotency keys, zombie runs stuck in RUNNING after a process crash, and silent exception swallowing in background tasks that leaves state permanently corrupted. All three must be addressed in Phase 1 — they cannot be retrofitted. The compensation path carries a secondary risk: a naive implementation that stops on the first compensation failure leaves resources permanently allocated. Compensation must be continue-on-failure with per-step retry from the first working version.

---

## Key Findings

### Recommended Stack

The stack is fully async end-to-end: FastAPI dispatches work to `BackgroundTasks`, SQLAlchemy async sessions talk to SQLite via aiosqlite, and outbound HTTP step calls use `httpx.AsyncClient`. Any synchronous I/O in the event loop (stdlib `sqlite3`, `requests`) blocks all concurrent runs — this is the primary correctness constraint that drives every library choice.

**Core technologies:**

- **FastAPI 0.142 + Uvicorn 0.54:** REST framework with native async, auto-generated OpenAPI, and `BackgroundTasks` for in-process workflow dispatch. Use `lifespan` context manager (not deprecated `on_event` hooks) for startup/shutdown.
- **SQLAlchemy 2.1 async + aiosqlite 0.22:** The only async-native ORM + driver combination for SQLite. Requires `expire_on_commit=False` on `async_sessionmaker` and WAL mode + `busy_timeout` set via `event.listens_for(engine.sync_engine, "connect")`.
- **Alembic 1.20 (async template):** `alembic init -t async` generates the correct async `env.py`. The default synchronous template silently fails against an async engine.
- **httpx 0.28:** Async HTTP client for outbound step calls. Prefer over aiohttp for this workload: steps execute sequentially per run (not fan-out), and httpx's DX and test integration (`ASGITransport`) are superior. Never use `requests` — it blocks the event loop.
- **structlog 26.1:** Structured logging with `contextvars` integration. Propagates `run_id`, `step_id`, and `correlation_id` across async boundaries automatically via `bind_contextvars()` in middleware.
- **pydantic-settings 2.15:** Settings management; reads from env vars and `.env` files; cache with `@lru_cache`.
- **pytest-asyncio 1.4 + `asyncio_mode="auto"`:** Eliminates per-test `@pytest.mark.asyncio` decoration; use `StaticPool` + `:memory:` for unit tests, `NullPool` + temp file for integration tests.

**Critical configuration flags that must be set from day 1:**
- `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000` on every connection
- `expire_on_commit=False` on `async_sessionmaker`
- `--workers 1` in Docker CMD (SQLite single-writer constraint)
- Named Docker volume for the `.db` file (not a project-directory bind mount)

See [STACK.md](STACK.md) for pinned versions and full configuration code.

### Expected Features

The boundary between "workflow engine" and "task runner" is durable state + saga compensation. Without both, this is not a workflow engine.

**Must have (table stakes):**
- Register workflow definitions (name + ordered steps + execute/compensate URLs)
- Execute workflow by name — returns `run_id` immediately (202 Accepted), executes async
- Durable per-run state: `PENDING → RUNNING → COMPLETED / COMPENSATING → COMPENSATED / COMPENSATION_FAILED`
- Per-step execution state with full history (`step_executions` append-only log)
- Saga compensation: on any step failure, call compensate URLs in strict reverse-completion order
- Query run status (`GET /executions/{run_id}`) and step history (`GET /executions/{run_id}/steps`)
- Per-step HTTP timeout — steps that never respond must not block the engine
- API key authentication (`X-API-Key`) on all endpoints
- Health endpoint (`GET /health`)
- Structured JSON logging with `run_id` correlation on every log line

**Should have (low complexity, high interview signal):**
- Distinct `COMPENSATING` / `COMPENSATED` states (most basic engines collapse to `FAILED`)
- Per-step compensation status in history (`compensated_at`, `compensation_error`)
- List executions with status filter (`GET /executions?status=FAILED`)
- Run input payload forwarded to each step HTTP body
- `correlation_id` on runs (client-supplied reference, indexed)
- Cancel endpoint (`POST /executions/{run_id}/cancel`)

**Defer (explicit scope boundaries):**
- Retry policy per step (MVP defaults to single attempt; model can be defined but not enforced)
- Idempotency key on the execute endpoint
- Workflow versioning, parallel steps, scheduling, UI

See [FEATURES.md](FEATURES.md) for full state vocabulary and schema fields.

### Architecture Approach

The service is a single-process **orchestration Saga** (not choreography): one coordinator owns all state transitions, issues HTTP calls in sequence, and drives reverse-order compensation on failure. Components are organized into four tiers — API Layer, Executor Engine, State Store, and Infrastructure — with a hard dependency rule: the `engine/` package has zero imports from `workflows/router.py` or `runs/router.py`, making it independently testable and Celery-migratable.

**Major components:**
1. **API Layer (`routers/`)** — HTTP routing, request validation, auth enforcement; dispatches runs via `BackgroundTasks`; reads state via repos
2. **WorkflowRunner (`engine/runner.py`)** — drives step sequencing, state transitions, compensation trigger; pure async function with no FastAPI dependency
3. **CompensationCoordinator (`engine/compensation.py`)** — reverse-order compensation loop; continue-on-failure; records per-step compensation outcome
4. **StepExecutor (`engine/step_executor.py`)** — single outbound HTTP call with retry loop, idempotency key check, `httpx.Timeout` + `asyncio.timeout` wrapping
5. **State Store (`runs/repository.py`, `workflows/repository.py`)** — all DB reads and writes; owns optimistic lock (version column) and `asyncio.Lock` write serialization
6. **Infrastructure (`core/`)** — config, database engine factory, auth dependency, structlog setup, exception types

**The one critical data flow (persist-before-dispatch):**
```
POST /runs → write PENDING to DB → HTTP 202 → BackgroundTasks dispatch
  → write RUNNING → for each step: write PENDING → write RUNNING → HTTP call
  → write result → next step or trigger compensation
```
The DB is written before every outbound action. A crash at any point leaves auditable state; recovery reads `step_executions` to determine exactly where to resume.

See [ARCHITECTURE.md](ARCHITECTURE.md) for full component diagram, data model DDL, state machine transitions, and concurrent-write safety strategy.

### Critical Pitfalls

These five issues cause silent data corruption or permanent state inconsistency. All must be designed in from Phase 1; none can be retrofitted.

1. **Step double-execution (no idempotency key)** — Pass `X-Idempotency-Key: {run_id}-{step_index}-{attempt}` on every outbound HTTP call; write `STEP_STARTED` + key to DB *before* the call; check for an existing `COMPLETED` record with that key before re-dispatching. Without this, a crash-and-restart causes every in-flight step to execute twice.

2. **Zombie runs stuck RUNNING after process crash** — `BackgroundTasks` leaves no cleanup hook on crash. Add a startup recovery sweep: on boot, query all `RUNNING` / `EXECUTING` rows older than a staleness window and transition them to `FAILED`; trigger compensation for their completed steps. Requires `last_heartbeat_at` column in the schema from day 1.

3. **SQLite "database is locked" under concurrent async writes** — Enable `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000` at engine init via `event.listens_for(engine.sync_engine, "connect")`. Additionally, never hold an open write transaction across an outbound HTTP call — commit before the HTTP call, re-acquire after. An `asyncio.Lock` at the application level serializes writes and eliminates the contention that WAL alone cannot prevent.

4. **Silent exception swallowing in BackgroundTasks** — FastAPI has already sent HTTP 202 when the background task runs; unhandled exceptions have no response to attach to and are dropped by asyncio's weak task reference. Wrap the entire task body in `try/except Exception`: on any error, write a terminal state (`FAILED`) to the DB, log with `exc_info=True` and structured fields, then trigger compensation. Never let the task function exit without writing a terminal state.

5. **Compensation chain stopping on first failure** — A compensation HTTP call that times out or returns 5xx must not halt compensation for the remaining steps. Log the failure, record `COMPENSATION_FAILED` for that step, and continue compensating the remaining steps. Zombie resource allocations (unfunded refunds, unreleased inventory) from incomplete compensation are permanent without manual operator intervention.

See [PITFALLS.md](PITFALLS.md) for the full severity matrix (15 pitfalls) and phase-specific warnings.

---

## Implications for Roadmap

The component dependency chain from ARCHITECTURE.md maps directly to phases. Each phase is independently testable before the next begins.

### Phase 1: Foundation and Persistence
**Rationale:** Everything depends on the database layer, async engine configuration, and infrastructure setup. The WAL mode pragmas, `asyncio.Lock`, `expire_on_commit=False`, and test isolation strategy must be correct before any feature code is written. Retrofitting these later breaks concurrent-run safety.
**Delivers:** Working async DB engine; workflow definition CRUD; durable `WorkflowRun` and `StepExecution` models; API key auth; health endpoint; structlog middleware; test harness with `StaticPool` in-memory DB.
**Addresses features:** Register/retrieve workflow definitions; API key auth; health endpoint; structured logging.
**Avoids pitfalls:** Pitfall 3 (SQLite locking), Pitfall 9 (test isolation), Pitfall 10 (pool misconfiguration), Pitfall 14 (`expire_on_commit`).

### Phase 2: Execution Engine — Happy Path
**Rationale:** The `WorkflowRunner` and `StepExecutor` are the core engine. Build the happy path (all steps succeed) before adding failure handling. This validates the persist-before-dispatch data flow and idempotency key logic at the simplest level.
**Delivers:** `POST /executions/{name}` → async execution → `PENDING → RUNNING → COMPLETED` state transitions; per-step HTTP calls via `httpx.AsyncClient` with `httpx.Timeout` + `asyncio.timeout`; step execution log (append-only); idempotency key generation and pre-dispatch check; background task exception wrapper (terminal state on any unhandled error).
**Uses:** httpx, `asyncio.Lock`, optimistic version column, structlog `bind_contextvars`.
**Implements:** WorkflowRunner, StepExecutor, State Store write path.
**Avoids pitfalls:** Pitfall 1 (double-execution), Pitfall 7 (silent exception swallowing), Pitfall 8 (missing hard deadline), Pitfall 15 (task GC).

### Phase 3: Saga Compensation
**Rationale:** Compensation is a first-class engine capability, not error handling. It requires the append-only `step_executions` log (built in Phase 2) and strict reverse-completion ordering. The continue-on-failure requirement makes this phase non-trivial and must be built correctly from the start.
**Delivers:** `RUNNING → COMPENSATING → COMPENSATED / COMPENSATION_FAILED` state machine; `CompensationCoordinator` with per-step retry and continue-on-failure loop; per-step `compensation_error` / `compensated_at` fields in history; `COMPENSATING` / `COMPENSATED` as distinct API states.
**Uses:** `StepExecutor` (reused with compensation idempotency key), `step_executions` phase column.
**Implements:** CompensationCoordinator, state machine transition guard.
**Avoids pitfalls:** Pitfall 4 (silent partial compensation), Pitfall 5 (wrong compensation order), Pitfall 6 (non-idempotent compensation).

### Phase 4: Observability, Control, and Resilience
**Rationale:** The engine is correct by Phase 3 but not production-observable. This phase adds the startup recovery sweep (zombie detection), cancel endpoint, list-with-filter endpoint, and workflow definition snapshot at run creation. These are cross-cutting and can be added without changing the core execution loop.
**Delivers:** Startup recovery sweep (`RUNNING` rows older than staleness window → `FAILED` + compensation); `POST /executions/{run_id}/cancel`; `GET /executions?status=FAILED`; workflow definition snapshotted into run record at creation time; `last_heartbeat_at` column updated during execution; `correlation_id` on runs.
**Avoids pitfalls:** Pitfall 2 (zombie runs), Pitfall 13 (definition mutation breaks in-progress runs).

### Phase 5: Containerization and Integration Tests
**Rationale:** Docker configuration has a hard constraint (single worker, named volume) that must be correct before the service is considered deliverable. End-to-end integration tests with a real SQLite file complete the interview showcase.
**Delivers:** `Dockerfile` + `docker-compose.yml` with named volume and `--workers 1`; end-to-end integration tests (register → execute → compensate flow); CI-ready test suite with coverage report.
**Uses:** `pytest-asyncio`, `httpx.MockTransport` for step URL mocking, `AsyncClient(transport=ASGITransport(app=app))` for API tests.
**Avoids pitfalls:** Pitfall 3 (multi-worker SQLite), Docker volume data-loss trap.

### Phase Ordering Rationale

- **Phases 1 → 2 → 3** follow strict component dependencies: DB must exist before models, models before engine, happy path before compensation.
- **Phase 4 before Phase 5** ensures the service is correct and resilient before containerization — debugging zombie-run issues inside Docker is harder than catching them with unit tests first.
- The five CRITICAL pitfalls from PITFALLS.md map cleanly across Phases 1-3: pitfalls 3, 9, 10, 14 in Phase 1; pitfalls 1, 7, 8 in Phase 2; pitfalls 4, 5, 6 in Phase 3. This mapping means no critical pitfall is left unaddressed until late in the build.
- The `engine/` package has no FastAPI imports by design, which means Phases 2 and 3 can be unit-tested without spinning up the full ASGI app.

### Research Flags

Phases with well-documented patterns (skip additional research-phase):
- **Phase 1:** FastAPI + SQLAlchemy async setup is thoroughly documented; STACK.md contains the exact PRAGMA and sessionmaker configuration needed.
- **Phase 5:** Docker single-process SQLite pattern is documented in STACK.md; pytest-asyncio integration testing patterns are documented in PITFALLS.md.

Phases likely needing careful design review (not external research, but internal design):
- **Phase 2:** The exact boundary between "idempotency key check" and "persist-before-dispatch" is subtle. The ARCHITECTURE.md data flow diagram specifies the correct ordering — follow it exactly.
- **Phase 3:** LIFO ordering via `completed_at DESC` (not step definition order) is the easy-to-miss detail. Pitfall 5 explains why definition order is wrong.
- **Phase 4:** The startup recovery sweep interacts with the compensation system — recovering a `RUNNING` run may need to trigger compensation for its completed steps. Design this interaction explicitly before implementing.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library choices verified against official docs via Context7; PRAGMA configuration and pool settings cross-referenced against SQLAlchemy asyncio extension docs |
| Features | HIGH | Grounded in Temporal, AWS Step Functions, and Conductor OSS documentation; state vocabulary is industry-standard |
| Architecture | HIGH | Component boundaries and data flow patterns verified against Temporal internals and SQLAlchemy async docs; asyncio.Lock + WAL strategy confirmed in production post-mortems |
| Pitfalls | HIGH | Critical pitfalls (1, 2, 3, 4, 7) verified against multiple independent sources including FastAPI docs, asyncio behavior docs, and Saga pattern literature |

**Overall confidence:** HIGH

### Gaps to Address

- **Startup recovery sweep design:** PITFALLS.md identifies the need (Pitfall 2) and ARCHITECTURE.md notes the pattern, but the exact SQL query and `last_heartbeat_at` update interval are design decisions left for Phase 4 planning. Decide on staleness window (suggested: 5 minutes) and whether recovery triggers compensation automatically or requires operator confirmation.

- **Definition snapshot format:** PITFALLS.md (Pitfall 13) recommends snapshotting the workflow definition into the run record at creation time, but the exact storage format (JSON blob vs. FK snapshot table) is not specified. JSON blob on `workflow_runs.definition_snapshot` is the simpler choice for SQLite at this scale.

- **Retry policy in MVP:** FEATURES.md defers per-step retry enforcement to post-MVP but recommends defining the `RetryPolicy` model. Clarify during Phase 2 planning whether the `StepExecutor` implements a fixed retry count (e.g., 3) or respects a per-step field. A hardcoded default with a configurable field avoids the model-without-enforcement inconsistency.

- **httpx.MockTransport vs. live test services:** Tests for `StepExecutor` should use `httpx.MockTransport` to avoid real network calls, but the exact mock harness for testing compensation ordering is not specified. Design the test double in Phase 2 so Phase 3 can reuse it.

---

## Sources

### Primary (HIGH confidence)
- FastAPI official docs (tiangolo.com) — DI patterns, BackgroundTasks, lifespan, Docker deployment
- SQLAlchemy 2.0 asyncio extension docs — `async_sessionmaker`, `expire_on_commit`, aiosqlite, StaticPool
- SQLAlchemy 2.0 SQLite dialect docs — WAL pragma via `event.listens_for(engine.sync_engine, ...)`
- Temporal workflow engine design — persist-before-dispatch, append-only event history, Saga compensation model
- AWS Step Functions API reference — execution state vocabulary
- Netflix Conductor OSS — workflow definition schema, step states

### Secondary (MEDIUM confidence)
- Multiple production blog posts on SQLite WAL + aiosqlite concurrency (daily.dev, oneuptime.com, tenthousandmeters.com)
- FastAPI BackgroundTasks vs. Celery comparison articles — BackgroundTasks swappability pattern
- pytest-asyncio 1.x docs — `asyncio_mode="auto"` and event loop scope behavior
- httpx vs. aiohttp comparison articles — sequential-call workload tradeoffs

### Tertiary (noted limitations)
- BackgroundTasks swappability abstraction boundary — community pattern, no official Celery migration guide; design is sound but specific wrapper code is a judgment call
- `asyncio.Lock` as write serializer — documented in SQLAlchemy community resources; not explicitly in official docs but consistent with asyncio semantics

---
*Research completed: 2026-10-07*
*Ready for roadmap: yes*
