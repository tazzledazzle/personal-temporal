"""
RunRepo: data access layer for WorkflowRun and WorkflowStepExecution.
"""

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import _write_lock
from app.runs.models import WorkflowRun, WorkflowStepExecution


class RunRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, workflow_def_id: str, input_payload: dict | None) -> WorkflowRun:
        async with _write_lock:
            run = WorkflowRun(
                id=str(uuid4()),
                workflow_def_id=workflow_def_id,
                status="PENDING",
                input_payload=json.dumps(input_payload) if input_payload else None,
            )
            self._session.add(run)
            await self._session.commit()
            return run

    async def get_by_id(self, run_id: str) -> WorkflowRun | None:
        result = await self._session.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_steps_by_run_id(self, run_id: str) -> list[WorkflowStepExecution]:
        result = await self._session.execute(
            select(WorkflowStepExecution)
            .where(WorkflowStepExecution.run_id == run_id)
            .order_by(WorkflowStepExecution.step_index)
        )
        return list(result.scalars().all())
