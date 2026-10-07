# Domain Pitfalls: Durable Workflow Executor

**Domain:** Durable workflow executor — Python + FastAPI + SQLite + async SQLAlchemy + Saga pattern
**Researched:** 2026-10-07
**Stack scope:** Python 3.11+, FastAPI BackgroundTasks, aiosqlite, SQLAlchemy 2.0 async, httpx, pytest-asyncio

---

## Critical Pitfalls

Mistakes that cause data loss, duplicate side effects, or permanent state corruption.

---

### Pitfall 1: Step Executes Twice Due to At-Least-Once Delivery Without Idempotency

**Severity:** CRITICAL

**What goes wrong:**
The executor calls a step's execute URL, the external service processes the request and responds, but the executor crashes before writing the step result to SQLite. On restart, the step appears `PENDING` or `RUNNING` so the executor calls the URL again. The external service processes it a second time — duplicate charge, duplicate record, duplicate email.

**Why it happens:**
There is an unavoidable gap between "the HTTP call succeeded" and "that success is persisted." No single atomic operation spans both. This is the fundamental at-least-once problem in distributed systems.

**Consequences:**
- Double-charges in payment steps
- Duplicate records in downstream systems
- Compensation applied to already-compensated state

**Prevention:**
- Require callers to design their step handlers as idempotent (documented contract in API)
- Pass a stable idempotency key on every step HTTP call: `X-Idempotency-Key: {run_id}-{step_index}-{attempt_number}`
- Record `STEP_STARTED` with the idempotency key to the DB and fsync *before* making the outbound HTTP call, not after
- Record `STEP_COMPLETED` immediately after HTTP 2xx; never batch this write

**Detection / warning signs:**
- External service logs show same `X-Idempotency-Key` called twice for successful runs
- Compensation fired against steps that were already compensated

**Phase / component to address:**
Core execution engine, Phase 1. The "persist intent before acting" pattern must be baked in from the first working implementation — retrofitting it later means rewriting the execution loop.

---

### Pitfall 2: Zombie Workflows Stuck RUNNING After Process Crash

**Severity:** CRITICAL

**What goes wrong:**
A workflow run is in state `RUNNING` and a step is `EXECUTING` when the process crashes. On restart, no code transitions those rows — they stay `RUNNING` forever. Queries show an active workflow, but no worker is driving it. The run never finishes, never compensates, never errors.

**Why it happens:**
FastAPI `BackgroundTasks` run in-process. When the process dies, no cleanup hook runs. The DB rows reflect the last-written state, which is mid-execution. There is no heartbeat or lease mechanism to detect abandonment.

**Consequences:**
- Stuck runs accumulate over time; status API returns stale `RUNNING` states
- Compensation never fires for abandoned runs
- Operators have no automated recovery path

**Prevention:**
- Implement a startup recovery sweep: on application boot, query all rows in state `RUNNING` or `EXECUTING` that have not been updated within a configurable staleness window (e.g., 5 minutes), and transition them to `FAILED` or a dedicated `INTERRUPTED` state
- Write a `last_heartbeat_at` timestamp column on workflow runs; update it periodically during execution
- After transition to `INTERRUPTED`, trigger compensation for any completed steps (they may need rollback)
- Document the recovery sweep as a required startup step, not an optional background job

**Detection / warning signs:**
- Workflow run `updated_at` is old but status is still `RUNNING`
- No corresponding log entries for step execution after a certain timestamp
- Count of `RUNNING` runs grows monotonically after restarts

**Phase / component to address:**
Phase 1 (persistence schema must include `last_heartbeat_at`). Phase 2 (recovery sweep on startup). Add integration test that SIGKILLs mid-run and verifies recovery.

---

### Pitfall 3: SQLite "Database Is Locked" Under Concurrent Async Writes

**Severity:** CRITICAL

**What goes wrong:**
Multiple workflow runs execute concurrently via `BackgroundTasks`. Each has an open async SQLAlchemy session. SQLite allows only one writer at a time. Without WAL mode and a busy timeout, the second writer immediately receives `sqlite3.OperationalError: database is locked` and crashes — silently, if the exception is not propagated from the background task.

**Why it happens:**
Default SQLite journal mode (`DELETE`) blocks all readers and writers when any write is in progress. `aiosqlite` is async at the Python level but still serializes writes through SQLite's single-writer lock. The default busy timeout is effectively 0 on some platforms, causing instant failure instead of brief waiting.

**Consequences:**
- Concurrent workflow runs fail with opaque `OperationalError`
- If the exception is swallowed (see Pitfall 7), the workflow silently stalls
- Under load, almost all concurrent write attempts fail

**Prevention:**
- Enable WAL mode at database initialization: `PRAGMA journal_mode=WAL` (persistent per DB file; set once on first connect)
- Set `PRAGMA busy_timeout=5000` on every connection (connection-scoped, not DB-scoped)
- Set `PRAGMA synchronous=NORMAL` for write performance without durability sacrifice
- Use `check_same_thread=False` in the SQLite connect args when using SQLAlchemy async
- Use SQLAlchemy `NullPool` for file-based SQLite in async contexts to avoid cross-thread connection sharing
- Keep write transactions short — do not hold an open write transaction across an HTTP call

**Detection / warning signs:**
- `OperationalError: database is locked` in logs
- Background tasks completing slowly or inconsistently under load
- Test suite passes with one worker but fails with concurrent test execution

**Phase / component to address:**
Phase 1, database initialization. Add PRAGMAs to the engine creation code and a startup assertion that WAL mode is active.

---

### Pitfall 4: Compensation Fails Silently and Workflow Is Left Partially Compensated

**Severity:** CRITICAL

**What goes wrong:**
Step 3 fails. The executor triggers compensation for steps 2 and 1 in reverse order. The `compensate_url` for step 2 is unreachable (503, timeout, DNS failure). The executor records the failure and moves on — or worse, raises an exception that stops compensation entirely, leaving step 1 un-compensated. The workflow is marked `FAILED` but resources allocated in step 1 are never released.

**Why it happens:**
Teams assume compensation is simpler than forward execution. It is not. Compensation calls cross the same network boundaries with the same failure modes. Stopping the compensation chain on first failure compounds the damage.

**Consequences:**
- "Zombie" resource allocations — reserved inventory, held funds, locked records — that are never released
- Permanent data inconsistency that requires manual operator intervention
- No visibility into which steps were compensated and which were not

**Prevention:**
- Never stop the compensation chain on a single compensation failure; log the failure, record it, continue compensating remaining steps
- Wrap each compensation HTTP call in retry-with-backoff logic (recommended: 3–5 retries, exponential backoff starting at 1s)
- After retry exhaustion, transition that step's compensation state to `COMPENSATION_FAILED` (distinct from `COMPENSATED`)
- Persist each compensation attempt and outcome individually in a `step_compensation_log` table
- Expose a `/runs/{id}/compensation-status` endpoint so operators can see partial compensation state
- Emit a structured alert/log when any compensation exhausts retries — treat this as an ops incident, not a routine error

**Detection / warning signs:**
- Runs in `COMPENSATING` state that never reach `COMPENSATED` or `FAILED`
- Steps with `COMPENSATION_FAILED` in the step log
- External systems show resources still allocated after a run is marked failed

**Phase / component to address:**
Phase 2 (compensation loop). Compensation logic must be retry-aware and continuation-safe from the start. Do not implement compensation as a simple reverse loop without failure handling.

---

## High Pitfalls

Mistakes that cause data loss or correctness bugs that are hard to diagnose.

---

### Pitfall 5: LIFO Compensation Order Not Strictly Enforced

**Severity:** HIGH

**What goes wrong:**
Compensation runs steps in insertion order, alphabetical order, or whatever the query returns — not in strict reverse-completion order. A refund fires before inventory is released. An email cancellation fires before the order record is marked cancelled. The partial window between out-of-order compensations violates business invariants.

**Why it happens:**
The natural implementation — "iterate over completed steps and call their compensate URL" — uses the step definition order (ascending) rather than completion order (descending). Subtle if steps complete out of definition order, which is possible under retry or step-skipping scenarios.

**Prevention:**
- Store `completed_at` on each step execution record
- Build the compensation sequence by sorting on `completed_at DESC` at compensation time, not on step index
- Add a unit test that verifies compensation URL call order when steps complete out of definition sequence

**Detection / warning signs:**
- Business invariant violations during failure scenarios (e.g., order cancelled before refund issued)
- Integration tests with mocked step handlers only pass for happy-path ordering

**Phase / component to address:**
Phase 2, compensation sequencer. Sort by `completed_at` DESC when building the compensation call list.

---

### Pitfall 6: Non-Idempotent Compensation Causes Double-Refund or Double-Release

**Severity:** HIGH

**What goes wrong:**
Compensation for a step is triggered, the compensate URL is called, but the HTTP response is lost (timeout, network error). The executor retries. The external service receives the compensation call twice and issues two refunds, releases inventory twice, or sends two cancellation emails.

**Why it happens:**
Same at-least-once problem as forward execution, but teams focus idempotency design only on the forward path. Compensation is assumed to be inherently safe to repeat.

**Prevention:**
- Pass a stable `X-Idempotency-Key` on compensation calls too: `{run_id}-compensate-{step_index}`
- Document that compensate URL handlers must be idempotent as part of the workflow definition API contract
- Record `COMPENSATION_STARTED` with the key before calling the URL

**Detection / warning signs:**
- External service shows double-refunds correlated with network timeout events
- Compensation succeeds but downstream state is doubly-affected

**Phase / component to address:**
Phase 2, same compensation loop as Pitfall 5. Compensation idempotency keys are a first-class concern, not an afterthought.

---

### Pitfall 7: BackgroundTasks Exceptions Are Silently Swallowed

**Severity:** HIGH

**What goes wrong:**
A workflow execution task raises an unhandled exception — database error, HTTP connection error, unexpected `None`. FastAPI has already sent the HTTP response (202 Accepted). The exception has no response to attach to, so it is logged by asyncio's event loop exception handler (if configured) or silently dropped. The workflow run stays in `RUNNING` state. No error is surfaced. No compensation fires.

**Why it happens:**
FastAPI `BackgroundTasks` run after the HTTP response is committed. Python's asyncio exception propagation for fire-and-forget tasks does not surface to any middleware or exception handler registered on the FastAPI app. This is a documented FastAPI behavior, not a bug.

**Consequences:**
- Silent `RUNNING` zombies (overlaps with Pitfall 2)
- No structured error log for ops to investigate
- Compensation never triggered for failed runs

**Prevention:**
- Wrap the entire background task body in a `try/except Exception` block
- On any unhandled exception: update the run state to `FAILED`, log with `exc_info=True` and structured fields (`run_id`, `step_index`, `error_type`), trigger compensation for completed steps
- Never let the top-level task function exit without writing a terminal state to the DB
- Add an asyncio exception handler at app startup via `loop.set_exception_handler()` as a last-resort catch

**Detection / warning signs:**
- Workflow runs stuck in `RUNNING` with no corresponding step execution log entries
- Exception traces appearing in asyncio exception handler but not in application logs
- HTTP 202 responses that never produce a terminal run state

**Phase / component to address:**
Phase 1, background task wrapper. Every execution function must have this wrapper before the first integration test is written.

---

### Pitfall 8: HTTP Step Calls Without a Hard Total Deadline

**Severity:** HIGH

**What goes wrong:**
An HTTP step call is made with `httpx` using only a `read` timeout. The external service responds slowly — one byte per second — never triggering the read timeout (which measures inactivity between bytes, not total duration). The step holds an open DB connection, a running background task slot, and an asyncio task indefinitely. Under load, all task slots fill with stuck HTTP calls.

**Why it happens:**
`read` timeout and total timeout are distinct. A slow drip of bytes from the server resets the read timeout continuously. Without `asyncio.timeout()` as a hard outer deadline, no per-phase timeout provides a true cap.

**Consequences:**
- Resource exhaustion from accumulated hanging tasks
- SQLite write lock held by a hanging step, blocking all other concurrent runs
- No clean error state written to DB — overlaps with zombie run problem

**Prevention:**
- Use `httpx.AsyncClient` with explicit per-phase timeouts: `httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)`
- Wrap every HTTP step call in `asyncio.timeout(total_seconds)` (Python 3.11+) as a hard outer deadline
- Treat `asyncio.TimeoutError` and `httpx.TimeoutException` as step failures, not unexpected exceptions — write `FAILED` state to DB and trigger compensation
- Expose configurable per-step timeout in the workflow definition (default 30s is a reasonable starting point)

**Detection / warning signs:**
- Step `started_at` is old but `completed_at` is null with no `failed_at`
- HTTP traces show open connections accumulating
- External service logs show requests completing successfully while the executor never records the result

**Phase / component to address:**
Phase 1, HTTP step executor. Never make an HTTP call to an external step URL without both `httpx.Timeout` and `asyncio.timeout` wrapping it.

---

### Pitfall 9: Test Isolation Failure — Async Tests Share DB State Across Runs

**Severity:** HIGH

**What goes wrong:**
Tests use a shared file-based or `:memory:` SQLite database. Test A creates a workflow run. Test B queries "all runs" and sees Test A's data. Tests pass in isolation but fail in suite order. Parallel test execution (`pytest-xdist`) causes race conditions and `database is locked` errors. Flaky test results that change between runs.

**Why it happens:**
SQLite `:memory:` databases create a new database instance per connection — so if SQLAlchemy's connection pool opens multiple connections, tests see different empty databases. File-based SQLite shares state across tests if teardown is incomplete. Async session lifecycle mismatches (fixture scope vs. event loop scope) cause `RuntimeError: got Future attached to a different loop`.

**Prevention:**
- Use a per-test temporary file-based SQLite DB (via `tmp_path` fixture), not `:memory:` — avoids the per-connection isolation problem of in-memory DBs with connection pools
- Use `NullPool` on the test engine to prevent connection reuse across tests
- Always drop and recreate tables in test teardown, or use transactional rollback via nested savepoints
- Match event loop scope to fixture scope: session-scoped async fixtures need `scope="session"` on the event loop fixture
- Use `pytest-asyncio` with `asyncio_mode = "auto"` in `pytest.ini` to avoid silent test-skipping of `async def` test functions

**Detection / warning signs:**
- Tests pass individually but fail when run together
- `RuntimeError: got Future attached to a different loop`
- Test results change based on alphabetical ordering of test file names
- `async def test_*` functions with no `@pytest.mark.asyncio` that appear to pass without executing assertions

**Phase / component to address:**
Phase 1, test infrastructure setup (`conftest.py`). Correct test isolation is a prerequisite for all subsequent test phases — do not defer.

---

## Moderate Pitfalls

Mistakes that cause reliability or correctness issues that are diagnosable but require rework.

---

### Pitfall 10: SQLAlchemy `pool_size` Default Creates Multiple Connections to SQLite

**Severity:** MEDIUM

**What goes wrong:**
SQLAlchemy's default pool creates multiple connections. SQLite with a connection pool means multiple writers contend for the same file lock. `check_same_thread=False` is required but insufficient alone. The pool may return a connection from a different thread than the one that created it.

**Prevention:**
- For file-based SQLite in async FastAPI: use `NullPool` (each operation gets a fresh connection, closes it immediately — no pooling)
- If pooling is desired for performance, set `pool_size=1` and `max_overflow=0` to serialize all writes through a single connection
- Always pass `connect_args={"check_same_thread": False}` in SQLAlchemy `create_async_engine`

**Phase / component to address:**
Phase 1, engine initialization.

---

### Pitfall 11: Compensation Triggered Without Verifying Step Actually Completed

**Severity:** MEDIUM

**What goes wrong:**
A step's execute URL was called but the response was lost — the executor marks the step `FAILED` (correct), but compensation is triggered and calls the compensate URL, even though the external service never processed the original request. The compensate URL receives a request to undo work that was never done. If the compensate URL is not designed for this, it returns an error, which the executor misinterprets as a compensation failure.

**Why it happens:**
The compensation trigger logic checks `step.status == FAILED` but does not distinguish "failed to execute" from "executed but response lost." Both look identical from the executor's perspective.

**Prevention:**
- Document in the step API contract that compensate URLs must handle the case where no forward execution occurred (idempotent no-op on absent work)
- Consider recording a `CONFIRMED` sub-state for steps where HTTP 2xx was received and persisted before any retry attempt
- Compensation should be safe to call even if the forward step never actually modified state

**Phase / component to address:**
Phase 2, compensation trigger logic and API contract documentation.

---

### Pitfall 12: WAL Mode Not Enabled for Test Databases

**Severity:** MEDIUM

**What goes wrong:**
Production code enables WAL mode. Test databases are created fresh for each test, and WAL mode is never set. Concurrency bugs that WAL mode masks (or exacerbates) go undetected in tests. In rare cases, tests pass because they use a single-connection `StaticPool` or `NullPool` that avoids the contention, while production uses pooled connections.

**Prevention:**
- Apply the same PRAGMA initialization (`journal_mode=WAL`, `busy_timeout=5000`) in test fixture DB setup as in production engine initialization
- Extract engine initialization into a shared factory function used by both production and test code

**Phase / component to address:**
Phase 1, test infrastructure and engine factory.

---

### Pitfall 13: Workflow Definition Mutation Breaks In-Progress Runs

**Severity:** MEDIUM

**What goes wrong:**
A workflow definition is updated (step URLs changed, steps reordered) while runs using the previous version are still in-progress. The running executor loads the current definition and calls the new step URL for a step that was half-executed against the old URL. Or a compensation call goes to the new compensate URL, not the one that was called during forward execution.

**Prevention:**
- Snapshot the workflow definition into the run record at the time of run creation (store JSON of the step sequence used)
- Compensation and retry must always use the snapshotted definition, not the current live definition
- Consider versioning workflow definitions explicitly (v1, v2) and rejecting updates to definitions with active runs

**Phase / component to address:**
Phase 1, run creation logic. Snapshot at run creation time; enforce this in the data model.

---

## Minor Pitfalls

---

### Pitfall 14: `expire_on_commit=True` Causes Lazy Load Errors After Session Commit

**Severity:** LOW

**What goes wrong:**
After committing an `AsyncSession`, SQLAlchemy marks all loaded objects as expired. Accessing an attribute on a committed model object outside a session context triggers a lazy load, which fails in async context with `MissingGreenlet` or `DetachedInstanceError`.

**Prevention:**
- Set `expire_on_commit=False` on `async_sessionmaker`
- Return Pydantic schemas from service functions, not ORM objects, so session lifecycle is never a concern at the API layer

**Phase / component to address:**
Phase 1, session factory configuration.

---

### Pitfall 15: `asyncio.create_task` Without Storing the Reference

**Severity:** LOW

**What goes wrong:**
Background tasks spawned with `asyncio.create_task(...)` without storing the returned `Task` object are garbage-collected immediately. The task is cancelled before it runs. This is an asyncio bug, not a FastAPI bug — Python's garbage collector can collect the task while the event loop still holds it weakly.

**Prevention:**
- Always store task references in a set or list at the module or app level: `_background_tasks: set[asyncio.Task] = set()`
- Add a `task.add_done_callback(_background_tasks.discard)` to clean up completed tasks
- Prefer `BackgroundTasks` over `asyncio.create_task` for FastAPI-managed background work; BackgroundTasks holds the reference internally

**Phase / component to address:**
Phase 1, any code that uses `asyncio.create_task` for workflow execution.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| DB schema design | Missing `last_heartbeat_at`, `completed_at`, `compensation_status` columns | Design schema with all state columns up front; migrations are more painful than planning |
| Execution loop | No "persist intent before act" discipline | Write `STEP_STARTED` + idempotency key to DB before every outbound HTTP call |
| HTTP step executor | Missing hard deadline on outbound calls | Wrap with both `httpx.Timeout` and `asyncio.timeout` |
| Compensation loop | Stopping on first compensation failure | Use continue-on-failure compensation with per-step retry |
| Startup recovery | No zombie detection on boot | Recovery sweep must run at startup, not on demand |
| Test setup | `async def` tests that never execute | Enable `asyncio_mode = "auto"` and verify at least one assertion fires |
| Concurrent runs | SQLite lock contention | WAL mode + `busy_timeout` set before accepting any requests |
| Definition updates | Active run uses updated step URLs | Snapshot definition at run creation |

---

## Sources

- [SQLite WAL mode concurrent writes — The Write Stuff blog](https://oldmoe.blog/2024/07/08/the-write-stuff-concurrent-write-transactions-in-sqlite/)
- [aiosqlite PyPI — async bridge details](https://pypi.org/project/aiosqlite/)
- [SQLite "database is locked" — WAL mode fix guide](https://dbapark.com/sqlite-database-is-locked-wal-fix/)
- [FastAPI async database patterns](https://oneuptime.com/blog/post/2026-02-02-fastapi-async-database/view)
- [Fix AsyncSession errors in FastAPI — SQLAlchemy 2.0](https://dev.to/ayush_kumar_085a0f2c54e3f/fix-asyncsession-errors-in-fastapi-sqlalchemy-20-guide-52i6)
- [FastAPI BackgroundTask exception not caught](https://theneuralbase.com/fastapi/errors/fastapi-background-task-exception-not-caught/)
- [Understanding pitfalls of async task management in FastAPI](https://leapcell.io/blog/understanding-pitfalls-of-async-task-management-in-fastapi-requests)
- [Saga rollback mechanics — compensation ordering and partial execution trap](https://dev.to/neeraj_singhi_golang/saga-rollback-mechanics-compensating-transaction-ordering-failure-atomicity-and-the-partial-4142)
- [The Saga Pattern Trap — handling compensation failures](https://coldfusion-example.blogspot.com/2026/01/the-saga-pattern-trap-handling.html)
- [Saga dead letter handling — recover stuck workflows](https://adhdecode.com/articles/saga-pattern/saga-dead-letter-handling/)
- [Mastering Saga patterns — Temporal blog](https://temporal.io/blog/mastering-saga-patterns-for-distributed-transactions-in-microservices)
- [Durable execution idempotency — at-least-once vs exactly-once](https://opulion.dev/ground-truth/durable-execution-idempotency-or-both)
- [AWS durable execution idempotency best practices](https://docs.aws.amazon.com/durable-execution/patterns/best-practices/idempotency/)
- [HTTP request hangs forever — where timeouts live in Python](https://dev.to/libme/http-request-hangs-forever-in-production-where-timeouts-actually-live-in-node-python-and-go-28ph)
- [aiohttp total/read timeout not respected — GitHub issue](https://github.com/aio-libs/aiohttp/issues/9547)
- [httpx async requests guide](https://oneuptime.com/blog/post/2026-02-03-python-httpx-async-requests/view)
- [Dapr workflow stuck in running state](https://oneuptime.com/blog/post/2026-03-31-dapr-workflow-stuck-running-state/view)
- [Deterministic crash-tolerant saga orchestrator — GitHub](https://github.com/Zion-01/saga-orchestrator)
- [Transactional unit tests with pytest and async SQLAlchemy](https://www.core27.co/post/transactional-unit-tests-with-pytest-and-async-sqlalchemy)
- [Pytest async SQLAlchemy — flaky sessions guide](https://medium.com/@babaian2001dan/pytest-async-sqlalchemy-how-to-test-async-db-code-without-flaky-sessions-af3f77661f93)
- [Async testing with pytest-asyncio — event loops](https://medium.com/@connect.hashblock/async-testing-with-pytest-mastering-pytest-asyncio-and-event-loops-for-fastapi-and-beyond-37c613f1cfa3)
