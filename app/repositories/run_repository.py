from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.run import Run
from app.repositories.base import BaseRepository


class RunRepository(BaseRepository[Run]):
    model = Run

    async def count_since(self, project_id: int, since: datetime) -> int:
        """eng-review D2: rate limit is enforced server-side, independent of
        who's asking — see app.core.deps.enforce_run_rate_limit."""
        stmt = select(func.count()).select_from(Run).where(
            Run.project_id == project_id, Run.created_at >= since
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_last_24h(self, project_id: int) -> int:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        return await self.count_since(project_id, since)
