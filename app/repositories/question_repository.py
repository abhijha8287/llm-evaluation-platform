from sqlalchemy import select

from app.models.dataset import DatasetVersionQuestion
from app.models.question import Question
from app.repositories.base import BaseRepository


class QuestionRepository(BaseRepository[Question]):
    model = Question

    async def list_for_dataset_version(self, dataset_version_id: int) -> list[Question]:
        stmt = (
            select(Question)
            .join(DatasetVersionQuestion, DatasetVersionQuestion.question_id == Question.id)
            .where(DatasetVersionQuestion.dataset_version_id == dataset_version_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
