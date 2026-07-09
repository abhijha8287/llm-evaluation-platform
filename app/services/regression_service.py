from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation_result import EvaluationResult, EvaluationStatus
from app.models.prompt import PromptTemplate, PromptVersion
from app.models.regression import RegressionResult, RegressionRun, RegressionStatus
from app.models.response import Response
from app.models.run import Run, RunStatus


class RegressionService:
    """eng-review D7: a RegressionRun pins dataset_version_id at creation.
    Diffing only happens against a baseline RegressionRun that (a) exists,
    (b) completed successfully, and (c) used the SAME dataset_version_id —
    otherwise the run is marked NOT_COMPARABLE and every RegressionResult's
    delta_from_baseline is left null, never a silently-wrong diff.

    Response generation and scoring are not duplicated here — create_run
    creates a real Run that the existing RunOrchestrator/Celery pipeline
    (D8/D12) executes exactly like any other Run. This service only adds
    the run-creation wiring and the post-completion diff step."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(
        self,
        prompt_version_id: int,
        dataset_version_id: int,
        model_id: int,
        baseline_prompt_version_id: int | None,
    ) -> RegressionRun:
        prompt_version = await self.session.get(PromptVersion, prompt_version_id)
        prompt_template = await self.session.get(PromptTemplate, prompt_version.prompt_template_id)

        run = Run(project_id=prompt_template.project_id, dataset_version_id=dataset_version_id, status=RunStatus.RUNNING)
        self.session.add(run)
        await self.session.flush()

        regression_run = RegressionRun(
            prompt_version_id=prompt_version_id,
            baseline_prompt_version_id=baseline_prompt_version_id,
            dataset_version_id=dataset_version_id,
            model_id=model_id,
            run_id=run.id,
            status=RegressionStatus.RUNNING,
        )
        self.session.add(regression_run)
        await self.session.flush()
        return regression_run

    async def _find_baseline_run(self, regression_run: RegressionRun) -> RegressionRun | None:
        """Most recent COMPLETED RegressionRun for the same baseline prompt
        version and the same model — "most recent" is the documented
        resolution rule for the (necessarily) many-runs-per-prompt-version
        case; there is no separate baseline_regression_run_id to disambiguate
        further, by design, since users think in terms of "compare against
        prompt version X," not a specific historical run id."""
        if regression_run.baseline_prompt_version_id is None:
            return None
        stmt = (
            select(RegressionRun)
            .where(
                RegressionRun.prompt_version_id == regression_run.baseline_prompt_version_id,
                RegressionRun.model_id == regression_run.model_id,
                RegressionRun.status == RegressionStatus.COMPLETED,
            )
            .order_by(RegressionRun.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _load_scores(self, run_id: int) -> dict[tuple[int, str], float]:
        stmt = (
            select(Response.question_id, EvaluationResult.metric_name, EvaluationResult.score)
            .join(EvaluationResult, EvaluationResult.response_id == Response.id)
            .where(Response.run_id == run_id, EvaluationResult.status == EvaluationStatus.SUCCESS)
        )
        rows = (await self.session.execute(stmt)).all()
        # .value, not str() — see leaderboard.py's comment; str(MetricName.X)
        # renders as "MetricName.X", not the metric's actual value.
        return {(question_id, metric_name.value): score for question_id, metric_name, score in rows}

    async def compute_results(self, regression_run: RegressionRun) -> None:
        """Called once the underlying Run (regression_run.run_id) has
        completed — see app/workers/eval_tasks.py's regression completion
        callback."""
        has_baseline_request = regression_run.baseline_prompt_version_id is not None
        baseline_run = await self._find_baseline_run(regression_run)
        is_comparable = not has_baseline_request or (
            baseline_run is not None and baseline_run.dataset_version_id == regression_run.dataset_version_id
        )

        baseline_scores = await self._load_scores(baseline_run.run_id) if is_comparable and baseline_run else {}
        current_scores = await self._load_scores(regression_run.run_id)

        for (question_id, metric_name), score in current_scores.items():
            delta = None
            if is_comparable:
                baseline_score = baseline_scores.get((question_id, metric_name))
                if baseline_score is not None:
                    delta = score - baseline_score
            self.session.add(
                RegressionResult(
                    regression_run_id=regression_run.id,
                    question_id=question_id,
                    metric_name=metric_name,
                    score=score,
                    delta_from_baseline=delta,
                )
            )

        regression_run.status = (
            RegressionStatus.COMPLETED if is_comparable else RegressionStatus.NOT_COMPARABLE
        )
        regression_run.completed_at = datetime.now(timezone.utc)
        await self.session.flush()
