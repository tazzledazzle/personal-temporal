# Feature Landscape: Durable Workflow Executor

**Domain:** Workflow orchestration engine with Saga pattern compensation
**Researched:** 2026-10-07
**Confidence:** HIGH (grounded in Temporal, AWS Step Functions, Netflix Conductor OSS, and production Saga pattern literature)

---

## REST API Endpoint Surface

### Standard endpoint groups seen across Temporal, Conductor, n8n, AWS Step Functions

| Group | Endpoints | Purpose |
|-------|-----------|---------|
| Definitions | `POST /workflows`, `GET /workflows`, `GET /workflows/{name}`, `DELETE /workflows/{name}` | Register, inspect, delete workflow blueprints |
| Executions | `POST /workflows/{name}/execute`, `GET /executions/{run_id}`, `GET /executions`, `DELETE /executions/{run_id}` | Start and track runs |
| Control | `POST /executions/{run_id}/cancel`, `POST /executions/{run_id}/retry` | User-driven lifecycle transitions |
| History | `GET /executions/{run_id}/steps` | Per-step execution log |
| Health | `GET /health`, `GET /health/ready` | Infrastructure readiness probes |

---

## Table Stakes

Features that any workflow engine must have. Missing = product is not a workflow engine.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Register workflow definition | Blueprint storage is the foundation; nothing else works without it | Low | Name + ordered steps + compensate URLs; versioning is advanced |
| Execute workflow by name | Core user action — triggers a run | Low–Med | Creates a run record, kicks off async execution |
| Per-run durable state | Engine must survive restarts (crash-recovery is the whole point) | Med | Persist status + current step + timestamps after every transition |
| Standard execution states | Users need a stable vocabulary to drive automation against | Low | `PENDING → RUNNING → COMPLETED / FAILED`; plus `COMPENSATING` and `COMPENSATED` for Saga engines |
| Step execution states | Fine-grained observability per step, not just the whole run | Low | `PENDING / RUNNING / COMPLETED / FAILED`; store `started_at`, `completed_at`, `error` |
| Query run status | Clients poll or display state — must be fast and reliable | Low | `GET /executions/{run_id}` returns status, current step, timestamps |
| Query step history | Debugging requires knowing exactly what each step did | Low | `GET /executions/{run_id}/steps`; ordered list of step records |
| Saga compensation (reverse-order) | This engine's core promise — automatic rollback on failure | Med–High | On any step failure, call compensate URLs in reverse for all completed steps |
| API key authentication | All endpoints must be access-controlled | Low | `X-API-Key` header; return 401 on missing/invalid key |
| Health endpoint | Required for Docker, k8s, load balancers, and CI smoke tests | Low | `GET /health` → `{"status": "ok"}` |
| Structured JSON logging | Without structured logs, debugging distributed failures is impossible | Low | Each log line carries `run_id`, `step_name`, `event`, `timestamp`; use `structlog` or similar |
| HTTP timeout per step | Steps that never respond must not block the engine forever | Med | Each step call has a configurable deadline; timeout counts as failure and triggers compensation |
| Concurrent execution safety | Multiple runs of the same workflow must not corrupt each other | Med | SQLAlchemy row-level locking or optimistic concurrency on run state transitions |

---

## Execution States (Standard Vocabulary)

Drawn from Temporal, AWS Step Functions, Conductor OSS, and Saga literature.

### Workflow Run States

| State | Type | Meaning |
|-------|------|---------|
| `PENDING` | Non-terminal | Accepted; waiting to start (e.g., BackgroundTask not yet scheduled) |
| `RUNNING` | Non-terminal | Steps are actively executing |
| `COMPENSATING` | Non-terminal | A step failed; compensations are running in reverse |
| `COMPLETED` | Terminal | All steps finished successfully |
| `COMPENSATED` | Terminal | All completed steps were successfully compensated |
| `FAILED` | Terminal | Step failed AND compensation itself failed or was not attempted |
| `CANCELLED` | Terminal | Operator cancelled the run before completion |

### Step States

| State | Meaning |
|-------|---------|
| `PENDING` | Waiting for prior step to complete |
| `RUNNING` | HTTP call in flight |
| `COMPLETED` | Got 2xx response |
| `FAILED` | Non-retryable failure or retries exhausted |
| `SKIPPED` | Never reached (only assigned retrospectively for clarity) |
| `COMPENSATED` | Compensate URL was called successfully |
| `COMPENSATION_FAILED` | Compensate URL call failed |

---

## Workflow Definition Schema (Standard Fields)

What users expect to POST when registering a workflow.

### Workflow Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for the workflow; used to start runs |
| `description` | string | No | Human-readable purpose |
| `steps` | array[Step] | Yes | Ordered list of steps |
| `timeout_seconds` | integer | No | Wall-clock deadline for the entire run; default: no timeout |
| `created_at` | datetime | Auto | Server-assigned |

### Step Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique within the workflow; used in history |
| `execute_url` | string (URL) | Yes | HTTP endpoint the engine calls to perform this step |
| `compensate_url` | string (URL) | No | HTTP endpoint to call during compensation; if absent, step is skipped during rollback |
| `timeout_seconds` | integer | No | Per-step timeout; overrides workflow-level timeout |
| `retry` | RetryPolicy | No | Retry configuration for transient failures |
| `method` | string | No | HTTP method for execute_url call; default `POST` |

### RetryPolicy Object

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_attempts` | integer | 1 (no retry) | Total attempt count including first try |
| `backoff` | string | `exponential` | Strategy: `constant`, `linear`, `exponential` |
| `initial_delay_seconds` | float | 1.0 | Wait before first retry |
| `max_delay_seconds` | float | 60.0 | Cap on backoff growth |
| `jitter` | boolean | true | Add ±50% jitter to prevent thundering herd |

---

## Differentiators

Features that set this engine apart from a basic task runner. Not expected but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| `COMPENSATING` / `COMPENSATED` states (distinct from FAILED) | Most basic engines just go to FAILED; explicit compensation states let clients distinguish "rollback succeeded" from "rollback also failed" | Low | State machine discipline; few simple engines bother |
| Per-step compensation status in history | Knowing which compensations ran and which failed is critical for manual recovery | Low | Add `compensated_at`, `compensation_error` to step records |
| `POST /executions/{run_id}/retry` (re-arm failed run) | Failed runs can be retried from the start without re-registering; important for transient infrastructure failures | Med | Reset run to PENDING, clear step states, re-enqueue |
| `POST /executions/{run_id}/cancel` | Operator can abort a running workflow; triggers compensation for already-completed steps | Med | Treat as a synthetic step failure at current position |
| Idempotent execute endpoint | Calling `POST /workflows/{name}/execute` twice with the same `idempotency_key` returns the existing run, not a duplicate | Med | Header-based: `Idempotency-Key: <uuid>`; store key → run_id mapping |
| Run input payload forwarded to steps | Steps receive the original execution input as context; enables parameterized workflows | Low | Store `input` JSON on run record; include in step HTTP body |
| List executions with status filter | `GET /executions?status=FAILED&workflow=order_saga` for dashboards and alerting | Low | Standard SQL WHERE clause; return paginated results |
| `correlation_id` on runs | Clients pass their own reference ID to tie workflow runs to their system's objects (e.g., order ID) | Low | Indexed, filterable field on run record |
| OpenAPI / Swagger UI auto-generated | FastAPI does this for free; interviewers can immediately explore the API without a Postman collection | Free (FastAPI) | Ensure all Pydantic models are well-annotated |

---

## Anti-Features

Features to deliberately exclude from this MVP.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Scheduling / cron triggers | Adds a separate scheduler subsystem; out of scope per PROJECT.md | Accept on-demand POSTs only |
| UI dashboard | Doubles the project scope; REST API is sufficient for interview evaluation | Auto-generated Swagger UI from FastAPI covers interactive exploration |
| Multi-tenant / org isolation | Requires schema-per-tenant or row-level tenant columns throughout | Single API key is sufficient for showcase |
| Workflow versioning (v1, v2) | Conductor supports it but it adds migration and routing complexity; not needed for MVP | Use PUT to overwrite definition; note limitation |
| Parallel step execution (fan-out) | DAG orchestration requires dependency tracking; pure sequential is the interview scope | Document sequential-only limitation; note extension path |
| Step-to-step data passing (wiring) | Conductor's `${step_ref.output.field}` expression language is non-trivial; not needed | Document that steps receive the original run input; full wiring is an extension |
| Webhooks / outbound event push | Engine-to-client push requires a reliable delivery subsystem (dead-letter, retries) | Steps can use the run status API to poll; noted as future work |
| Distributed broker (Celery/RabbitMQ) | Adds infra; asyncio BackgroundTasks are sufficient for single-process demo | Architecture explicitly leaves room for it per PROJECT.md |
| Dead-letter queue for compensations | Production concern; adds a separate storage/monitoring surface | Log compensation failures clearly; FAILED state captures permanent failure |
| Circuit breakers per step target | Valuable in production but adds a per-host state machine | Not implemented; document as known gap |
| Pause / resume workflow | Useful operator control but not required for saga showcase | Cancel is sufficient; pause adds "waiting" state complexity |

---

## Feature Dependencies

```
API key auth
  └── all endpoints (nothing is public)

Workflow definition storage
  └── execute workflow
        └── durable run state (PENDING → RUNNING)
              ├── per-step HTTP execution
              │     ├── step retry logic
              │     │     └── per-step timeout
              │     └── step state transitions
              │           └── step history endpoint
              ├── saga compensation trigger (on any step FAILED)
              │     ├── compensate URLs (reverse order)
              │     │     └── per-step compensation status
              │     └── COMPENSATING → COMPENSATED / FAILED state
              ├── query run status endpoint
              └── list executions endpoint
                    └── status filter

Health endpoint (independent)
Structured logging (cross-cutting; not blocked by any feature)
Concurrent execution safety (cross-cutting; must be present before multi-run testing)
```

---

## MVP Recommendation

### Must ship (table stakes for a durable workflow engine)

1. Register and retrieve workflow definitions (POST + GET /workflows)
2. Execute a workflow (POST /workflows/{name}/execute) with durable PENDING → RUNNING → COMPLETED/FAILED state
3. Saga compensation: on step failure, call compensate URLs in reverse for all completed steps
4. Query run status (GET /executions/{run_id}) and step history (GET /executions/{run_id}/steps)
5. Per-step HTTP timeout (prevent hung engine)
6. API key auth on all endpoints
7. Health endpoint
8. Structured JSON logging with run_id correlation

### Include for differentiation (low complexity, high interview signal)

9. Explicit COMPENSATING and COMPENSATED states (not just FAILED)
10. Per-step compensation status in history (compensated_at, compensation_error)
11. List executions with status filter (GET /executions?status=FAILED)
12. Run input payload forwarded to each step HTTP call
13. correlation_id on runs (client-supplied reference)
14. Cancel endpoint (POST /executions/{run_id}/cancel)

### Defer (explicit scope boundaries)

- Retry policy per step (note: MVP defaults to single attempt; RetryPolicy model can be defined but not enforced)
- Idempotency key on execute endpoint
- Workflow versioning
- Parallel steps, fan-out
- Scheduling, webhooks, UI

---

## Sources

- [Netflix Conductor Workflow Definition](https://conductor.netflix.com/configuration/workflowdef.html)
- [Netflix Conductor Workflow API](https://conductor.netflix.com/documentation/api/workflow.html)
- [Conductor OSS API Reference](https://conductor-oss.github.io/conductor/documentation/api/index.html)
- [Temporal Workflow CLI Reference](https://docs.temporal.io/cli/workflow)
- [Temporal Saga Pattern](https://docs.temporal.io/design-patterns/saga-pattern)
- [AWS Step Functions API Reference](https://docs.aws.amazon.com/pdfs/step-functions/latest/apireference/step-functions-api.pdf)
- [AWS Step Functions Execution Status](https://repost.aws/articles/ARW9pOH6ZMTWWXc9q8U_u34A/handling-aws-step-functions-execution-status-for-express-workflows)
- [Bunqueue Workflow Engine Step Schema](https://bunqueue.dev/guide/workflow/steps)
- [Saga Pattern Best Practices — Temporal Blog](https://temporal.io/blog/mastering-saga-patterns-for-distributed-transactions-in-microservices)
- [Webhook Retry and Idempotency](https://hookray.com/blog/webhook-retry-strategies-2026)
- [Workflow Engine State Machine Reference](https://fullstackinfra.substack.com/p/day-99-building-a-production-grade)
- [Prefect Execution States](https://docs.prefect.io/v3/concepts/states)
- [n8n Executions API](https://mintlify.wiki/n8n-io/n8n/api/executions)
