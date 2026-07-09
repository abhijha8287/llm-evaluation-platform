from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.scoring_service import EvaluationService
from app.llm.runner import LLMRunner
from app.models.dataset import DatasetVersionQuestion
from app.models.evaluation_result import EvaluationResult
from app.models.llm_model import LLMModel
from app.models.question import Question
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus
from app.services.cost_service import compute_cost_usd


class RunOrchestrator:
    """Phase 4: synchronous execution — for each (question, provider) pair in
    the Run's DatasetVersion sample, call the model, persist the Response,
    and (on success) score it via the shared EvaluationService (D8).

    Deliberately structured as one unit of work per (question, model) pair
    already, not a single big loop over everything — eng-review D12 moves
    this exact unit into a Celery task in Phase 5 without changing the core
    logic, so that move is mechanical rather than a rewrite.

    Flushes but does not commit — the caller owns the transaction boundary,
    same convention as app/api/routes/runs.py."""

    def __init__(
        self, session: AsyncSession, llm_runner: LLMRunner, evaluation_service: EvaluationService
    ):
        self.session = session
        self.llm_runner = llm_runner
        self.evaluation_service = evaluation_service

    async def execute(self, run: Run, models: list[LLMModel]) -> None:
        questions = await self._load_sampled_questions(run.dataset_version_id)

        for question in questions:
            for model in models:
                await self._run_one_pair(run, question, model)

        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def _run_one_pair(self, run: Run, question: Question, model: LLMModel) -> None:
        result = await self.llm_runner.run(provider_model=model.name, prompt=question.text)
        cost_usd = compute_cost_usd(model.name, result.prompt_tokens, result.completion_tokens)

        response = Response(
            run_id=run.id,
            question_id=question.id,
            model_id=model.id,
            status=result.status,
            output=result.output,
            error_message=result.error_message,
            latency_ms=result.latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=cost_usd,
        )
        self.session.add(response)
        await self.session.flush()

        if result.status != ResponseStatus.SUCCESS:
            return

        scores = await self.evaluation_service.score_response(question, result.output)
        for score in scores:
            self.session.add(
                EvaluationResult(
                    response_id=response.id,
                    metric_name=score.metric_name,
                    status=score.status,
                    score=score.score,
                    reason=score.reason,
                    error_message=score.error_message,
                    judge_model=self.evaluation_service.judge_model_name,
                )
            )
        await self.session.flush()

    async def _load_sampled_questions(self, dataset_version_id: int) -> list[Question]:
        stmt = (
            select(Question)
            .join(DatasetVersionQuestion, DatasetVersionQuestion.question_id == Question.id)
            .where(DatasetVersionQuestion.dataset_version_id == dataset_version_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
