"""Task T6 verify: same version/seed -> identical sample across repeated calls."""

from sqlalchemy import select

from app.models.dataset import Dataset, DatasetVersionQuestion
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.user import User
from app.services.dataset_sampler import DatasetVersionService, sample_question_ids


def test_sample_is_deterministic_for_same_seed():
    ids = list(range(1, 101))
    first = sample_question_ids(ids, sample_size=20, seed=42)
    second = sample_question_ids(ids, sample_size=20, seed=42)
    assert first == second
    assert len(first) == 20


def test_sample_differs_for_different_seed():
    ids = list(range(1, 101))
    first = sample_question_ids(ids, sample_size=20, seed=42)
    second = sample_question_ids(ids, sample_size=20, seed=43)
    assert first != second


def test_sample_size_larger_than_pool_returns_entire_pool():
    ids = [1, 2, 3]
    result = sample_question_ids(ids, sample_size=25, seed=1)
    assert result == [1, 2, 3]


def test_sample_is_deterministic_regardless_of_input_order():
    ascending = list(range(1, 51))
    shuffled = list(reversed(ascending))
    assert sample_question_ids(ascending, sample_size=10, seed=7) == sample_question_ids(
        shuffled, sample_size=10, seed=7
    )


async def _seed_dataset_with_questions(session, count: int) -> int:
    user = User(email="sampler@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(owner_id=user.id, name="P")
    session.add(project)
    await session.flush()
    dataset = Dataset(project_id=project.id, name="D")
    session.add(dataset)
    await session.flush()
    session.add_all(
        [
            Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text=f"Q{i}")
            for i in range(count)
        ]
    )
    await session.flush()
    await session.commit()
    return dataset.id


async def test_create_version_materializes_sampled_questions(db_session):
    dataset_id = await _seed_dataset_with_questions(db_session, count=50)

    service = DatasetVersionService(db_session)
    version = await service.create_version(dataset_id=dataset_id, sample_size=10, seed=99)
    await db_session.commit()

    assert version.version_number == 1
    assert version.sample_seed == 99
    assert version.sample_size == 10

    linked = await db_session.execute(
        select(DatasetVersionQuestion).where(DatasetVersionQuestion.dataset_version_id == version.id)
    )
    assert len(linked.scalars().all()) == 10


async def test_create_version_auto_increments_version_number(db_session):
    dataset_id = await _seed_dataset_with_questions(db_session, count=20)

    service = DatasetVersionService(db_session)
    v1 = await service.create_version(dataset_id=dataset_id, sample_size=5, seed=1)
    await db_session.commit()
    v2 = await service.create_version(dataset_id=dataset_id, sample_size=5, seed=2)
    await db_session.commit()

    assert v1.version_number == 1
    assert v2.version_number == 2


async def test_create_version_without_explicit_seed_still_samples_correct_size(db_session):
    dataset_id = await _seed_dataset_with_questions(db_session, count=30)

    service = DatasetVersionService(db_session)
    version = await service.create_version(dataset_id=dataset_id, sample_size=12)
    await db_session.commit()

    assert version.sample_size == 12
    assert isinstance(version.sample_seed, int)
