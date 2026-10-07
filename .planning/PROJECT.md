# Multi-Step Workflow Executor

## What This Is

A production-ready REST service for durable, compensatable workflow orchestration. Clients register workflow definitions (ordered steps with HTTP callback URLs), execute them, and query their state and history. When a step fails, the executor automatically compensates already-completed steps using the Saga pattern — calling each step's compensate URL in reverse order.

## Core Value

**Reliable, durable workflow execution with automatic compensation** — workflows survive restarts, concurrent executions don't collide, and failures are never silent.

## Context

Built as an interview showcase demonstrating systems design depth: durable state machines, distributed compensation patterns, concurrent execution, and a clean REST API. Python + FastAPI + SQLite keeps the stack self-contained; the async concurrency model is designed to extend to Celery + broker without architectural changes.

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI (async, OpenAPI-first)
- **Database:** SQLite (via SQLAlchemy async + aiosqlite)
- **Concurrency:** asyncio + FastAPI BackgroundTasks (extensible to Celery)
- **Auth:** API key via `X-API-Key` header
- **Compensation model:** Saga pattern — reverse-order HTTP compensate calls

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Register named workflow definitions with ordered steps (each step has execute + compensate URLs)
- [ ] Execute a workflow by name; executor calls step URLs in order via HTTP
- [ ] On step failure, compensate all previously-completed steps in reverse order
- [ ] Persist workflow runs and step states to SQLite; survive process restarts
- [ ] Support concurrent workflow executions without state corruption
- [ ] Query workflow run state (status, current step, timestamps)
- [ ] Query step execution history for a workflow run
- [ ] API key authentication on all endpoints
- [ ] Observability: structured logging, health check endpoint
- [ ] Docker-ready: Dockerfile + docker-compose for local dev

### Out of Scope

- Scheduling / cron-triggered workflows — focus is on demand-triggered execution
- UI dashboard — REST API surface is sufficient for this scope
- Multi-tenant / org isolation — single-tenant API key is sufficient
- Distributed broker (Celery) — architecture leaves room for it but won't implement

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| SQLite over PostgreSQL | Zero-infra, self-contained for interview context; SQLAlchemy async layer makes future migration straightforward | Pending |
| Saga over 2PC | Each step owns its own rollback logic; executor is just a coordinator, not a transaction manager | Pending |
| asyncio in-process over Celery | Avoids broker infra; BackgroundTasks pattern is directly replaceable with Celery tasks | Pending |
| FastAPI over Flask/Django | Native async, auto-generated OpenAPI docs, Pydantic validation — right tool for an API-first service | Pending |
| API key over JWT | Simpler to demo and test; JWT adds complexity without showcasing workflow engine architecture | Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-07 after initialization*
