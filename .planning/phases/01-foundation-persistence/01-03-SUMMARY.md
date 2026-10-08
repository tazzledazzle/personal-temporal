---
phase: 01-foundation-persistence
plan: "03"
status: complete
wave: 3
completed: 2026-10-07
---

# Plan 01-03 Summary — Wave 3: Workflow Definition CRUD

## Outcome

All 13 Phase 1 tests pass. `pytest tests/ -x -q` exits 0.

## Files Created / Modified

| File | Action | Purpose |
|------|--------|---------|
| `app/workflows/models.py` | Created | WorkflowDefinition + WorkflowStep ORM models; `lazy="selectin"` for async safety; `version` column for RESIL-04 |
| `app/workflows/schemas.py` | Created | Pydantic v2 request/response schemas; `HttpUrl` validation on execute_url/compensate_url (T-1-04) |
| `app/workflows/repository.py` | Created | WorkflowRepo: create/get_by_name/list_all/delete_by_name; `_write_lock` acquired on all writes (RESIL-04); active-run guard on delete (DEFN-03) |
| `app/workflows/router.py` | Created | POST/GET/DELETE /workflows routes; all declare `APIKey` dependency (PLAT-01); 204 returns `Response(status_code=204)` with no body |
| `app/main.py` | Updated | Replaced stub router with real `workflows_router`; removed Plan 02 stub |
| `app/lifespan.py` | Updated | Added model imports so `Base.metadata.create_all` creates all 3 tables on startup |
| `migrations/versions/0001_initial_schema.py` | Created | Alembic migration for workflow_definitions, workflow_steps, workflow_runs |

## Key Decisions

- **`datetime` type on `WorkflowResponse`** (not `str`): Pydantic v2 validates `from_attributes` before custom `model_validate` logic runs; using `datetime` lets Pydantic handle ORM-to-schema coercion, then JSON serializer converts to ISO string.
- **`lazy="selectin"`**: Required for async SQLAlchemy — default lazy load triggers `MissingGreenlet` exception when accessed outside the connection context.
- **`_write_lock` imported from `app.core.database`**: Single module-level lock shared across all repo instances. Re-instantiating per-repo would defeat the concurrency protection.

## Requirements Satisfied

| Requirement | Test | Status |
|-------------|------|--------|
| DEFN-01 | test_create_workflow_returns_201 | ✅ |
| DEFN-02 | test_get_workflow_by_name, test_list_workflows, test_get_missing_workflow_returns_404 | ✅ |
| DEFN-03 | test_delete_workflow_no_runs_returns_204 | ✅ |
| RESIL-04 | _write_lock in repository.py + WAL in conftest | ✅ |

## Phase 1 Gate

```
pytest tests/ -x -q  →  13 passed, 8 warnings
```

All 5 test files GREEN: test_database, test_auth, test_health, test_workflows, test_logging.
