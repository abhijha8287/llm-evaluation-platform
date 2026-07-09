from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import enforce_run_rate_limit, get_current_user
from app.models.dataset import Dataset, DatasetVersion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.prompt import PromptTemplate, PromptVersion
from app.models.regression import RegressionResult, RegressionRun, RegressionStatus
from app.models.user import User
from app.repositories.question_repository import QuestionRepository
from app.services.regression_service import RegressionService
from app.workers.eval_tasks import dispatch_regression_run

# eng-review D2/D7: creating a regression run costs the same real API money
# as POST /runs (it generates real responses + real judge scoring through
# the same pipeline) — same auth + rate-limit gate, reusing
# enforce_run_rate_limit directly since the underlying Run it creates is
# counted by the same per-project daily cap.
router = APIRouter(prefix="/regression-runs", tags=["regression"])


class CreateRegressionRunRequest(BaseModel):
    prompt_version_id: int
    dataset_version_id: int
    model_id: int
    baseline_prompt_version_id: int | None = None


class RegressionRunResponse(BaseModel):
    id: int
    prompt_version_id: int
    baseline_prompt_version_id: int | None
    dataset_version_id: int
    model_id: int
    run_id: int
    status: RegressionStatus
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class RegressionResultResponse(BaseModel):
    question_id: int
    metric_name: str
    score: float | None
    delta_from_baseline: float | None

    model_config = {"from_attributes": True}


class RegressionRunDetailResponse(RegressionRunResponse):
    results: list[RegressionResultResponse]


@router.post("", response_model=RegressionRunResponse, status_code=status.HTTP_201_CREATED)
async def create_regression_run(
    body: CreateRegressionRunRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RegressionRun:
    prompt_version = await session.get(PromptVersion, body.prompt_version_id)
    if prompt_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt version not found")
    prompt_template = await session.get(PromptTemplate, prompt_version.prompt_template_id)
    project = await session.get(Project, prompt_template.project_id)
    if project is None or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt version not found")

    dataset_version_stmt = (
        select(DatasetVersion.id)
        .join(Dataset, DatasetVersion.dataset_id == Dataset.id)
        .where(DatasetVersion.id == body.dataset_version_id, Dataset.project_id == project.id)
    )
    if (await session.execute(dataset_version_stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")

    model = await session.get(LLMModel, body.model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    if body.baseline_prompt_version_id is not None:
        baseline_version = await session.get(PromptVersion, body.baseline_prompt_version_id)
        if baseline_version is None or baseline_version.prompt_template_id != prompt_version.prompt_template_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="baseline_prompt_version_id must belong to the same prompt template",
            )

    questions = await QuestionRepository(session).list_for_dataset_version(body.dataset_version_id)
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset version has no sampled questions"
        )

    await enforce_run_rate_limit(project_id=project.id, session=session)

    regression_run = await RegressionService(session).create_run(
        body.prompt_version_id, body.dataset_version_id, body.model_id, body.baseline_prompt_version_id
    )
    # Commit before dispatch — same reason as POST /runs: Celery workers run
    # in a separate process and must see this row before a task references it.
    await session.commit()

    dispatch_regression_run(regression_run.id, [q.id for q in questions])

    return regression_run


@router.get("", response_model=list[RegressionRunResponse])
async def list_regression_runs(
    prompt_template_id: int, session: AsyncSession = Depends(get_session)
) -> list[RegressionRun]:
    """Public, no-auth (D2) — backs the Regression Results dashboard page.
    Filtered by prompt_template_id (not prompt_version_id) so the page can
    show the full history across every version of a template in one list."""
    stmt = (
        select(RegressionRun)
        .join(PromptVersion, PromptVersion.id == RegressionRun.prompt_version_id)
        .where(PromptVersion.prompt_template_id == prompt_template_id)
        .order_by(RegressionRun.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{regression_run_id}", response_model=RegressionRunDetailResponse)
async def get_regression_run(
    regression_run_id: int, session: AsyncSession = Depends(get_session)
) -> RegressionRun:
    """Public, no-auth (D2) — same as GET /runs/{id}."""
    regression_run = await session.get(RegressionRun, regression_run_id)
    if regression_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regression run not found")

    results = (
        await session.execute(
            select(RegressionResult).where(RegressionResult.regression_run_id == regression_run_id)
        )
    ).scalars().all()

    return RegressionRunDetailResponse(
        id=regression_run.id,
        prompt_version_id=regression_run.prompt_version_id,
        baseline_prompt_version_id=regression_run.baseline_prompt_version_id,
        dataset_version_id=regression_run.dataset_version_id,
        model_id=regression_run.model_id,
        run_id=regression_run.run_id,
        status=regression_run.status,
        completed_at=regression_run.completed_at,
        results=[RegressionResultResponse.model_validate(r) for r in results],
    )
