# Roadmap — Multi-Step Workflow Executor

## Project

**Core value:** Reliable, durable workflow execution with automatic compensation — workflows survive restarts, concurrent executions don't collide, and failures are never silent.

**Milestone:** v1 MVP

**Granularity:** Standard (5–8 phases)

**Coverage:** 16/16 v1 requirements mapped

---

## Phases

- [ ] **Phase 1: Foundation & Persistence** - Async DB engine, WAL config, workflow definition CRUD, auth, health, structlog, test harness
- [ ] **Phase 2: Execution Engine** - Happy-path run execution, per-step HTTP dispatch, run/step query endpoints, timeouts, retry schema
- [ ] **Phase 3: Saga Compensation** - CompensationCoordinator, LIFO reverse-order compensation, continue-on-failure, per-step compensation recording
- [ ] **Phase 4: Containerization & Integration Tests** - Dockerfile, docker-compose with named volume, end-to-end integration test suite

---

## Phase Details

### Phase 1: Foundation & Persistence
**Goal**: Clients can register and query workflow definitions; the service is authenticated, observable, and backed by a correctly-configured async SQLite engine that is safe for concurrent writes.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: DEFN-01, DEFN-02, DEFN-03, RESIL-01, RESIL-04, PLAT-01, PLAT-02, PLAT-03
**Success Criteria** (what must be TRUE):
  1. `POST /workflows` with a valid API key and a JSON body of named steps (each with `execute_url`, optional `compensate_url`, `timeout_seconds`, and `retry_policy` schema) returns 201 and the stored definition.
  2. `GET /workflows/{name}` returns the definition and `GET /workflows` lists all registered definitions; both require a valid API key and return 401 without one.
  3. `DELETE /workflows/{name}` returns 204 when no active runs exist for that workflow, and 409 when active runs are present.
  4. `GET /health` returns 200 with SQLite reachability status when the DB is up, and 503 when the DB is unreachable.
  5. After a process restart, all previously-registered definitions are queryable without data loss; structured JSON log lines for each request include a `correlation_id` field.
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Wave 1 (RED): pyproject.toml + test harness stubs (all 5 test files, conftest.py)
- [x] 01-02-PLAN.md — Wave 2 (GREEN): Core infrastructure scaffold (engine, auth, logging, health, Docker)
- [x] 01-03-PLAN.md — Wave 3 (GREEN+REFACTOR): Workflow CRUD (models, schemas, repository, router)

### Phase 2: Execution Engine
**Goal**: Clients can start a workflow run and immediately receive a run ID; the executor drives each step's HTTP call in order, persists every state transition before dispatch, and exposes run status and step history via query endpoints.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: EXEC-01, EXEC-02, EXEC-03, RESIL-01, RESIL-02, RESIL-03
**Success Criteria** (what must be TRUE):
  1. `POST /workflows/{name}/runs` returns 202 with a `run_id` immediately; the run transitions from `PENDING` to `RUNNING` to `COMPLETED` in the background when all steps respond 2xx.
  2. `GET /runs/{run_id}` returns current status, current step index, input payload, `started_at`, `completed_at`, and error detail; a query issued before the background task finishes reflects the live intermediate state.
  3. `GET /runs/{run_id}/steps` returns an append-only history entry for each step including `status`, `started_at`, `completed_at`, HTTP response code, and `error_detail`.
  4. A step whose HTTP call exceeds `timeout_seconds` (or the service-level default) fails with a timeout error visible in the step history; the run transitions to a terminal failure state.
  5. After a process restart, all completed runs and their full step histories remain queryable without data loss.
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md — Wave 1 (RED): respx dev dep + test_runs.py stubs
- [x] 02-02-PLAN.md — Wave 2 (GREEN): WorkflowRun+StepExecution models, executor, router, wiring

### Phase 3: Saga Compensation
**Goal**: When any step fails, the executor automatically compensates all previously-completed steps in strict reverse-completion order; compensation continues even if individual compensate calls fail; all outcomes are recorded per-step.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: COMP-01, COMP-02
**Success Criteria** (what must be TRUE):
  1. When a step returns a non-2xx response, `GET /runs/{run_id}/steps` shows each previously-completed step's `compensate_url` was called in reverse-completion order (LIFO by `completed_at`); steps with no `compensate_url` are skipped silently.
  2. A compensation HTTP call that returns 5xx or times out does not stop compensation for the remaining steps; all steps in the compensation chain are attempted regardless of individual failures.
  3. After full compensation, `GET /runs/{run_id}/steps` records `compensated_at` for each successfully-compensated step and `compensation_error` for any step whose compensation call failed.
  4. `GET /runs/{run_id}` reflects the final run status: `COMPENSATED` when all compensations succeeded and `COMPENSATION_FAILED` when one or more compensation calls failed.
**Plans**: TBD

### Phase 4: Containerization & Integration Tests
**Goal**: The service ships as a single-worker Docker image with durable SQLite storage; an end-to-end integration test suite validates the full register-execute-compensate workflow against a real SQLite file.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: PLAT-04
**Success Criteria** (what must be TRUE):
  1. `docker-compose up` starts the service; `GET /health` returns 200; the `--workers 1` constraint is enforced in the Dockerfile CMD (not overridable by compose without explicit edit).
  2. SQLite data written in one `docker-compose up` session is readable after `docker-compose down && docker-compose up`; data lives in a named Docker volume, not a bind mount.
  3. The integration test suite executes a full register → execute → compensate flow against a real SQLite temp file and passes without network calls to external services; `pytest` exits 0.
**Plans**: TBD

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Persistence | 2/3 | In Progress|  |
| 2. Execution Engine | 0/? | Not started | - |
| 3. Saga Compensation | 1/1 | Complete   | 2026-10-07 |
| 4. Containerization & Integration Tests | 0/? | Not started | - |

---

## Coverage Map

| Requirement | Phase |
|-------------|-------|
| DEFN-01 | Phase 1 |
| DEFN-02 | Phase 1 |
| DEFN-03 | Phase 1 |
| EXEC-01 | Phase 2 |
| EXEC-02 | Phase 2 |
| EXEC-03 | Phase 2 |
| COMP-01 | Phase 3 |
| COMP-02 | Phase 3 |
| RESIL-01 | Phase 2 |
| RESIL-02 | Phase 2 |
| RESIL-03 | Phase 2 |
| RESIL-04 | Phase 1 |
| PLAT-01 | Phase 1 |
| PLAT-02 | Phase 1 |
| PLAT-03 | Phase 1 |
| PLAT-04 | Phase 4 |

Total mapped: 16/16 ✓

---
*Created: 2026-10-07*
*Updated: 2026-10-07 — Phase 1 planned (3 plans, 3 waves)*
