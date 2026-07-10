from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.scoring_service import EvaluationService
from app.llm.runner import LLMRunner
from app.models.evaluation_result import EvaluationResult
from app.models.llm_model import LLMModel
from app.models.question import Question
from app.models.response import Response, ResponseStatus
from app.models.run import Run
from app.monitoring.metrics import RESPONSE_COST_USD_TOTAL
from app.repositories.question_repository import QuestionRepository
from app.repositories.run_repository import RunRepository
from app.services.cost_service import compute_cost_usd


class RunOrchestrator:
    """Phase 4 gave this a synchronous `execute()` — run every (question,
    model) pair in-process, in one HTTP request. Phase 5 (eng-review D1/D12)
    dispatches each pair as its own Celery task instead (see
    app/workers/eval_tasks.py), calling the same `run_pair()` this class
    always used internally — that method was deliberately public-shaped
    (single-pair, self-contained, flush-not-commit) from Phase 4 onward so
    this move required no rewrite, just a new caller.

    `execute()` is kept: it's still what the test suite uses to exercise the
    full orchestration logic without needing a live Celery worker, and it
    remains a legitimate "run synchronously" path (e.g. for local dev
    without Celery running).

    Only holds what actually needs llm_runner/evaluation_service (i.e.
    run_pair). Loading the question sample and marking a run complete need
    neither dependency, so they live on QuestionRepository/RunRepository
    instead — needing an EvaluationService purely to call a method that
    never touches it would be the same smell already fixed once in this
    file for mark_completed. (EvaluationService's judge-model construction
    is now lazy — TODOS.md item 4 — but the dependency-shape argument for
    keeping this class narrow holds regardless.)

    Flushes but does not commit — the caller owns the transaction boundary."""

    def __init__(
        self, session: AsyncSession, llm_runner: LLMRunner, evaluation_service: EvaluationService
    ):
        self.session = session
        self.llm_runner = llm_runner
        self.evaluation_service = evaluation_service

    async def execute(self, run: Run, models: list[LLMModel]) -> None:
        questions = await QuestionRepository(self.session).list_for_dataset_version(
            run.dataset_version_id
        )

        for question in questions:
            for model in models:
                await self.run_pair(run, question, model)

        await RunRepository(self.session).mark_completed(run)

    async def run_pair(
        self, run: Run, question: Question, model: LLMModel, prompt_override: str | None = None
    ) -> None:
        """prompt_override lets a caller send a different prompt than the
        bare question text — Phase 7's regression engine renders a
        PromptVersion template around the question and passes the result
        here, reusing this exact pipeline (response generation, cost
        tracking, scoring, persistence) rather than duplicating it. The
        Response row still records question_id as normal; what actually
        changed is the text sent to the model, which is Phase 7's whole
        point (test whether a prompt version regresses quality)."""
        prompt = prompt_override if prompt_override is not None else question.text
        result = await self.llm_runner.run(provider_model=model.name, prompt=prompt)
        cost_usd = compute_cost_usd(model.name, result.prompt_tokens, result.completion_tokens)
        # D6: null (model missing from LiteLLM's pricing map) is never
        # counted as 0 — same null-vs-zero discipline as the leaderboard's
        # avg_cost_usd, applied here to the cumulative metric too.
        if cost_usd is not None:
            RESPONSE_COST_USD_TOTAL.labels(model=model.name).inc(cost_usd)

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
                    passed=score.passed,
                    reason=score.reason,
                    error_message=score.error_message,
                    judge_model=self.evaluation_service.judge_model_name,
                )
            )
        await self.session.flush()
