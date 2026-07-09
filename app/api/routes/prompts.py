from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.core.deps import get_current_user
from app.models.project import Project
from app.models.prompt import PromptTemplate
from app.models.user import User
from app.repositories.prompt_repository import PromptVersionRepository
from app.services.prompt_service import PromptService, PromptTemplateContentError

# Creating a template/version costs nothing (no LLM call) — auth required
# for write actions (consistent with D10's "logged-in demo user" model) but
# no rate limit, unlike POST /runs and POST /regression-runs.
router = APIRouter(prefix="/prompt-templates", tags=["prompts"])


class CreateTemplateRequest(BaseModel):
    project_id: int
    name: str


class PromptTemplateResponse(BaseModel):
    id: int
    project_id: int
    name: str

    model_config = {"from_attributes": True}


class CreateVersionRequest(BaseModel):
    content: str


class PromptVersionResponse(BaseModel):
    id: int
    prompt_template_id: int
    version_number: int
    content: str

    model_config = {"from_attributes": True}


class PromptTemplateDetailResponse(PromptTemplateResponse):
    versions: list[PromptVersionResponse]


@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: CreateTemplateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    project = await session.get(Project, body.project_id)
    if project is None or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    template = await PromptService(session).create_template(body.project_id, body.name)
    await session.commit()
    return template


@router.get("", response_model=list[PromptTemplateDetailResponse])
async def list_templates(project_id: int, session: AsyncSession = Depends(get_session)):
    """Public, no-auth (D2) — backs the Prompt Testing dashboard page."""
    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.project_id == project_id)
        .options(selectinload(PromptTemplate.versions))
        .order_by(PromptTemplate.created_at)
    )
    templates = (await session.execute(stmt)).scalars().all()
    return list(templates)


@router.post(
    "/{prompt_template_id}/versions", response_model=PromptVersionResponse, status_code=status.HTTP_201_CREATED
)
async def create_version(
    prompt_template_id: int,
    body: CreateVersionRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    template = await session.get(PromptTemplate, prompt_template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")
    project = await session.get(Project, template.project_id)
    if project is None or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")

    try:
        version = await PromptService(session).create_version(prompt_template_id, body.content)
    except PromptTemplateContentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return version


@router.get("/{prompt_template_id}/versions", response_model=list[PromptVersionResponse])
async def list_versions(prompt_template_id: int, session: AsyncSession = Depends(get_session)):
    return await PromptVersionRepository(session).list_for_template(prompt_template_id)
