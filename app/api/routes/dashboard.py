from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.evaluation_result import EvaluationResult, EvaluationStatus
from app.models.llm_model import LLMModel
from app.models.regression import RegressionRun
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus

# eng-review D2: read-only public access. One point per (run, model) pair —
# same shape leaderboard.py uses per model, just not collapsed across runs —
# so the dashboard's Latency Trend / Cost Analysis / Pass Rate / Faithfulness
# Trend charts are all one line chart over this list, filtered/keyed by
# whichever metric_averages entry or field the chart needs. Regression-run
# responses are excluded for the same reason they're excluded from the
# leaderboard (see leaderboard.py) — a prompt-engineering test run is not a
# "how did this model do over time" data point.
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class RunTrendPoint(BaseModel):
    run_id: int
    created_at: datetime
    model_id: int
    display_name: str
    avg_latency_ms: float | None
    avg_cost_usd: float | None
    pass_rate: float | None
    metric_averages: dict[str, float]


@router.get("/trends", response_model=list[RunTrendPoint])
async def get_trends(project_id: int, session: AsyncSession = Depends(get_session)) -> list[RunTrendPoint]:
    regression_run_ids = select(RegressionRun.run_id)
    runs = (
        (
            await session.execute(
                select(Run)
                .where(
                    Run.project_id == project_id,
                    Run.status == RunStatus.COMPLETED,
                    Run.id.not_in(regression_run_ids),
                )
                .order_by(Run.created_at)
            )
        )
        .scalars()
        .all()
    )

    points: list[RunTrendPoint] = []
    for run in runs:
        model_ids = (
            (
                await session.execute(
                    select(Response.model_id).where(Response.run_id == run.id).distinct()
                )
            )
            .scalars()
            .all()
        )

        for model_id in model_ids:
            model = await session.get(LLMModel, model_id)

            agg_stmt = select(
                func.avg(Response.latency_ms), func.avg(Response.cost_usd)
            ).where(
                Response.run_id == run.id,
                Response.model_id == model_id,
                Response.status == ResponseStatus.SUCCESS,
            )
            avg_latency, avg_cost = (await session.execute(agg_stmt)).one()

            metric_stmt = (
                select(EvaluationResult.metric_name, func.avg(EvaluationResult.score))
                .join(Response, Response.id == EvaluationResult.response_id)
                .where(
                    Response.run_id == run.id,
                    Response.model_id == model_id,
                    EvaluationResult.status == EvaluationStatus.SUCCESS,
                )
                .group_by(EvaluationResult.metric_name)
            )
            metric_rows = (await session.execute(metric_stmt)).all()

            # passed is only meaningful on SUCCESS evaluation results (see
            # evaluation_result.py) — a failed judge call has no verdict, so
            # it's excluded from the pass-rate denominator, not counted as 0.
            pass_stmt = select(
                func.count(EvaluationResult.id),
                func.sum(case((EvaluationResult.passed.is_(True), 1), else_=0)),
            ).join(Response, Response.id == EvaluationResult.response_id).where(
                Response.run_id == run.id,
                Response.model_id == model_id,
                EvaluationResult.status == EvaluationStatus.SUCCESS,
            )
            total, passed_count = (await session.execute(pass_stmt)).one()

            points.append(
                RunTrendPoint(
                    run_id=run.id,
                    created_at=run.created_at,
                    model_id=model_id,
                    display_name=model.display_name,
                    avg_latency_ms=float(avg_latency) if avg_latency is not None else None,
                    avg_cost_usd=float(avg_cost) if avg_cost is not None else None,
                    pass_rate=(passed_count / total) if total else None,
                    metric_averages={name.value: float(avg) for name, avg in metric_rows},
                )
            )

    return points
