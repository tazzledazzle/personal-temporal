"""
execute_run: background task that drives a workflow run from PENDING to terminal state.

Two architectural invariants:
1. Persist-before-dispatch: every state transition is committed to SQLite BEFORE the
   outbound HTTP call. If the process crashes mid-execution, the DB shows RUNNING and
   a zombie detection sweep (v2) can recover it.

2. Module-level AsyncSessionLocal: imported at module load so tests can patch it via
       import app.runs.executor as m; m.AsyncSessionLocal = test_session_factory
   The self-import pattern inside execute_run re-reads the attribute at call time,
   ensuring the patched value is used rather than the import-time reference.
"""

import json
from datetime import datetime
from uuid import uuid4

import httpx
from sqlalchemy import select

# Module-level import — patchable by tests via:
#   import app.runs.executor as m; m.AsyncSessionLocal = test_factory
from app.core.database import AsyncSessionLocal
from app.core.database import _write_lock
from app.runs.compensator import CompensationCoordinator
from app.runs.models import WorkflowRun, WorkflowStepExecution
from app.workflows.models import WorkflowDefinition


async def execute_run(run_id: str, workflow_def_id: str) -> None:
    """
    Background task: drive a workflow run from PENDING to terminal state.

    Creates its own AsyncSession — cannot reuse the request session (closed after 202 response).
    Uses the module-level AsyncSessionLocal so tests can patch it to the test engine.

    Persist-before-dispatch: every status transition committed to DB BEFORE HTTP call.
    """
    # Use module-level name so tests can patch app.runs.executor.AsyncSessionLocal
    import app.runs.executor as _self
    session_factory = _self.AsyncSessionLocal

    async with session_factory() as session:
        run_result = await session.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        run = run_result.scalar_one()

        wf_result = await session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_def_id)
        )
        wf = wf_result.scalar_one()

        # Transition run PENDING → RUNNING — persist before dispatch
        async with _write_lock:
            run.status = "RUNNING"
            run.started_at = datetime.utcnow()
            await session.commit()

        async with httpx.AsyncClient() as http_client:
            for step in wf.steps:
                # Persist step as RUNNING before HTTP call (persist-before-dispatch)
                step_exec = WorkflowStepExecution(
                    id=str(uuid4()),
                    run_id=run_id,
                    step_index=step.step_order,
                    step_name=step.name,
                    status="RUNNING",
                    started_at=datetime.utcnow(),
                )
                async with _write_lock:
                    session.add(step_exec)
                    run.current_step_index = step.step_order
                    await session.commit()

                timeout = step.timeout_seconds or 30
                try:
                    response = await http_client.post(
                        step.execute_url,
                        json=json.loads(run.input_payload) if run.input_payload else {},
                        timeout=httpx.Timeout(timeout),
                    )
                    if 200 <= response.status_code < 300:
                        async with _write_lock:
                            step_exec.status = "COMPLETED"
                            step_exec.http_status_code = response.status_code
                            step_exec.completed_at = datetime.utcnow()
                            await session.commit()
                    else:
                        async with _write_lock:
                            step_exec.status = "FAILED"
                            step_exec.http_status_code = response.status_code
                            step_exec.error_detail = f"HTTP {response.status_code}"
                            step_exec.completed_at = datetime.utcnow()
                            run.status = "FAILED"
                            run.error_detail = (
                                f"Step '{step.name}' failed: HTTP {response.status_code}"
                            )
                            run.completed_at = datetime.utcnow()
                            await session.commit()
                        await CompensationCoordinator(session, http_client).compensate(run)
                        return
                except httpx.TimeoutException:
                    async with _write_lock:
                        step_exec.status = "FAILED"
                        step_exec.error_detail = f"Timeout after {timeout}s"
                        step_exec.completed_at = datetime.utcnow()
                        run.status = "FAILED"
                        run.error_detail = f"Step '{step.name}' timeout after {timeout}s"
                        run.completed_at = datetime.utcnow()
                        await session.commit()
                    await CompensationCoordinator(session, http_client).compensate(run)
                    return

        # All steps completed successfully
        async with _write_lock:
            run.status = "COMPLETED"
            run.completed_at = datetime.utcnow()
            await session.commit()
