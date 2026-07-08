import random
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion, DatasetVersionQuestion
from app.models.question import Question


def sample_question_ids(question_ids: list[int], sample_size: int, seed: int) -> list[int]:
    """eng-review D5: deterministic — the same (question_ids, sample_size,
    seed) always produces the same sample, so every provider scored against
    a given DatasetVersion is scored on the identical question set. Pure
    function, no DB access, so it's trivially testable in isolation."""
    rng = random.Random(seed)
    # Sort first: set/query ordering from Postgres is not guaranteed stable
    # across calls, and random.Random.sample's output depends on input order.
    pool = sorted(question_ids)
    if sample_size >= len(pool):
        return pool
    return sorted(rng.sample(pool, sample_size))


class DatasetVersionService:
    """Creates a new, immutable DatasetVersion — a seeded sample materialized
    into DatasetVersionQuestion rows (not recomputed from the seed at read
    time), so the sample stays stable even if sampling logic changes later."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_version(
        self, dataset_id: int, sample_size: int, seed: int | None = None
    ) -> DatasetVersion:
        if seed is None:
            seed = secrets.randbelow(2**31)

        question_ids_result = await self.session.execute(
            select(Question.id).where(Question.dataset_id == dataset_id)
        )
        question_ids = [row[0] for row in question_ids_result]

        next_version_result = await self.session.execute(
            select(func.max(DatasetVersion.version_number)).where(
                DatasetVersion.dataset_id == dataset_id
            )
        )
        current_max = next_version_result.scalar_one_or_none() or 0

        sampled_ids = sample_question_ids(question_ids, sample_size, seed)

        version = DatasetVersion(
            dataset_id=dataset_id,
            version_number=current_max + 1,
            sample_seed=seed,
            sample_size=len(sampled_ids),
        )
        self.session.add(version)
        await self.session.flush()

        self.session.add_all(
            [
                DatasetVersionQuestion(dataset_version_id=version.id, question_id=qid)
                for qid in sampled_ids
            ]
        )
        await self.session.flush()
        return version
