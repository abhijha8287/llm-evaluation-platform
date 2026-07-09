"""D10/Phase 4: seeding is idempotent (safe on every app startup) and
produces a usable demo — models with real LiteLLM-format names, and a
dataset with both question types sampled into one version."""

from sqlalchemy import select

from app.core.seed_data import DEMO_USER_EMAIL, seed_all_demo_data
from app.models.dataset import DatasetVersion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.question import QuestionType
from app.models.user import User


async def test_seed_all_demo_data_is_idempotent(db_session):
    await seed_all_demo_data(db_session, demo_password="pw")
    await seed_all_demo_data(db_session, demo_password="pw")

    users = (await db_session.execute(select(User).where(User.email == DEMO_USER_EMAIL))).scalars().all()
    assert len(users) == 1

    models = (await db_session.execute(select(LLMModel))).scalars().all()
    assert len(models) == 3  # DEMO_MODELS has 3 entries, not 6 after two runs


async def test_seed_creates_dataset_version_with_both_question_types(db_session):
    await seed_all_demo_data(db_session, demo_password="pw")

    user = (await db_session.execute(select(User).where(User.email == DEMO_USER_EMAIL))).scalar_one()
    project = (await db_session.execute(select(Project).where(Project.owner_id == user.id))).scalar_one()
    version = (
        (await db_session.execute(select(DatasetVersion).where(DatasetVersion.dataset_id.in_(
            select(DatasetVersion.dataset_id)
        ))))
    ).scalars().first()
    assert version is not None

    from app.models.dataset import DatasetVersionQuestion
    from app.models.question import Question

    sampled_types = (
        await db_session.execute(
            select(Question.type)
            .join(DatasetVersionQuestion, DatasetVersionQuestion.question_id == Question.id)
            .where(DatasetVersionQuestion.dataset_version_id == version.id)
        )
    ).scalars().all()

    assert QuestionType.OPEN_DOMAIN in sampled_types
    assert QuestionType.RAG in sampled_types


async def test_seed_uses_real_litellm_format_model_names(db_session):
    """Sanity check against Phase 2's runner and Phase 4's cost service:
    model.name must be a string LiteLLM can actually resolve pricing for,
    not a placeholder."""
    import litellm

    await seed_all_demo_data(db_session, demo_password="pw")
    models = (await db_session.execute(select(LLMModel))).scalars().all()

    for model in models:
        try:
            litellm.cost_per_token(model=model.name, prompt_tokens=10, completion_tokens=10)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"{model.name} is not a resolvable LiteLLM model string: {exc}")
