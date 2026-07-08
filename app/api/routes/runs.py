from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import enforce_run_rate_limit, get_current_user
from app.models.dataset import Dataset, DatasetVersion
from app.models.project import Project
from app.models.run import Run, RunStatus
from app.models.user import User
from app.repositories.run_repository import RunRepository

# eng-review D2: read-only endpoints (not yet built — arrive with Phase 4's
# leaderboard) require no auth. This endpoint is the one exception: creating
# a Run costs real provider API money, so it requires both a valid JWT
# (get_current_user) AND the rate limit (enforce_run_rate_limit) — the rate
# limit does not trust auth alone to be sufficient.
router = APIRouter(prefix="/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    project_id: int
    dataset_version_id: int


class RunResponse(BaseModel):
    id: int
    project_id: int
    dataset_version_id: int
    status: RunStatus

    model_config = {"from_attributes": True}


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Run:
    project = await session.get(Project, body.project_id)
    if project is None or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Explicit join rather than dataset_version.dataset.project_id — async
    # SQLAlchemy raises MissingGreenlet on implicit lazy-loaded relationship
    # access outside an awaited load, so validation queries the FK chain
    # directly instead of traversing relationships.
    stmt = (
        select(DatasetVersion.id)
        .join(Dataset, DatasetVersion.dataset_id == Dataset.id)
        .where(DatasetVersion.id == body.dataset_version_id, Dataset.project_id == body.project_id)
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")

    await enforce_run_rate_limit(project_id=body.project_id, session=session)

    run = await RunRepository(session).add(
        Run(project_id=body.project_id, dataset_version_id=body.dataset_version_id, status=RunStatus.PENDING)
    )
    await session.commit()
    # Dispatch to Celery (one task per question x provider pair, per D1/D12)
    # is wired in Phase 5. Until then, the Run persists as PENDING — this
    # endpoint's scope is "create and rate-limit a Run," not "execute one";
    # see design doc Next Steps and TODOS.md for the phase boundary.
    return run
