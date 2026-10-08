import json
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import _write_lock
from app.core.exceptions import ConflictError, NotFoundError
from app.runs.models import WorkflowRun
from app.workflows.models import WorkflowDefinition, WorkflowStep
from app.workflows.schemas import WorkflowCreateRequest


class WorkflowRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, request: WorkflowCreateRequest) -> WorkflowDefinition:
        async with _write_lock:
            steps = [
                WorkflowStep(
                    id=str(uuid4()),
                    workflow_def_id=request.name,
                    step_order=idx,
                    name=step.name,
                    execute_url=str(step.execute_url),
                    compensate_url=str(step.compensate_url) if step.compensate_url else None,
                    timeout_seconds=step.timeout_seconds,
                    retry_policy=(
                        json.dumps(step.retry_policy.model_dump()) if step.retry_policy else None
                    ),
                )
                for idx, step in enumerate(request.steps)
            ]
            definition = WorkflowDefinition(
                id=request.name,
                name=request.name,
                description=request.description,
                steps=steps,
            )
            self._session.add(definition)
            await self._session.commit()
            return definition

    async def get_by_name(self, name: str) -> WorkflowDefinition | None:
        result = await self._session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.id == name)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[WorkflowDefinition]:
        result = await self._session.execute(select(WorkflowDefinition))
        return list(result.scalars().all())

    async def delete_by_name(self, name: str) -> None:
        definition = await self.get_by_name(name)
        if definition is None:
            raise NotFoundError(f"Workflow '{name}' not found")

        # Active-run guard (DEFN-03): reject delete if any non-terminal runs exist
        count_result = await self._session.execute(
            select(func.count(WorkflowRun.id)).where(
                WorkflowRun.workflow_def_id == name,
                WorkflowRun.status.notin_(["COMPLETED", "COMPENSATION_FAILED", "COMPENSATED", "FAILED"]),
            )
        )
        active_count = count_result.scalar_one()
        if active_count > 0:
            raise ConflictError("Active runs exist for this workflow")

        async with _write_lock:
            await self._session.delete(definition)
            await self._session.commit()
