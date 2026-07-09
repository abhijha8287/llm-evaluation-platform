from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.comparison import Comparison, VoterType
from app.models.evaluation_result import EvaluationResult, EvaluationStatus
from app.models.llm_model import LLMModel
from app.models.regression import RegressionRun
from app.models.response import Response, ResponseStatus
from app.services.leaderboard_cache import get_cached_leaderboard, set_cached_leaderboard

# eng-review D2: read-only, no auth required — this is what a recruiter sees
# when they open the demo URL with no login.
router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


class LeaderboardEntry(BaseModel):
    model_id: int
    display_name: str
    provider: str
    # office-hours design doc Phase 6: LLM-judged and human-judged Elo are
    # shown separately, not blended — see app/models/llm_model.py.
    elo_rating_llm_judge: float
    elo_rating_human: float
    llm_judge_comparison_count: int
    human_comparison_count: int
    response_count: int
    avg_latency_ms: float | None
    avg_cost_usd: float | None
    metric_averages: dict[str, float]


async def _count_comparisons(session: AsyncSession, model_id: int, voter_type: VoterType) -> int:
    stmt = select(func.count(Comparison.id)).where(
        or_(Comparison.model_a_id == model_id, Comparison.model_b_id == model_id),
        Comparison.voter_type == voter_type,
    )
    return (await session.execute(stmt)).scalar_one()


async def _compute_leaderboard(session: AsyncSession) -> list[LeaderboardEntry]:
    models = list((await session.execute(select(LLMModel))).scalars().all())

    # Phase 7: regression runs reuse the real Run/Response/EvaluationResult
    # pipeline (D8) wholesale — including intentionally-varied prompts that
    # would otherwise pollute "how good is this model, normally" stats with
    # prompt-engineering-test noise. Exclude any Response whose run_id is a
    # regression run's underlying run.
    regression_run_ids = select(RegressionRun.run_id)

    entries: list[LeaderboardEntry] = []
    for model in models:
        # eng-review D3: only SUCCESS responses count toward averages — a
        # timed-out or failed provider call must never read as a 0.
        agg_stmt = select(
            func.count(Response.id),
            func.avg(Response.latency_ms),
            func.avg(Response.cost_usd),
        ).where(
            Response.model_id == model.id,
            Response.status == ResponseStatus.SUCCESS,
            Response.run_id.not_in(regression_run_ids),
        )
        count, avg_latency, avg_cost = (await session.execute(agg_stmt)).one()

        # eng-review D9: only SUCCESS-status EvaluationResults count — a
        # failed judge call must never read as a real 0 score.
        metric_stmt = (
            select(EvaluationResult.metric_name, func.avg(EvaluationResult.score))
            .join(Response, Response.id == EvaluationResult.response_id)
            .where(
                Response.model_id == model.id,
                EvaluationResult.status == EvaluationStatus.SUCCESS,
                Response.run_id.not_in(regression_run_ids),
            )
            .group_by(EvaluationResult.metric_name)
        )
        metric_rows = (await session.execute(metric_stmt)).all()

        llm_judge_count = await _count_comparisons(session, model.id, VoterType.LLM_JUDGE)
        human_count = await _count_comparisons(session, model.id, VoterType.HUMAN)

        entries.append(
            LeaderboardEntry(
                model_id=model.id,
                display_name=model.display_name,
                provider=model.provider,
                elo_rating_llm_judge=model.elo_rating_llm_judge,
                elo_rating_human=model.elo_rating_human,
                llm_judge_comparison_count=llm_judge_count,
                human_comparison_count=human_count,
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


@router.get("", response_model=list[LeaderboardEntry])
async def get_leaderboard(session: AsyncSession = Depends(get_session)) -> list[LeaderboardEntry]:
    cached = await get_cached_leaderboard()
    if cached is not None:
        return [LeaderboardEntry(**entry) for entry in cached]

    entries = await _compute_leaderboard(session)
    await set_cached_leaderboard([entry.model_dump() for entry in entries])
    return entries
