from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import enforce_run_rate_limit, get_current_user, get_evaluation_service, get_llm_runner
from app.evaluation.scoring_service import EvaluationService
from app.llm.runner import LLMRunner
from app.models.dataset import Dataset, DatasetVersion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.run import Run, RunStatus
from app.models.user import User
from app.repositories.run_repository import RunRepository
from app.services.run_orchestrator import RunOrchestrator

# eng-review D2: read-only endpoints (leaderboard.py) require no auth. This
# endpoint is the one exception: creating a Run costs real provider API
# money, so it requires both a valid JWT (get_current_user) AND the rate
# limit (enforce_run_rate_limit) — the rate limit does not trust auth alone
# to be sufficient.
router = APIRouter(prefix="/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    project_id: int
    dataset_version_id: int
    model_ids: list[int]


class RunResponse(BaseModel):
    id: int
    project_id: int
    dataset_version_id: int
    status: RunStatus
    completed_at: datetime | None

    model_config = {"from_attributes": True}


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    llm_runner: LLMRunner = Depends(get_llm_runner),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
) -> Run:
    if not body.model_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="model_ids must not be empty")

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

    models_result = await session.execute(select(LLMModel).where(LLMModel.id.in_(body.model_ids)))
    models = list(models_result.scalars().all())
    if len(models) != len(set(body.model_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more model_ids not found")

    await enforce_run_rate_limit(project_id=body.project_id, session=session)

    run = await RunRepository(session).add(
        Run(project_id=body.project_id, dataset_version_id=body.dataset_version_id, status=RunStatus.RUNNING)
    )
    await session.flush()

    # Phase 4: synchronous execution — one HTTP request runs the whole batch
    # and returns once complete. eng-review D12 moves this into one Celery
    # task per (question, model) pair in Phase 5; RunOrchestrator is already
    # structured that way internally so that move doesn't require a rewrite.
    orchestrator = RunOrchestrator(session, llm_runner, evaluation_service)
    await orchestrator.execute(run, models)

    await session.commit()
    return run
