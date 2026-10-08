from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import APIKey
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.workflows.repository import WorkflowRepo
from app.workflows.schemas import WorkflowCreateRequest, WorkflowResponse

router = APIRouter(prefix="/workflows", tags=["workflows"])

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("", status_code=201, response_model=WorkflowResponse)
async def create_workflow(
    body: WorkflowCreateRequest,
    db: DBSession,
    _: APIKey,
) -> WorkflowResponse:
    repo = WorkflowRepo(db)
    definition = await repo.create(body)
    return WorkflowResponse.model_validate(definition)


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(db: DBSession, _: APIKey) -> list[WorkflowResponse]:
    repo = WorkflowRepo(db)
    definitions = await repo.list_all()
    return [WorkflowResponse.model_validate(d) for d in definitions]


@router.get("/{name}", response_model=WorkflowResponse)
async def get_workflow(name: str, db: DBSession, _: APIKey) -> WorkflowResponse:
    repo = WorkflowRepo(db)
    definition = await repo.get_by_name(name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    return WorkflowResponse.model_validate(definition)


@router.delete("/{name}", status_code=204)
async def delete_workflow(name: str, db: DBSession, _: APIKey) -> Response:
    repo = WorkflowRepo(db)
    try:
        await repo.delete_by_name(name)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return Response(status_code=204)
