---
phase: 1
slug: foundation-persistence
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-07
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24.x + httpx 0.27.x |
| **Config file** | `pyproject.toml` (asyncio_mode = "auto") |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v --tb=short`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| DB engine setup | 01 | 0 | RESIL-04 | — | WAL mode + busy_timeout prevents deadlocks | unit | `pytest tests/test_db.py -x -q` | ❌ W0 | ⬜ pending |
| API key auth | 01 | 1 | PLAT-01 | T-1-01 | 401 without valid key; timing-safe comparison | unit | `pytest tests/test_auth.py -x -q` | ❌ W0 | ⬜ pending |
| Definition CRUD | 01 | 1 | DEFN-01, DEFN-02 | — | 201 on create, 200 on read, 404 on missing | integration | `pytest tests/test_definitions.py -x -q` | ❌ W0 | ⬜ pending |
| Definition delete | 01 | 1 | DEFN-03 | — | 204 when no active runs; 409 when active runs | integration | `pytest tests/test_definitions.py::test_delete -x -q` | ❌ W0 | ⬜ pending |
| Health check | 01 | 1 | PLAT-03 | — | 200 with DB status; 503 when DB unreachable | integration | `pytest tests/test_health.py -x -q` | ❌ W0 | ⬜ pending |
| Structured logging | 01 | 1 | PLAT-02 | — | JSON log lines include correlation_id field | unit | `pytest tests/test_logging.py -x -q` | ❌ W0 | ⬜ pending |
| Concurrent writes | 01 | 2 | RESIL-04 | — | No lost updates under concurrent POST /workflows | integration | `pytest tests/test_concurrency.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — shared fixtures: async_engine (StaticPool in-memory), async_session, test_client (ASGITransport + httpx.AsyncClient), valid_api_key
- [ ] `tests/test_db.py` — stub: test WAL pragma set, test asyncio.Lock prevents concurrent writes
- [ ] `tests/test_auth.py` — stub: test 401 without key, test 401 with wrong key, test 200 with valid key
- [ ] `tests/test_definitions.py` — stubs: test_create_definition, test_get_definition, test_list_definitions, test_delete_definition_no_runs, test_delete_definition_with_runs
- [ ] `tests/test_health.py` — stub: test_health_returns_200, test_health_db_status_field
- [ ] `tests/test_logging.py` — stub: test correlation_id in log output

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Docker compose starts and GET /health returns 200 | PLAT-04 | Requires Docker daemon | `docker-compose up -d && curl http://localhost:8000/health` |
| SQLite data persists across docker-compose restart | RESIL-01 | Requires volume mount | `docker-compose down && docker-compose up -d && curl GET /workflows` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
