from sqlalchemy import func, select

from app.models.prompt import PromptTemplate, PromptVersion
from app.repositories.base import BaseRepository


class PromptTemplateRepository(BaseRepository[PromptTemplate]):
    model = PromptTemplate


class PromptVersionRepository(BaseRepository[PromptVersion]):
    model = PromptVersion

    async def list_for_template(self, prompt_template_id: int) -> list[PromptVersion]:
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.prompt_template_id == prompt_template_id)
            .order_by(PromptVersion.version_number)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def next_version_number(self, prompt_template_id: int) -> int:
        stmt = select(func.max(PromptVersion.version_number)).where(
            PromptVersion.prompt_template_id == prompt_template_id
        )
        current_max = (await self.session.execute(stmt)).scalar_one_or_none() or 0
        return current_max + 1
