from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.question import QuestionType
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.question_repository import QuestionRepository

# eng-review D2: read-only public access, same as leaderboard.py and GET
# /runs/{id} — these are the browsing endpoints behind the Projects/Datasets
# dashboard pages (design doc Phase 8), not write actions, so no auth gate.
projects_router = APIRouter(prefix="/projects", tags=["catalog"])
datasets_router = APIRouter(prefix="/datasets", tags=["catalog"])


class ProjectResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetVersionSummary(BaseModel):
    id: int
    version_number: int
    sample_size: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetResponse(BaseModel):
    id: int
    project_id: int
    name: str
    created_at: datetime
    versions: list[DatasetVersionSummary]

    model_config = {"from_attributes": True}


class QuestionResponse(BaseModel):
    id: int
    dataset_id: int
    type: QuestionType
    text: str
    has_retrieval_context: bool
    expected_output: str | None


@projects_router.get("", response_model=list[ProjectResponse])
async def list_projects(session: AsyncSession = Depends(get_session)) -> list[ProjectResponse]:
    projects = await ProjectRepository(session).list()
    return [ProjectResponse.model_validate(p) for p in projects]


@projects_router.get("/{project_id}/datasets", response_model=list[DatasetResponse])
async def list_project_datasets(
    project_id: int, session: AsyncSession = Depends(get_session)
) -> list[DatasetResponse]:
    project = await ProjectRepository(session).get(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    datasets = await DatasetRepository(session).list_for_project(project_id)
    return [DatasetResponse.model_validate(d) for d in datasets]


@datasets_router.get("/{dataset_id}/questions", response_model=list[QuestionResponse])
async def list_dataset_questions(
    dataset_id: int, session: AsyncSession = Depends(get_session)
) -> list[QuestionResponse]:
    questions = await QuestionRepository(session).list(dataset_id=dataset_id)
    if not questions:
        # An empty dataset and a nonexistent dataset both return [] from the
        # filter above; only reject the latter explicitly.
        if await DatasetRepository(session).get(dataset_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        return []

    return [
        QuestionResponse(
            id=q.id,
            dataset_id=q.dataset_id,
            type=q.type,
            text=q.text,
            has_retrieval_context=q.retrieval_context is not None,
            expected_output=q.expected_output,
        )
        for q in questions
    ]
