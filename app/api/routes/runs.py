from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import enforce_run_rate_limit, get_current_user
from app.models.dataset import Dataset, DatasetVersion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.regression import RegressionRun
from app.models.response import Response
from app.models.run import Run, RunStatus
from app.models.user import User
from app.repositories.question_repository import QuestionRepository
from app.repositories.run_repository import RunRepository
from app.workers.eval_tasks import dispatch_run

# eng-review D2: read-only endpoints (leaderboard.py, GET /runs/{id}) require
# no auth. Creating a Run is the one exception: it costs real provider API
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


class RunListItem(BaseModel):
    id: int
    project_id: int
    dataset_version_id: int
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None
    response_count: int


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
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

    questions = await QuestionRepository(session).list_for_dataset_version(body.dataset_version_id)
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset version has no sampled questions"
        )

    run = await RunRepository(session).add(
        Run(project_id=body.project_id, dataset_version_id=body.dataset_version_id, status=RunStatus.RUNNING)
    )
    # Commit before dispatch, not after — Celery workers run in a separate
    # process (eng-review D1) and must see this Run row (and every question
    # id referenced below) before a task tries to load it.
    await session.commit()

    dispatch_run(run.id, [q.id for q in questions], [m.id for m in models])

    return run


@router.get("", response_model=list[RunListItem])
async def list_runs(project_id: int, session: AsyncSession = Depends(get_session)) -> list[RunListItem]:
    """Public, no-auth (D2). Backs the Experiment History dashboard page.
    Excludes regression-run-owned runs — those show up under Regression
    Results instead (see leaderboard.py's identical exclusion filter and
    its rationale)."""
    regression_run_ids = select(RegressionRun.run_id)
    stmt = (
        select(
            Run.id,
            Run.project_id,
            Run.dataset_version_id,
            Run.status,
            Run.created_at,
            Run.completed_at,
            func.count(Response.id).label("response_count"),
        )
        .outerjoin(Response, Response.run_id == Run.id)
        .where(Run.project_id == project_id, Run.id.not_in(regression_run_ids))
        .group_by(Run.id)
        .order_by(Run.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        RunListItem(
            id=r.id,
            project_id=r.project_id,
            dataset_version_id=r.dataset_version_id,
            status=r.status,
            created_at=r.created_at,
            completed_at=r.completed_at,
            response_count=r.response_count,
        )
        for r in rows
    ]


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: int, session: AsyncSession = Depends(get_session)) -> Run:
    """Public, no-auth (D2) — the frontend polls this after POST /runs
    dispatches the async Celery chord, since the run is no longer completed
    synchronously within the POST request/response cycle (Phase 5)."""
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run
