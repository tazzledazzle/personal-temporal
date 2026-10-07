# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->


## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Conventions & Patterns

_Add your project-specific conventions here_

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Multi-Step Workflow Executor**

A production-ready REST service for durable, compensatable workflow orchestration. Clients register workflow definitions (ordered steps with HTTP callback URLs), execute them, and query their state and history. When a step fails, the executor automatically compensates already-completed steps using the Saga pattern — calling each step's compensate URL in reverse order.

**Core Value:** **Reliable, durable workflow execution with automatic compensation** — workflows survive restarts, concurrent executions don't collide, and failures are never silent.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

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
### Testing
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | 8.x (latest) | Test runner | Standard |
| pytest-asyncio | 1.4.x | Async test support | Enables `async def` test functions and fixtures; use `asyncio_mode = "auto"` in `pyproject.toml` to avoid per-test `@pytest.mark.asyncio` decoration |
| httpx | 0.28.x | AsyncClient for integration tests | `AsyncClient(transport=ASGITransport(app=app))` replaces FastAPI's sync `TestClient` for async test correctness; same package as outbound HTTP client (no extra dep) |
| pytest-cov | latest | Coverage reporting | Interview showcase should show coverage |
### Containerization
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docker | latest | Container runtime | Interview requirement |
| python:3.11-slim | (base image) | Container base | `slim` drops dev tools and locale data; meaningfully smaller than `full`; `alpine` causes CPython compilation issues with some packages and is not worth the extra complexity |
## Configuration Gotchas
### SQLite WAL Mode (Critical)
### SQLite Connection Pooling (Critical)
- Do **not** set `pool_size` > 1 and expect parallel writes — they will serialize or busy-wait.
- For tests, use `poolclass=StaticPool` with `connect_args={"check_same_thread": False}` to force a single shared in-memory connection.
- For a file-based DB with intermittent `database is locked` errors, switch to `NullPool` — this disables connection reuse and avoids file-lock accumulation at the cost of per-request connection creation overhead (acceptable for SQLite interview scale).
# Production (file-based)
# Test (in-memory, single coroutine)
### FastAPI Dependency Injection for Async DB Sessions
### BackgroundTasks Swappability Pattern
# app/tasks/dispatch.py
### Alembic Async Setup
### Docker + SQLite Volume Mount (Critical)
# docker-compose.yml
### Docker Single-Worker Constraint with SQLite
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
## What NOT to Use and Why
## Installation
# Core application
# Development and testing
# httpx already installed above — used for both outbound calls and AsyncClient testing
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

| Skill | Description | Path |
|-------|-------------|------|
| beads | Use when working in a repository that uses bd or Beads for durable project task tracking, issue dependencies, blocker management, multi-session handoff, or shared work memory. Trigger when the user asks to find ready work, claim or close tasks, create follow-up work, inspect blockers, recover project context, or choose between local planning and persistent project tracking. | `.agents/skills/beads/SKILL.md` |
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
