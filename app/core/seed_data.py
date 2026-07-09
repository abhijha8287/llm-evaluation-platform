from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.dataset import Dataset, DatasetVersion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository

DEMO_USER_EMAIL = "demo@llm-eval-platform.dev"

# Constraints/Open Questions: OpenAI + Anthropic + one free/cheap open-model
# route via Groq, rather than all 6 providers from day one — cost and
# rate-limit surface area scales with provider count x dataset size.
#
# Model names are verified directly against the installed litellm's pricing
# map (litellm.cost_per_token), not assumed — "claude-3-5-haiku-20241022"
# (a natural guess) is NOT resolvable by litellm's provider-detection logic
# even though "claude-3-haiku-20240307" is; only bare names litellm
# explicitly recognizes work without an explicit "anthropic/" prefix.
DEMO_MODELS = [
    ("openai", "gpt-4o-mini", "GPT-4o mini"),
    ("anthropic", "claude-haiku-4-5", "Claude Haiku 4.5"),
    ("groq", "groq/llama-3.3-70b-versatile", "Llama 3.3 70B (Groq)"),
]

DEMO_OPEN_DOMAIN_QUESTIONS = [
    "What is the capital of France?",
    "Explain the difference between TCP and UDP in one paragraph.",
    "What year did the Berlin Wall fall?",
]

DEMO_RAG_QUESTIONS = [
    (
        "According to the policy, how many days do customers have to request a refund?",
        "Our return policy allows customers to request a refund within 30 days of the "
        "original purchase date, provided the item is unused and in its original packaging.",
    ),
    (
        "What is the maximum file size the API accepts for uploads?",
        "The upload endpoint accepts files up to 25 MB. Requests exceeding this limit "
        "receive a 413 Payload Too Large response.",
    ),
]


async def seed_demo_user(session: AsyncSession, password: str) -> User:
    """eng-review D10: the public deploy has exactly one seeded user/project —
    no open self-registration. Idempotent: safe to call on every startup."""
    user_repo = UserRepository(session)
    existing = await user_repo.get_by_email(DEMO_USER_EMAIL)
    if existing is not None:
        return existing

    user = await user_repo.add(User(email=DEMO_USER_EMAIL, hashed_password=hash_password(password)))
    await ProjectRepository(session).add(Project(owner_id=user.id, name="Demo Project"))
    await session.commit()
    return user


async def seed_demo_models(session: AsyncSession) -> list[LLMModel]:
    """Idempotent: skips any (provider, name) pair that already exists."""
    existing = (await session.execute(select(LLMModel))).scalars().all()
    existing_keys = {(m.provider, m.name) for m in existing}

    created = []
    for provider, name, display_name in DEMO_MODELS:
        if (provider, name) in existing_keys:
            continue
        model = LLMModel(provider=provider, name=name, display_name=display_name)
        session.add(model)
        created.append(model)

    if created:
        await session.flush()
        await session.commit()
    return existing + created


async def seed_demo_dataset(session: AsyncSession, project_id: int) -> DatasetVersion:
    """Idempotent: returns the existing demo dataset's latest version if one
    already exists, rather than creating duplicates on every startup."""
    from app.services.dataset_sampler import DatasetVersionService

    existing_dataset = (
        await session.execute(select(Dataset).where(Dataset.project_id == project_id, Dataset.name == "Demo Dataset"))
    ).scalar_one_or_none()
    if existing_dataset is not None:
        latest_version = (
            await session.execute(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == existing_dataset.id)
                .order_by(DatasetVersion.version_number.desc())
            )
        ).scalars().first()
        if latest_version is not None:
            return latest_version

    dataset = existing_dataset
    if dataset is None:
        dataset = Dataset(project_id=project_id, name="Demo Dataset")
        session.add(dataset)
        await session.flush()

        for text in DEMO_OPEN_DOMAIN_QUESTIONS:
            session.add(Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text=text))
        for text, context in DEMO_RAG_QUESTIONS:
            session.add(
                Question(
                    dataset_id=dataset.id, type=QuestionType.RAG, text=text, retrieval_context=context
                )
            )
        await session.flush()

    question_count = len(
        (await session.execute(select(Question.id).where(Question.dataset_id == dataset.id))).all()
    )
    version_service = DatasetVersionService(session)
    version = await version_service.create_version(
        dataset_id=dataset.id, sample_size=question_count, seed=42
    )
    await session.commit()
    return version


async def seed_all_demo_data(session: AsyncSession, demo_password: str) -> None:
    user = await seed_demo_user(session, password=demo_password)
    await seed_demo_models(session)
    project = (await session.execute(select(Project).where(Project.owner_id == user.id))).scalars().first()
    if project is not None:
        await seed_demo_dataset(session, project_id=project.id)
