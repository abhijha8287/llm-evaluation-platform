"""RunOrchestrator: verifies the wiring between LLMRunner, EvaluationService,
and cost_service produces the right Response/EvaluationResult rows — and
that D3/D9's failure isolation holds at the orchestration level too (one
failed provider call for one model must not stop the other models or the
other questions in the same Run)."""

from unittest.mock import AsyncMock

from sqlalchemy import select

from app.evaluation.scoring_service import EvaluationService, MetricScore
from app.llm.runner import LLMRunner, RunResult
from app.models.dataset import Dataset, DatasetVersion, DatasetVersionQuestion
from app.models.evaluation_result import EvaluationResult, EvaluationStatus, MetricName
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.services.run_orchestrator import RunOrchestrator


async def _seed_run_fixture(session):
    user = User(email="orch@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(owner_id=user.id, name="P")
    session.add(project)
    await session.flush()
    dataset = Dataset(project_id=project.id, name="D")
    session.add(dataset)
    await session.flush()

    q1 = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Q1")
    q2 = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Q2")
    session.add_all([q1, q2])
    await session.flush()

    dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=2)
    session.add(dataset_version)
    await session.flush()
    session.add_all(
        [
            DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=q1.id),
            DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=q2.id),
        ]
    )

    model_a = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
    model_b = LLMModel(provider="anthropic", name="claude-3-5-sonnet-20241022", display_name="Claude Sonnet")
    session.add_all([model_a, model_b])
    await session.flush()

    run = Run(project_id=project.id, dataset_version_id=dataset_version.id, status=RunStatus.PENDING)
    session.add(run)
    await session.flush()

    await session.commit()
    return run, [model_a, model_b], [q1, q2]


def _fake_runner(result_for_model: dict[str, RunResult]) -> LLMRunner:
    runner = LLMRunner()
    runner.run = AsyncMock(side_effect=lambda provider_model, prompt: result_for_model[provider_model])
    return runner


def _fake_evaluator(scores: list[MetricScore]) -> EvaluationService:
    evaluator = EvaluationService.__new__(EvaluationService)
    evaluator.judge_model_name = "gpt-4o-mini"
    evaluator.score_response = AsyncMock(return_value=scores)
    return evaluator


async def test_execute_persists_responses_and_evaluation_results_for_every_pair(db_session):
    run, models, questions = await _seed_run_fixture(db_session)

    runner = _fake_runner(
        {
            "gpt-4o-mini": RunResult(
                status=ResponseStatus.SUCCESS, output="answer-a", latency_ms=100, prompt_tokens=10, completion_tokens=5
            ),
            "claude-3-5-sonnet-20241022": RunResult(
                status=ResponseStatus.SUCCESS, output="answer-b", latency_ms=120, prompt_tokens=12, completion_tokens=6
            ),
        }
    )
    evaluator = _fake_evaluator(
        [MetricScore(metric_name=MetricName.TOXICITY, status=EvaluationStatus.SUCCESS, score=0.05, reason="fine")]
    )

    orchestrator = RunOrchestrator(db_session, runner, evaluator)
    await orchestrator.execute(run, models)
    await db_session.commit()

    responses = (await db_session.execute(select(Response).where(Response.run_id == run.id))).scalars().all()
    # 2 questions x 2 models = 4 responses
    assert len(responses) == 4
    assert all(r.status == ResponseStatus.SUCCESS for r in responses)

    eval_results = (
        (await db_session.execute(select(EvaluationResult))).scalars().all()
    )
    assert len(eval_results) == 4  # one TOXICITY result per successful response

    refreshed_run = await db_session.get(Run, run.id)
    assert refreshed_run.status == RunStatus.COMPLETED
    assert refreshed_run.completed_at is not None


async def test_execute_isolates_one_model_failure_from_the_rest(db_session):
    """eng-review D3 at the orchestration level: model A failing for a
    question must not stop model B's response for the same question, or any
    response for the other question."""
    run, models, questions = await _seed_run_fixture(db_session)

    runner = _fake_runner(
        {
            "gpt-4o-mini": RunResult(status=ResponseStatus.FAILED, error_message="rate limited"),
            "claude-3-5-sonnet-20241022": RunResult(
                status=ResponseStatus.SUCCESS, output="answer-b", latency_ms=120, prompt_tokens=12, completion_tokens=6
            ),
        }
    )
    evaluator = _fake_evaluator(
        [MetricScore(metric_name=MetricName.TOXICITY, status=EvaluationStatus.SUCCESS, score=0.05)]
    )

    orchestrator = RunOrchestrator(db_session, runner, evaluator)
    await orchestrator.execute(run, models)
    await db_session.commit()

    responses = (await db_session.execute(select(Response).where(Response.run_id == run.id))).scalars().all()
    assert len(responses) == 4
    failed = [r for r in responses if r.status == ResponseStatus.FAILED]
    succeeded = [r for r in responses if r.status == ResponseStatus.SUCCESS]
    assert len(failed) == 2  # gpt-4o-mini failed for both questions
    assert len(succeeded) == 2  # claude succeeded for both questions

    # No EvaluationResult should exist for the failed responses (D9: never
    # scored — a failed provider call has no output to evaluate).
    eval_results = (await db_session.execute(select(EvaluationResult))).scalars().all()
    assert len(eval_results) == 2

    refreshed_run = await db_session.get(Run, run.id)
    assert refreshed_run.status == RunStatus.COMPLETED
