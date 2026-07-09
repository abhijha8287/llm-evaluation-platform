from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.evaluation_result import EvaluationResult, EvaluationStatus
from app.models.llm_model import LLMModel
from app.models.response import Response, ResponseStatus

# eng-review D2: read-only, no auth required — this is what a recruiter sees
# when they open the demo URL with no login.
router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


class LeaderboardEntry(BaseModel):
    model_id: int
    display_name: str
    provider: str
    elo_rating: float
    response_count: int
    avg_latency_ms: float | None
    avg_cost_usd: float | None
    metric_averages: dict[str, float]


@router.get("", response_model=list[LeaderboardEntry])
async def get_leaderboard(session: AsyncSession = Depends(get_session)) -> list[LeaderboardEntry]:
    models = list((await session.execute(select(LLMModel))).scalars().all())

    entries: list[LeaderboardEntry] = []
    for model in models:
        # eng-review D3: only SUCCESS responses count toward averages — a
        # timed-out or failed provider call must never read as a 0.
        agg_stmt = select(
            func.count(Response.id),
            func.avg(Response.latency_ms),
            func.avg(Response.cost_usd),
        ).where(Response.model_id == model.id, Response.status == ResponseStatus.SUCCESS)
        count, avg_latency, avg_cost = (await session.execute(agg_stmt)).one()

        # eng-review D9: only SUCCESS-status EvaluationResults count — a
        # failed judge call must never read as a real 0 score.
        metric_stmt = (
            select(EvaluationResult.metric_name, func.avg(EvaluationResult.score))
            .join(Response, Response.id == EvaluationResult.response_id)
            .where(Response.model_id == model.id, EvaluationResult.status == EvaluationStatus.SUCCESS)
            .group_by(EvaluationResult.metric_name)
        )
        metric_rows = (await session.execute(metric_stmt)).all()

        entries.append(
            LeaderboardEntry(
                model_id=model.id,
                display_name=model.display_name,
                provider=model.provider,
                elo_rating=model.elo_rating,
                response_count=count,
                avg_latency_ms=float(avg_latency) if avg_latency is not None else None,
                avg_cost_usd=float(avg_cost) if avg_cost is not None else None,
                # .value, not str() — str(MetricName.TOXICITY) is
                # "MetricName.TOXICITY" (standard str+Enum __str__
                # behavior), not the "toxicity" value; caught by the
                # metric-averages test.
                metric_averages={name.value: float(avg) for name, avg in metric_rows},
            )
        )

    return entries
