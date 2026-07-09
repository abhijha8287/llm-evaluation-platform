import pytest

from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.user import User
from app.services.prompt_service import PromptService, PromptTemplateContentError, render_prompt


async def _seed_project(session) -> int:
    user = User(email="prompt@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(owner_id=user.id, name="P")
    session.add(project)
    await session.flush()
    await session.commit()
    return project.id


async def test_create_version_rejects_content_missing_question_placeholder(db_session):
    project_id = await _seed_project(db_session)
    service = PromptService(db_session)
    template = await service.create_template(project_id, "Support agent")
    await db_session.commit()

    with pytest.raises(PromptTemplateContentError):
        await service.create_version(template.id, "You are a helpful assistant with no placeholder.")


async def test_create_version_accepts_content_with_placeholder(db_session):
    project_id = await _seed_project(db_session)
    service = PromptService(db_session)
    template = await service.create_template(project_id, "Support agent")
    await db_session.commit()

    version = await service.create_version(template.id, "Answer concisely: {question}")
    await db_session.commit()

    assert version.version_number == 1
    assert version.prompt_template_id == template.id


async def test_create_version_auto_increments_version_number(db_session):
    project_id = await _seed_project(db_session)
    service = PromptService(db_session)
    template = await service.create_template(project_id, "Support agent")
    await db_session.commit()

    v1 = await service.create_version(template.id, "V1: {question}")
    await db_session.commit()
    v2 = await service.create_version(template.id, "V2: {question}")
    await db_session.commit()

    assert v1.version_number == 1
    assert v2.version_number == 2


async def test_render_prompt_substitutes_question_text(db_session):
    project_id = await _seed_project(db_session)
    service = PromptService(db_session)
    template = await service.create_template(project_id, "Support agent")
    await db_session.commit()
    version = await service.create_version(
        template.id, "You are a helpful assistant. Question: {question}\nAnswer:"
    )
    await db_session.commit()

    question = Question(dataset_id=1, type=QuestionType.OPEN_DOMAIN, text="What is 2+2?")

    rendered = render_prompt(version, question)

    assert rendered == "You are a helpful assistant. Question: What is 2+2?\nAnswer:"
