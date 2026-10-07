---
phase: 04-containerization-integration-tests
plan: 01
subsystem: infra
tags: [docker, dockerfile, docker-compose, sqlite, python, setuptools]

# Dependency graph
requires:
  - phase: 03-saga-compensation
    provides: Full application codebase with WorkflowRunner, CompensationCoordinator, all routers, models, and migrations ready to containerize
provides:
  - Verified Dockerfile with python:3.11-slim base, --workers 1 hardcoded in CMD, pip/setuptools upgrade for build compatibility
  - Verified docker-compose.yml with named volume db_data mounted at /app/data, DATABASE_URL pointing to /app/data/workflows.db
  - Working docker build: workflow-executor-test image builds and app import passes
affects:
  - 04-02-integration-tests
  - 04-03-integration-tests-green

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Docker layer caching: COPY pyproject.toml + pip install before COPY . . for fast rebuilds"
    - "pip upgrade before install: RUN pip install --upgrade pip setuptools in base image step to resolve setuptools.backends compatibility"
    - "Single-worker constraint documented in CMD comment: --workers 1 must not be overridden"
    - "Named volume pattern: db_data named volume (not bind mount) ensures portability and data durability"

key-files:
  created: []
  modified:
    - Dockerfile
    - pyproject.toml

key-decisions:
  - "Use setuptools.build_meta instead of setuptools.backends.legacy:build — stable build backend present since setuptools 38, avoids BackendUnavailable error in pip's isolated build subprocess inside python:3.11-slim"
  - "Add RUN pip install --upgrade pip setuptools before dependency install — python:3.11-slim ships with pip 24.x which triggers BackendUnavailable for newer setuptools build backends; upgrade resolves it"
  - "docker-compose.yml required no changes — all constraints (named volume, DATABASE_URL, API_KEY, port mapping, comment) were already correctly configured"

patterns-established:
  - "Dockerfile pip upgrade pattern: always upgrade pip+setuptools in a separate RUN layer before package install to avoid build backend version mismatches"

requirements-completed:
  - PLAT-04

# Metrics
duration: 20min
completed: 2026-10-07
---

# Phase 4 Plan 01: Docker Audit and Hardening Summary

**Dockerfile hardened for python:3.11-slim pip/setuptools compatibility; docker build exits 0; --workers 1 confirmed hardcoded; named volume db_data correctly configured in docker-compose.yml**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-10-07T23:30:00Z
- **Completed:** 2026-10-07T23:50:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Dockerfile audited and hardened: all 7 constraints verified (base image, WORKDIR, layer-cached deps, app COPY, /app/data directory, EXPOSE 8000, --workers 1 CMD)
- Fixed pip/setuptools build compatibility: python:3.11-slim ships with pip 24.x which fails to import `setuptools.backends.legacy` in isolated build subprocess; switched to `setuptools.build_meta` (stable since setuptools 38) and added pip/setuptools upgrade step
- `docker build -t workflow-executor-test .` exits 0; `docker run` app import check confirms `from app.main import app` succeeds inside the image
- docker-compose.yml audited: all 6 constraints already met (named volume db_data, mount at /app/data, correct DATABASE_URL with four slashes, API_KEY placeholder, port 8000:8000, volume comment)
- `docker-compose config` exits 0 with no errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Audit and harden Dockerfile** - `aef91be` (chore)
2. **Task 2: Audit and harden docker-compose.yml** - no commit needed (already correct, zero changes)

**Plan metadata:** (committed with SUMMARY.md)

## Files Created/Modified

- `Dockerfile` - Added `RUN pip install --upgrade pip setuptools` step before dep install; all other constraints already correct
- `pyproject.toml` - Changed `build-backend` from `setuptools.backends.legacy:build` to `setuptools.build_meta`; changed `requires = ["setuptools>=68"]` (no version change needed, build_meta exists in setuptools 38+)

## Decisions Made

- **Switch build-backend to setuptools.build_meta:** `setuptools.backends.legacy:build` was added in setuptools 69 but pip's build isolation subprocess fails to find it even after upgrading setuptools globally. `setuptools.build_meta` has been the stable build backend since setuptools 38 and is universally supported. This is the correct long-term choice.
- **Add pip+setuptools upgrade step in Dockerfile:** python:3.11-slim ships with pip 24.0. Even with `setuptools.build_meta`, upgrading pip and setuptools ensures we get the latest wheel-building fixes. This layer is cached separately from the app dependency install.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `setuptools.backends.legacy:build` BackendUnavailable in Docker**
- **Found during:** Task 1 (docker build -t workflow-executor-test .)
- **Issue:** `pip._vendor.pyproject_hooks._impl.BackendUnavailable: No module named 'setuptools.backends'` — the `setuptools.backends.legacy:build` backend requires setuptools >= 69 but pip's isolated build subprocess cannot find it even after upgrading setuptools in the parent layer
- **Fix:** Changed `pyproject.toml` `build-backend` to `setuptools.build_meta` (the stable, universal build backend) and added `RUN pip install --upgrade pip setuptools` step in Dockerfile
- **Files modified:** `pyproject.toml`, `Dockerfile`
- **Verification:** `docker build -t workflow-executor-test .` exits 0; `docker run` app import check passes
- **Committed in:** `aef91be` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** The build-backend change is a necessary correctness fix. `setuptools.build_meta` is the canonical stable backend; `setuptools.backends.legacy:build` is a newer alias that introduces a version constraint. No scope creep — still pip-install-based, same package, same versions.

## Issues Encountered

- Docker daemon was not running at plan start — started Docker Desktop via `open -a Docker` and waited for daemon to become available. Normal dev environment startup; no impact on the plan.

## Threat Flags

No new security surface introduced. Changes are build-tooling only (build-backend alias + pip upgrade). No new network endpoints, auth paths, file access patterns, or schema changes.

## Known Stubs

None — this plan creates no application code, only build infrastructure.

## Next Phase Readiness

- Docker image builds and app imports cleanly — ready for integration test authoring (04-02)
- docker-compose.yml is verified correct — `docker-compose up` will work for the human-verify checkpoint in 04-03
- SQLite named volume (db_data at /app/data) confirmed — durability test in Phase 4 success criterion 2 is structurally satisfied
- Only blocker to full Phase 4 completion: integration tests (04-02 RED, 04-03 GREEN)

---
*Phase: 04-containerization-integration-tests*
*Completed: 2026-10-07*
