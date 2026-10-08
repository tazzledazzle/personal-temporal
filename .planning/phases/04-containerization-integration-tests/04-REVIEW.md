---
phase: "04"
status: issues_found
files_reviewed: 4
findings:
  critical: 2
  warning: 3
  info: 0
  total: 5
---

# Phase 04 Code Review — Containerization & Integration Tests

**Reviewer:** Claude Code (claude-sonnet-4-6)
**Date:** 2026-10-07
**Files Reviewed:** Dockerfile, pyproject.toml, tests/test_integration.py, docker-compose.yml

---

## Summary

Phase 4 correctly hardens the build backend (`setuptools.build_meta`), adds structured integration tests with proper async session patching and real SQLite fixtures, and wires a named Docker volume for durability. The core patterns are sound: `NullPool` + WAL PRAGMAs on the test engine, `executor_module.AsyncSessionLocal` patching, `respx` mock scoping, and `asyncio_mode = "auto"` in pyproject. Two critical issues must be resolved before any deployment: dev dependencies are shipped in the production image, and there is no `.dockerignore` to prevent secrets from being baked into image layers.

---

## Critical Findings

### CR-01: Production image installs dev dependencies

**File:** `Dockerfile`, line 11
**Confidence:** 95

`pip install --no-cache-dir ".[dev]"` installs pytest, pytest-asyncio, pytest-cov, respx, and httpx into the production image. respx works by patching httpx's transport layer globally; shipping it to production is a latent runtime risk. The image is also significantly larger than necessary.

**Fix:** Install only the base package in production:

```dockerfile
RUN pip install --no-cache-dir "."
```

For a dev/test stage, use a multi-stage build that installs `.[dev]` in an intermediate layer.

---

### CR-02: No `.dockerignore` — `.env` and other sensitive files copied into image

**File:** `Dockerfile`, line 14 (`COPY . .`)
**Confidence:** 95

Without a `.dockerignore`, `COPY . .` copies `.git/`, any local `.env` file (which contains `API_KEY`), `tests/`, `.planning/`, `.agents/`, local `.db` files, and `__pycache__` into every image layer. A real API key baked into a layer is permanently exposed in any registry push.

**Fix:** Add `.dockerignore` in the project root:

```
.git
.env
*.db
tests/
.planning/
.agents/
__pycache__
*.pyc
.pytest_cache
.venv
```

---

## Warning Findings

### WR-01: Container process runs as root

**File:** `Dockerfile`
**Confidence:** 85

No `USER` instruction is present. The uvicorn process runs as UID 0 inside the container. This is a standard Docker security anti-pattern: a container escape or RCE vulnerability gives the attacker root on the host's namespace.

**Fix:** Add before `CMD`:

```dockerfile
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser
```

---

### WR-02: `_wait_for_terminal` references `data` before guaranteed assignment

**File:** `tests/test_integration.py`, line 138
**Confidence:** 80

The `raise AssertionError` f-string references `data["status"]`, but `data` is only assigned inside the `for` loop body. If `max_iters=0` is ever passed, the loop body never executes and Python raises `NameError` instead of the intended `AssertionError`.

**Fix:**

```python
last_status = "<not polled>"
for _ in range(max_iters):
    await asyncio.sleep(sleep_s)
    response = await client.get(f"/runs/{run_id}")
    assert response.status_code == 200, f"GET /runs/{run_id} returned {response.status_code}"
    data = response.json()
    last_status = data["status"]
    if last_status in TERMINAL_STATES:
        return data
raise AssertionError(
    f"Run {run_id} did not reach a terminal state within {max_iters * sleep_s}s. "
    f"Last status: {last_status}"
)
```

---

### WR-03: `docker-compose.yml` hardcodes API key with no secrets indirection

**File:** `docker-compose.yml`, line 12
**Confidence:** 85

`API_KEY=change-me-in-production` is committed directly in the compose file. Anyone who deploys without modifying this value ships a publicly known key. There is no `.env` file reference or `${API_KEY}` variable substitution.

**Fix:** Replace the environment block with:

```yaml
env_file:
  - .env
```

Document a `.env.example` with `API_KEY=change-me` and add `.env` to `.gitignore`.

---

## Verified Correct Patterns

- **pyproject.toml build-backend:** `setuptools.build_meta` is the correct non-legacy backend for isolated pip builds.
- **SQLite WAL PRAGMAs in test fixture:** `integration_engine` correctly uses `event.listens_for(engine.sync_engine, "connect")`.
- **NullPool in test fixture:** `poolclass=NullPool` prevents connection reuse and file-lock accumulation.
- **executor patching:** `executor_module.AsyncSessionLocal = TestSession` correctly patches before background task runs.
- **Session factory:** `expire_on_commit=False` correctly set to prevent `DetachedInstanceError` in async sessions.
- **asyncio_mode = "auto":** Correctly set in `pyproject.toml` — eliminates per-test `@pytest.mark.asyncio`.
- **respx mock scoping:** All tests call `_wait_for_terminal` inside `async with respx.mock(...)` — background task HTTP calls are intercepted.
- **--workers 1 constraint:** Mandatory single-worker documented in CMD comment as SQLite safety constraint.
- **Named volume:** `db_data` volume correctly persists SQLite across container restarts.
- **`delete=False` + `os.unlink`:** Correct `NamedTemporaryFile` teardown pattern.
