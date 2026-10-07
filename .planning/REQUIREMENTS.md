# Requirements — Multi-Step Workflow Executor

## v1 Requirements

### Workflow Definitions

- [x] **DEFN-01**: User can register a named workflow definition with an ordered list of steps, where each step specifies `name`, `execute_url`, optional `compensate_url`, optional `timeout_seconds`, and optional `retry_policy` (schema only; enforcement deferred to v2)
- [x] **DEFN-02**: User can retrieve a single workflow definition by name and list all registered definitions
- [x] **DEFN-03**: User can delete a workflow definition by name; deletion is rejected if any active (non-terminal) runs exist for that workflow

### Execution

- [ ] **EXEC-01**: User can start a workflow run by name, optionally passing an input payload; the executor calls each step's `execute_url` via HTTP POST in order, passing the input payload; run ID is returned immediately
- [ ] **EXEC-02**: User can query a workflow run by ID and receive: current status, current step index, input payload, started_at, completed_at, and error detail on failure
- [ ] **EXEC-03**: User can retrieve step-level execution history for a run, including per-step: status, started_at, completed_at, HTTP response code, error detail, compensation status, compensated_at, and compensation_error

### Compensation (Saga Pattern)

- [ ] **COMP-01**: When any step fails (non-2xx response or timeout), the executor automatically calls each previously-completed step's `compensate_url` in reverse order (LIFO); steps with no `compensate_url` are silently skipped; compensation continues even if individual compensate calls fail
- [ ] **COMP-02**: Per-step compensation outcome is recorded in history: `compensated_at` on success, `compensation_error` on failure; final run status reflects whether compensation fully succeeded

### Resilience

- [ ] **RESIL-01**: Workflow run state is durably persisted to SQLite; process restarts do not lose run history; previously-completed runs are queryable after restart
- [ ] **RESIL-02**: Each step call enforces a configurable timeout (`timeout_seconds` from step definition, with a service-level default); steps that exceed the timeout fail with a timeout error and trigger compensation
- [ ] **RESIL-03**: Step definition includes a `retry_policy` schema (`max_attempts`, `backoff_seconds`, `max_delay_seconds`); schema is stored and returned in API responses (enforcement of multi-attempt retry logic is deferred to v2)
- [x] **RESIL-04**: Multiple workflow runs execute concurrently without state corruption; concurrent writes are serialized via `asyncio.Lock` + SQLite WAL mode + optimistic locking (`version` column) to prevent lost updates

### Platform

- [x] **PLAT-01**: All API endpoints require `X-API-Key` header authentication; requests without a valid key receive 401; key configured via environment variable
- [x] **PLAT-02**: Service emits structured JSON logs (via structlog) including `run_id`, `step_name`, and `correlation_id` on all workflow execution log lines
- [x] **PLAT-03**: `GET /health` returns service status, SQLite reachability, and service version; returns 200 on healthy, 503 on DB unreachable
- [ ] **PLAT-04**: Service ships with a single-worker Dockerfile and docker-compose.yml for local development; SQLite data persisted via named Docker volume

## v2 Requirements (Deferred)

- Step retry enforcement — actually honor `max_attempts` and backoff from `retry_policy` (RESIL-03 schema is defined in v1)
- Startup recovery sweep — on boot, detect zombie `RUNNING` rows (process crashed mid-execution) and drive them to a terminal state or re-queue
- List and filter workflow runs — `GET /runs?status=FAILED&workflow=foo` with pagination
- Cancel endpoint — `POST /runs/{run_id}/cancel` to manually abort a running workflow and trigger compensation
- Manual compensation trigger — `POST /runs/{run_id}/compensate` to initiate rollback on a FAILED run
- Update workflow definition — `PUT /workflows/{name}` replace step list (blocked on run migration strategy)
- `COMPENSATING` / `COMPENSATED` as distinct run status values (v1 uses `FAILED` + per-step compensation fields)
- Idempotency key on execute endpoint — `POST /workflows/{name}/runs` with `X-Idempotency-Key` header

## Out of Scope

- Scheduled / cron-triggered workflows — demand-triggered execution only
- Multi-tenant / org isolation — single-tenant API key is sufficient for scope
- Distributed broker (Celery + Redis) — architecture is designed to be extensible, but won't be implemented
- UI dashboard — REST API + OpenAPI docs is the interface
- Workflow versioning — no semantic version on definitions
- Step output chaining — each step receives the original run input, not previous step output

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEFN-01 | Phase 1 | Complete |
| DEFN-02 | Phase 1 | Complete |
| DEFN-03 | Phase 1 | Complete |
| EXEC-01 | Phase 2 | Pending |
| EXEC-02 | Phase 2 | Pending |
| EXEC-03 | Phase 2 | Pending |
| COMP-01 | Phase 3 | Pending |
| COMP-02 | Phase 3 | Pending |
| RESIL-01 | Phase 2 | Pending |
| RESIL-02 | Phase 2 | Pending |
| RESIL-03 | Phase 2 | Pending |
| RESIL-04 | Phase 1 | Complete |
| PLAT-01 | Phase 1 | Complete |
| PLAT-02 | Phase 1 | Complete |
| PLAT-03 | Phase 1 | Complete |
| PLAT-04 | Phase 4 | Pending |
