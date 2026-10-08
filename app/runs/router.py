"""
Runs router: POST /workflows/{name}/runs, GET /runs/{id}, GET /runs/{id}/steps
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import APIKey
from app.core.database import get_db
from app.runs.executor import execute_run
from app.runs.repository import RunRepo
from app.runs.schemas import RunResponse, StartRunRequest, StepExecutionResponse
from app.workflows.models import WorkflowDefinition

router = APIRouter(tags=["runs"])
DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/workflows/{workflow_name}/runs", status_code=202)
async def start_run(
    workflow_name: str,
    body: StartRunRequest,
    background_tasks: BackgroundTasks,
    db: DBSession,
    _: APIKey,
) -> dict:
    wf_result = await db.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_name)
    )
    if wf_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found")
    repo = RunRepo(db)
    run = await repo.create(workflow_name, body.input)
    background_tasks.add_task(execute_run, run.id, workflow_name)
    return {"run_id": run.id}


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, db: DBSession, _: APIKey) -> RunResponse:
    run = await RunRepo(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return RunResponse.model_validate(run)


@router.get("/runs/{run_id}/steps", response_model=list[StepExecutionResponse])
async def get_run_steps(run_id: str, db: DBSession, _: APIKey) -> list[StepExecutionResponse]:
    repo = RunRepo(db)
    if await repo.get_by_id(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    steps = await repo.list_steps_by_run_id(run_id)
    return [StepExecutionResponse.model_validate(s) for s in steps]
