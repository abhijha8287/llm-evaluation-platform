from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.dataset import Dataset
from app.repositories.base import BaseRepository


class DatasetRepository(BaseRepository[Dataset]):
    model = Dataset

    async def list_for_project(self, project_id: int) -> list[Dataset]:
        """selectinload, not the default lazy relationship access — async
        SQLAlchemy raises MissingGreenlet on an un-awaited lazy load once the
        session context that produced these rows returns to the route
        handler and Pydantic serialization walks `.versions`."""
        stmt = (
            select(Dataset)
            .where(Dataset.project_id == project_id)
            .options(selectinload(Dataset.versions))
            .order_by(Dataset.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
