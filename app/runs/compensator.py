"""
CompensationCoordinator: LIFO Saga compensation dispatch.

Invoked by execute_run after a step failure. Queries COMPLETED step executions
in reverse completion order (LIFO by completed_at DESC), calls each step's
compensate_url, records per-step outcome, and sets run.status to
COMPENSATED or COMPENSATION_FAILED.

Design invariants:
- Dependency-injected: receives session and http_client from executor; never
  constructs its own session factory or HTTP client (conftest.py patching works).
- Continue-on-failure: compensation chain never stops on individual failure (COMP-01).
- All DB writes happen inside `async with _write_lock:` (same pattern as executor.py).
"""

from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import _write_lock
from app.runs.models import WorkflowRun, WorkflowStepExecution
from app.workflows.models import WorkflowStep


class CompensationCoordinator:
    """Drive LIFO compensation for a failed workflow run."""

    def __init__(self, session: AsyncSession, http_client: httpx.AsyncClient) -> None:
        self.session = session
        self.http_client = http_client

    async def compensate(self, run: WorkflowRun) -> None:
        """
        Compensate all COMPLETED step executions for *run* in LIFO order.

        Steps without a compensate_url are silently skipped (compensation_status
        remains NULL). Steps whose compensation call fails are recorded as FAILED
        and the loop continues. After all steps are processed, run.status is set
        to COMPENSATED or COMPENSATION_FAILED based on the aggregate outcome.
        """
        # 1. Fetch COMPLETED step executions for this run, newest first (LIFO).
        stmt = (
            select(WorkflowStepExecution)
            .where(
                WorkflowStepExecution.run_id == run.id,
                WorkflowStepExecution.status == "COMPLETED",
            )
            .order_by(WorkflowStepExecution.completed_at.desc())
        )
        step_execs = (await self.session.execute(stmt)).scalars().all()

        # 2. Process each completed step in LIFO order.
        for step_exec in step_execs:
            # Look up the workflow step definition to get compensate_url.
            ws_stmt = select(WorkflowStep).where(
                WorkflowStep.workflow_def_id == run.workflow_def_id,
                WorkflowStep.step_order == step_exec.step_index,
            )
            ws_result = await self.session.execute(ws_stmt)
            workflow_step = ws_result.scalar_one_or_none()

            # Skip if no workflow step or no compensate_url defined.
            if workflow_step is None or not workflow_step.compensate_url:
                continue

            # Attempt to call the compensate_url.
            try:
                response = await self.http_client.post(
                    workflow_step.compensate_url,
                    timeout=httpx.Timeout(30),
                )
                if 200 <= response.status_code < 300:
                    step_exec.compensation_status = "COMPLETED"
                    step_exec.compensated_at = datetime.utcnow()
                    step_exec.compensation_error = None
                else:
                    step_exec.compensation_status = "FAILED"
                    step_exec.compensation_error = f"HTTP {response.status_code}"
                    step_exec.compensated_at = None
            except Exception as exc:  # noqa: BLE001 — continue-on-failure is the contract
                step_exec.compensation_status = "FAILED"
                step_exec.compensation_error = str(exc)[:500]
                step_exec.compensated_at = None

            # Persist per-step outcome immediately so partial progress is visible.
            async with _write_lock:
                await self.session.commit()

        # 3. Set aggregate run status based on per-step outcomes.
        any_failed = any(
            se.compensation_status == "FAILED" for se in step_execs
        )
        run.status = "COMPENSATION_FAILED" if any_failed else "COMPENSATED"
        run.completed_at = datetime.utcnow()
        async with _write_lock:
            await self.session.commit()
