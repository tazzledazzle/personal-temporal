# Architecture Patterns: Durable Workflow Executor

**Domain:** Workflow orchestration / Saga coordinator
**Researched:** 2026-10-07
**Confidence:** HIGH (verified against Temporal internals, SQLAlchemy docs, asyncio patterns)

---

## Recommended Architecture

The service is a single-process orchestrator following the **Orchestration Saga** pattern. A central coordinator (not choreography) owns all state transitions, issues outbound HTTP calls in sequence, and drives compensation in reverse order on failure. State is fully persisted to SQLite before any step is dispatched, making every run restartable.

---

## Component Diagram (ASCII)

```
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI Process                         │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   API Layer (routers/)                  │   │
│  │  POST /workflows          POST /runs                    │   │
│  │  GET  /runs/{id}          GET  /runs/{id}/steps         │   │
│  │  GET  /health             (auth middleware)             │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │ triggers via BackgroundTasks /      │
│                           │ asyncio.create_task()               │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │              Executor Engine (engine/)                  │   │
│  │                                                         │   │
│  │  WorkflowRunner          CompensationCoordinator        │   │
│  │  ─ step sequencing       ─ reverse-order execution      │   │
│  │  ─ state transitions     ─ compensated step tracking    │   │
│  │  ─ error detection       ─ partial-failure handling     │   │
│  │                                                         │   │
│  │  StepExecutor                                           │   │
│  │  ─ outbound HTTP via httpx.AsyncClient                  │   │
│  │  ─ retry with exponential backoff + jitter              │   │
│  │  ─ per-attempt logging                                  │   │
│  └──────────────┬──────────────────────────┬───────────────┘   │
│                 │                          │                    │
│  ┌──────────────▼──────┐   ┌──────────────▼───────────────┐   │
│  │  State Store (db/)  │   │  HTTP Client (http_client/)  │   │
│  │                     │   │                              │   │
│  │  WorkflowRepo       │   │  AsyncClient (httpx)         │   │
│  │  RunRepo            │   │  retry wrapper               │   │
│  │  StepRepo           │   │  timeout configuration       │   │
│  │                     │   │                              │   │
│  │  asyncio.Lock       │   └──────────────────────────────┘   │
│  │  (write serializer) │                                       │
│  │  aiosqlite / SA     │                                       │
│  └─────────────────────┘                                       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Infrastructure (core/)                      │  │
│  │  config.py  logging.py  auth.py  database.py lifespan.py│  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| API Layer | HTTP routing, request validation, auth enforcement, response serialization | Executor Engine (dispatches), State Store (reads) |
| WorkflowRunner | Executes one workflow run: steps in order, records transitions, triggers compensation | StepExecutor, State Store |
| CompensationCoordinator | Iterates completed steps in reverse, calls compensate URLs, records COMPENSATED/FAILED transitions | StepExecutor, State Store |
| StepExecutor | Single outbound HTTP call with retry loop; returns result or raises | HTTP Client |
| State Store (Repos) | Reads and writes all persisted state; owns optimistic-lock logic | SQLite via aiosqlite + SQLAlchemy async |
| HTTP Client | Shared `httpx.AsyncClient`; handles connection pooling and timeouts | External step URLs |
| Infrastructure | App config, structured logging, API key auth, DB pool init, lifespan startup | All components |

---

## Data Model

### Tables

```sql
-- Workflow definitions: registered blueprints
CREATE TABLE workflow_definitions (
    id          TEXT PRIMARY KEY,          -- slug: "order-fulfillment"
    name        TEXT NOT NULL,
    description TEXT,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version     INTEGER NOT NULL DEFAULT 1  -- optimistic lock
);

-- Ordered steps within a definition (immutable after creation)
CREATE TABLE workflow_steps (
    id              TEXT PRIMARY KEY,       -- uuid
    workflow_def_id TEXT NOT NULL REFERENCES workflow_definitions(id),
    step_order      INTEGER NOT NULL,       -- 0-based execution order
    name            TEXT NOT NULL,
    execute_url     TEXT NOT NULL,          -- HTTP POST target
    compensate_url  TEXT NOT NULL,          -- HTTP POST target for rollback
    timeout_seconds INTEGER NOT NULL DEFAULT 30,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    UNIQUE (workflow_def_id, step_order)
);

-- One row per workflow execution instance
CREATE TABLE workflow_runs (
    id              TEXT PRIMARY KEY,       -- uuid
    workflow_def_id TEXT NOT NULL REFERENCES workflow_definitions(id),
    status          TEXT NOT NULL,          -- see state machine below
    current_step    INTEGER,                -- step_order of active step; NULL when done
    input_data      TEXT,                   -- JSON blob of caller-supplied input
    error_message   TEXT,
    started_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME,
    version         INTEGER NOT NULL DEFAULT 1  -- optimistic lock
);

-- One row per step execution attempt (immutable append-only log)
CREATE TABLE step_executions (
    id              TEXT PRIMARY KEY,       -- uuid
    run_id          TEXT NOT NULL REFERENCES workflow_runs(id),
    step_id         TEXT NOT NULL REFERENCES workflow_steps(id),
    step_order      INTEGER NOT NULL,
    phase           TEXT NOT NULL,          -- "execute" | "compensate"
    status          TEXT NOT NULL,          -- PENDING | RUNNING | COMPLETED | FAILED | COMPENSATED
    attempt         INTEGER NOT NULL DEFAULT 1,
    request_body    TEXT,                   -- JSON sent to step URL
    response_body   TEXT,                   -- JSON received from step URL
    http_status     INTEGER,
    error_message   TEXT,
    started_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME,
    idempotency_key TEXT                    -- "{run_id}:{step_id}:{attempt}"
);
```

### Key Design Notes

- `workflow_runs.version` + `step_executions` are the durability backbone. The engine reads the run state, re-derives "where are we?" from step_executions on recovery after a crash.
- `step_executions` is append-only. Never update existing rows; create new rows for retries. This gives a full audit log at zero extra cost.
- `idempotency_key` on `step_executions` prevents double-dispatch on retry: before calling a step URL, check whether a COMPLETED execution for this key already exists.
- `workflow_definitions` and `workflow_steps` are effectively immutable after creation for simplicity; update semantics can be added in a later phase.

---

## State Machine Diagrams

### Workflow Run States

```
                   ┌─────────┐
                   │ PENDING │   (created, not yet dispatched)
                   └────┬────┘
                        │ executor picks up
                        ▼
                   ┌─────────┐
                   │ RUNNING │   (steps executing in sequence)
                   └────┬────┘
          ┌─────────────┼──────────────────┐
          │             │                  │
          │ all steps   │ step fails,      │ cancelled (future)
          │ succeeded   │ compensation     │
          ▼             │ triggered        ▼
   ┌──────────┐         │           ┌───────────┐
   │ COMPLETED│         ▼           │ CANCELLED │
   └──────────┘  ┌─────────────┐   └───────────┘
   (terminal)    │ COMPENSATING│
                 └──────┬──────┘
          ┌─────────────┴────────────────┐
          │                              │
          │ all compensations            │ compensation step
          │ succeeded                    │ permanently failed
          ▼                              ▼
   ┌──────────────┐             ┌──────────────────┐
   │ COMPENSATED  │             │ COMPENSATION_     │
   └──────────────┘             │ FAILED           │
   (terminal)                   └──────────────────┘
                                (terminal — needs human review)
```

### Step Execution States (per step_executions row)

```
PENDING ──► RUNNING ──► COMPLETED   (happy path)
                   └──► FAILED      (exhausted retries)

  (compensation phase)
PENDING ──► RUNNING ──► COMPENSATED
                   └──► FAILED
```

### Valid Workflow Run Transitions (enforced in code)

| From | To | Trigger |
|------|----|---------|
| PENDING | RUNNING | executor starts |
| RUNNING | COMPLETED | last step completes successfully |
| RUNNING | COMPENSATING | any step fails after exhausting retries |
| COMPENSATING | COMPENSATED | all compensation steps succeed |
| COMPENSATING | COMPENSATION_FAILED | any compensation step fails |

Any other transition raises a `InvalidStateTransitionError`.

---

## Data Flow: Request to Step HTTP Call to State Update

```
1. POST /runs  {workflow_name, input}
   │
   ├─ Auth middleware validates X-API-Key
   ├─ RunRepo.create(status=PENDING, input=input)   [SQLite write]
   ├─ HTTP 202 Accepted {run_id}  returned to caller
   └─ BackgroundTasks.add_task(execute_run, run_id)
         │
         ▼
2. WorkflowRunner.execute(run_id)
   │
   ├─ RunRepo.transition(run_id, PENDING → RUNNING)  [optimistic lock]
   │
   └─ for each step in order:
         │
         ├─ StepExecutionRepo.create(run_id, step_id, phase=execute, status=PENDING)
         ├─ StepExecutionRepo.transition(exec_id, PENDING → RUNNING)
         │
         ├─ StepExecutor.call(step, run_id, input_from_previous_step)
         │     │
         │     ├─ build idempotency_key = "{run_id}:{step_id}:{attempt}"
         │     ├─ check: is there already a COMPLETED execution for this key?
         │     │   YES → skip HTTP call, use cached result
         │     │   NO  → httpx.AsyncClient.post(execute_url, json=payload, timeout=step.timeout_seconds)
         │     │            [retry loop: max_retries, exponential backoff + jitter]
         │     └─ return (response_body, http_status)
         │
         ├─ if success:
         │     StepExecutionRepo.complete(exec_id, response_body, http_status)
         │     RunRepo.update_current_step(run_id, next_step_order)
         │
         └─ if failure (retries exhausted):
               StepExecutionRepo.fail(exec_id, error)
               RunRepo.transition(run_id, RUNNING → COMPENSATING)
               CompensationCoordinator.run(run_id)   [← see below]

3. CompensationCoordinator.run(run_id)
   │
   ├─ query step_executions WHERE run_id=? AND phase=execute AND status=COMPLETED
   │   ORDER BY step_order DESC   (reverse order)
   │
   └─ for each completed step (reverse):
         │
         ├─ StepExecutionRepo.create(run_id, step_id, phase=compensate, status=PENDING)
         ├─ StepExecutor.call(step, run_id, compensation_payload)
         │     [same retry logic, idempotency_key = "{run_id}:{step_id}:compensate:{attempt}"]
         │
         ├─ if success: StepExecutionRepo.complete(exec_id, ...)
         └─ if failure: StepExecutionRepo.fail(exec_id, ...)
                         mark RunRepo as COMPENSATION_FAILED, stop

   After loop:
   └─ all succeeded → RunRepo.transition(run_id, COMPENSATING → COMPENSATED)
      any failed    → RunRepo.transition(run_id, COMPENSATING → COMPENSATION_FAILED)
```

---

## Concurrent Execution Safety in SQLite

SQLite does not support row-level locks. `SELECT FOR UPDATE` is silently ignored by SQLAlchemy when using aiosqlite. The strategy below achieves safe concurrent workflow runs without row-level locks.

### Three-Layer Defense

**Layer 1: WAL mode + busy timeout (connection-level)**
```python
# Set once at DB init
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;   -- 5 seconds, per-connection
```
WAL allows concurrent readers alongside a writer. `busy_timeout` absorbs brief write collisions by retrying instead of immediately returning `SQLITE_BUSY`.

**Layer 2: asyncio.Lock for write serialization (application-level)**
```python
# core/database.py
_write_lock = asyncio.Lock()

async def write_transaction(session, fn):
    async with _write_lock:
        async with session.begin():
            return await fn(session)
```
A single module-level `asyncio.Lock` serializes all write transactions in application code. This eliminates the contention that makes WAL's single-writer limit problematic. In asyncio, only one coroutine holds the lock at a time; all others queue behind it cooperatively. This is zero-overhead for the single-node use case.

**Layer 3: Optimistic locking with version column (row-level safety)**
```python
# All mutable rows carry `version INTEGER NOT NULL DEFAULT 1`
# Update pattern:
result = await session.execute(
    update(WorkflowRun)
    .where(WorkflowRun.id == run_id, WorkflowRun.version == expected_version)
    .values(status=new_status, version=expected_version + 1)
)
if result.rowcount == 0:
    raise StaleDataError(f"Concurrent modification on run {run_id}")
```
Even if the `asyncio.Lock` serializes coroutines within one process, optimistic locking catches any edge case where two async tasks race within the same lock-acquisition window (e.g., during an `await` yield point inside a transaction). It also protects against future multi-process scenarios.

### Why Not a Connection Pool?

A pool with multiple writers does not help SQLite: the one-writer rule means pooled writers still queue at the DB level, generating contention and `SQLITE_BUSY` errors with no throughput benefit. A single shared connection serialized behind `asyncio.Lock` is strictly better for this workload.

---

## Patterns to Follow

### Pattern 1: Append-Only Step Execution Log

Never update a `step_executions` row. Create a new row for every retry attempt. Set `attempt=N` to distinguish retries. Query `status=COMPLETED` + highest `attempt` to find current state. This is the same principle as Temporal's append-only event history.

**Why:** Enables full audit trail, crash recovery by replaying completed steps, and idempotency checking all without additional tables.

### Pattern 2: Persist Before Dispatch

Write the `PENDING` step execution row to SQLite *before* making the outbound HTTP call. Write the `RUNNING` transition *before* calling. This means: if the process crashes between the write and the HTTP call, on restart the engine sees a `RUNNING` step with no result. It can re-check idempotency (did the HTTP call succeed on a prior attempt?) and retry safely.

**Why:** "Persist-before-act" is the core durability guarantee in Temporal, Step Functions, and every production workflow engine.

### Pattern 3: Idempotency Key Before HTTP Dispatch

```python
key = f"{run_id}:{step_id}:{attempt}"
existing = await step_repo.find_completed(idempotency_key=key)
if existing:
    return existing.response_body   # skip HTTP, return cached result
```

Check for a completed execution with this key *before* the outbound call. This means retries (after a crash mid-response) do not re-execute already-successful steps.

### Pattern 4: State Transition Guard Function

```python
VALID_RUN_TRANSITIONS = {
    ("PENDING", "RUNNING"),
    ("RUNNING", "COMPLETED"),
    ("RUNNING", "COMPENSATING"),
    ("COMPENSATING", "COMPENSATED"),
    ("COMPENSATING", "COMPENSATION_FAILED"),
}

def assert_valid_transition(from_status: str, to_status: str):
    if (from_status, to_status) not in VALID_RUN_TRANSITIONS:
        raise InvalidStateTransitionError(f"{from_status} → {to_status} is not allowed")
```

All state changes pass through this guard. Invalid transitions raise immediately rather than silently corrupting the state machine.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Update-in-Place Step Executions
**What:** Modify a `step_executions` row's status from PENDING → RUNNING → COMPLETED.
**Why bad:** Loses retry history, makes crash recovery ambiguous, eliminates audit trail.
**Instead:** Append a new row per attempt; query for terminal states.

### Anti-Pattern 2: Fire-and-Forget HTTP Without Pre-Persist
**What:** Call the step URL, then write to SQLite only on success.
**Why bad:** A crash after the HTTP call but before the DB write leaves the run stuck with no record of the successful call. Compensation would re-compensate a step that may have already been compensated.
**Instead:** Write PENDING → write RUNNING → make HTTP call → write result.

### Anti-Pattern 3: Long Transactions Holding Write Lock
**What:** Open a SQLite transaction, make an outbound HTTP call inside it, then commit.
**Why bad:** The transaction holds the DB write lock for the entire HTTP round-trip (potentially seconds). No other workflow can write. This is the primary source of "database is locked" errors in async SQLite services.
**Instead:** Commit the RUNNING state, release the lock, make the HTTP call, then re-acquire the lock to commit the result.

### Anti-Pattern 4: Compensation Registered Before Step Succeeds
**What:** Pre-populate compensation steps at run creation time.
**Why bad:** Compensates steps that never executed; produces its own inconsistency.
**Instead:** Only add a compensation candidate when the execute phase returns COMPLETED.

### Anti-Pattern 5: Blocking I/O in the Event Loop
**What:** Using `sqlite3` (sync) or `requests` (sync) directly inside `async def` handlers.
**Why bad:** Blocks the entire asyncio event loop; no other coroutines can run during that I/O.
**Instead:** `aiosqlite` via SQLAlchemy async for DB; `httpx.AsyncClient` for outbound HTTP.

---

## Scalability Considerations

| Concern | At Single Node (current) | At Multi-Process | At Distributed |
|---------|--------------------------|-----------------|----------------|
| Write concurrency | asyncio.Lock serializes writes; WAL handles reads | Switch to PostgreSQL with row-level locks | Replace state store with distributed DB |
| Executor scaling | asyncio.create_task() per run | Celery workers, run_id as task key | Temporal / Conductor |
| Step retry durability | SQLite persists retries | Same, now multi-worker safe | Worker-local state → distributed queue |
| Compensation correctness | Single process, no split-brain | Lease/lock on run_id | Distributed lock (Redis, etcd) |

The architecture is explicitly designed for the handoff from asyncio to Celery: `WorkflowRunner.execute()` is a pure async function. Replacing `BackgroundTasks.add_task(execute_run, run_id)` with `celery_app.send_task("execute_run", args=[run_id])` is the only callsite change required.

---

## Suggested Module / Package Structure

```
workflow_executor/
├── main.py                         # FastAPI app factory, mounts routers
├── lifespan.py                     # @asynccontextmanager startup/shutdown
│
├── core/
│   ├── config.py                   # Pydantic Settings (env vars)
│   ├── database.py                 # async engine, session factory, _write_lock
│   ├── auth.py                     # X-API-Key dependency
│   ├── logging.py                  # structlog setup, request-id injection
│   └── exceptions.py               # InvalidStateTransitionError, StaleDataError, etc.
│
├── workflows/                      # domain: workflow definitions
│   ├── models.py                   # SQLAlchemy: WorkflowDefinition, WorkflowStep
│   ├── schemas.py                  # Pydantic: CreateWorkflowRequest, WorkflowResponse
│   ├── repository.py               # WorkflowRepo (reads + writes)
│   └── router.py                   # POST /workflows, GET /workflows/{id}
│
├── runs/                           # domain: workflow run instances
│   ├── models.py                   # SQLAlchemy: WorkflowRun, StepExecution
│   ├── schemas.py                  # Pydantic: CreateRunRequest, RunResponse, StepResponse
│   ├── repository.py               # RunRepo, StepExecutionRepo (optimistic lock logic lives here)
│   └── router.py                   # POST /runs, GET /runs/{id}, GET /runs/{id}/steps
│
├── engine/                         # executor engine (no FastAPI imports)
│   ├── runner.py                   # WorkflowRunner.execute(run_id)
│   ├── step_executor.py            # StepExecutor: single HTTP call + retry loop
│   ├── compensation.py             # CompensationCoordinator.run(run_id)
│   └── state_machine.py            # VALID_TRANSITIONS, assert_valid_transition()
│
├── http_client/
│   └── client.py                   # shared httpx.AsyncClient, lifespan-managed
│
├── migrations/
│   └── init.sql                    # or Alembic migrations/
│
├── tests/
│   ├── conftest.py                 # in-memory SQLite, test client, mock httpx
│   ├── test_runner.py              # WorkflowRunner unit tests
│   ├── test_compensation.py        # CompensationCoordinator unit tests
│   ├── test_api_workflows.py       # API integration tests
│   └── test_api_runs.py            # API integration tests
│
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

### Dependency Rules

- `engine/` has no imports from `workflows/router.py` or `runs/router.py` (no circular dep)
- `engine/` imports from `runs/repository.py`, `workflows/repository.py`, `http_client/`
- `runs/router.py` imports from `runs/repository.py` (reads) and `engine/runner.py` (dispatches)
- `core/` is imported by everything; it imports nothing from the domain modules

---

## Build Order Recommendations

The dependency chain drives this order. Each phase builds on the previous one.

```
1. core/            → config, DB setup, auth, logging
                      (no business logic; everything depends on this)

2. workflows/       → models, repository, router for definitions
                      (can be tested independently with in-memory SQLite)

3. runs/ (models)   → WorkflowRun and StepExecution models, RunRepo
                      (no engine yet; just persistence)

4. engine/ (runner) → WorkflowRunner with happy-path step sequencing
                      (wire up with stub HTTP client; test without real steps)

5. engine/ (step_executor) → real httpx calls, retry loop, idempotency check
                      (mock the URLs in tests using httpx.MockTransport)

6. engine/ (compensation) → CompensationCoordinator
                      (requires: runs models, step_executor)

7. runs/ (router)   → POST /runs dispatch, GET /runs/{id}, GET /runs/{id}/steps
                      (wires the API surface to the engine)

8. observability    → structured logging across all layers, /health endpoint
                      (cross-cutting, add last so it doesn't block functionality)

9. Docker           → Dockerfile, docker-compose, env configuration
```

---

## Sources

- [Temporal: Workflow Engine Design Principles](https://temporal.io/blog/workflow-engine-principles) — transactionality, transfer queues, sharding
- [Temporal: Mastering Saga Patterns](https://temporal.io/blog/mastering-saga-patterns-for-distributed-transactions-in-microservices) — compensation model
- [Temporal: Saga Pattern Design](https://docs.temporal.io/design-patterns/saga-pattern) — register-on-success rule
- [SQLite Concurrent Writes and "database is locked"](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/) — WAL internals, MEDIUM confidence
- [Fix SQLite "Database Is Locked" Errors Under Concurrent Writes](https://oneuptime.com/blog/post/2026-09-08-fix-sqlite-database-is-locked-concurrent-writes/view) — busy_timeout, WAL setup
- [Serialize DB writes behind an async lock (GitHub PR)](https://github.com/guzalv/chait/pull/19) — asyncio.Lock pattern for aiosqlite
- [SQLAlchemy Async I/O Documentation](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html) — async engine, session, aiosqlite
- [Implementing Optimistic Locking in SQLAlchemy](https://oneuptime.com/blog/post/2026-01-25-optimistic-locking-sqlalchemy/view) — version column pattern, StaleDataError
- [FastAPI Background Tasks and Async](https://thecodeforge.io/python/fastapi-background-tasks-async/) — BackgroundTasks vs create_task()
- [Python Background Tasks — Asyncio Traps, FastAPI & Celery](https://dev.to/kaushikcoderpy/python-background-tasks-asyncio-traps-fastapi-celery-2026-381i) — durability limits of BackgroundTasks
- [OpenStack TaskFlow States](https://docs.openstack.org/taskflow/pike/user/states.html) — PENDING/RUNNING/SUCCESS/FAILURE state semantics
- [Clean Architecture Structure for FastAPI](https://www.launch.ist/blog/clean-architecture-structure/) — module layout guidance
