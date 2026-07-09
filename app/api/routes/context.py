from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import get_current_user
from app.models.dataset import DatasetVersion, Dataset
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.user import User

# Small, purpose-built endpoint so the frontend never hardcodes IDs: given
# the authenticated user, what project + dataset version should "trigger a
# run" default to, and what models are available to pick from. D10: there's
# exactly one seeded project per user in this phase, so "the" project is
# unambiguous.
router = APIRouter(prefix="/me", tags=["context"])


class ModelOption(BaseModel):
    id: int
    display_name: str
    provider: str

    model_config = {"from_attributes": True}


class RunContext(BaseModel):
    project_id: int
    dataset_version_id: int
    models: list[ModelOption]


@router.get("/run-context", response_model=RunContext)
async def get_run_context(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RunContext:
    project = (
        await session.execute(select(Project).where(Project.owner_id == current_user.id))
    ).scalars().first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project found")

    latest_version = (
        await session.execute(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(Dataset.project_id == project.id)
            .order_by(DatasetVersion.version_number.desc())
        )
    ).scalars().first()
    if latest_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No dataset version found")

    models = list((await session.execute(select(LLMModel))).scalars().all())

    return RunContext(
        project_id=project.id,
        dataset_version_id=latest_version.id,
        models=[ModelOption.model_validate(m) for m in models],
    )
