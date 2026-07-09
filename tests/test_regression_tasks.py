"""Regression Celery dispatch: one task per question (not per question x
model — a RegressionRun tests exactly one model/prompt-version pair), plus
an integration check that the fresh-engine-per-task pattern correctly
renders the prompt template and persists results."""

from unittest.mock import MagicMock, patch

from sqlalchemy import select

from app.core.config import get_settings
from app.models.dataset import Dataset, DatasetVersion, DatasetVersionQuestion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.prompt import PromptTemplate, PromptVersion
from app.models.question import Question, QuestionType
from app.models.regression import RegressionResult, RegressionRun, RegressionStatus
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.workers import eval_tasks
from tests.conftest import make_fake_evaluation_service, make_fake_llm_runner


def test_dispatch_regression_run_creates_one_task_per_question():
    with patch.object(eval_tasks, "chord") as mock_chord, patch.object(
        eval_tasks.regression_pair_task, "s"
    ) as mock_pair_sig, patch.object(eval_tasks.mark_regression_completed_task, "s") as mock_callback_sig:
        mock_chord.return_value = MagicMock()

        eval_tasks.dispatch_regression_run(regression_run_id=7, question_ids=[1, 2, 3])

        assert mock_pair_sig.call_count == 3
        assert [c.args for c in mock_pair_sig.call_args_list] == [(7, 1), (7, 2), (7, 3)]
        mock_callback_sig.assert_called_once_with(7)
        mock_chord.assert_called_once()


async def _seed_regression_fixture(session_factory) -> tuple[int, int, int]:
    """Returns (regression_run_id, question_id, expected_rendered_prompt)."""
    async with session_factory() as session:
        user = User(email="regr-task@example.com", hashed_password="x")
        session.add(user)
        await session.flush()
        project = Project(owner_id=user.id, name="P")
        session.add(project)
        await session.flush()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        question = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="What is 2+2?")
        session.add(question)
        await session.flush()
        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
        session.add(dataset_version)
        await session.flush()
        session.add(DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=question.id))
        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()
        template = PromptTemplate(project_id=project.id, name="T")
        session.add(template)
        await session.flush()
        prompt_version = PromptVersion(
            prompt_template_id=template.id, version_number=1, content="Answer tersely: {question}"
        )
        session.add(prompt_version)
        await session.flush()

        run = Run(project_id=project.id, dataset_version_id=dataset_version.id, status=RunStatus.RUNNING)
        session.add(run)
        await session.flush()
        regression_run = RegressionRun(
            prompt_version_id=prompt_version.id,
            dataset_version_id=dataset_version.id,
            model_id=model.id,
            run_id=run.id,
            status=RegressionStatus.RUNNING,
        )
        session.add(regression_run)
        await session.flush()
        await session.commit()
        return regression_run.id, question.id, "Answer tersely: What is 2+2?"


async def test_regression_pair_async_renders_prompt_and_persists_response(
    session_factory, async_engine, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", str(async_engine.url))
    get_settings.cache_clear()

    regression_run_id, question_id, expected_prompt = await _seed_regression_fixture(session_factory)

    fake_runner = make_fake_llm_runner(default_output="4")
    fake_evaluator = make_fake_evaluation_service()

    with patch.object(eval_tasks, "LLMRunner", return_value=fake_runner), patch.object(
        eval_tasks, "EvaluationService", return_value=fake_evaluator
    ):
        await eval_tasks._regression_pair_async(regression_run_id, question_id)

    fake_runner.run.assert_awaited_once()
    assert fake_runner.run.call_args.kwargs["prompt"] == expected_prompt

    async with session_factory() as session:
        regression_run = await session.get(RegressionRun, regression_run_id)
        responses = (
            (await session.execute(select(Response).where(Response.run_id == regression_run.run_id)))
            .scalars()
            .all()
        )
        assert len(responses) == 1
        assert responses[0].output == "4"

    get_settings.cache_clear()


async def test_mark_regression_completed_marks_run_and_computes_results(
    session_factory, async_engine, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", str(async_engine.url))
    get_settings.cache_clear()

    regression_run_id, question_id, _expected_prompt = await _seed_regression_fixture(session_factory)

    # Simulate the pair task having already run and produced a scored Response.
    async with session_factory() as session:
        regression_run = await session.get(RegressionRun, regression_run_id)
        from app.models.evaluation_result import EvaluationResult, EvaluationStatus, MetricName

        response = Response(
            run_id=regression_run.run_id, question_id=question_id, model_id=regression_run.model_id,
            status=ResponseStatus.SUCCESS, output="4",
        )
        session.add(response)
        await session.flush()
        session.add(
            EvaluationResult(
                response_id=response.id, metric_name=MetricName.TOXICITY, status=EvaluationStatus.SUCCESS,
                score=0.1, judge_model="gpt-4o-mini",
            )
        )
        await session.commit()

    await eval_tasks._mark_regression_completed_async(regression_run_id)

    async with session_factory() as session:
        run = await session.get(Run, regression_run.run_id)
        assert run.status == RunStatus.COMPLETED

        refreshed = await session.get(RegressionRun, regression_run_id)
        assert refreshed.status == RegressionStatus.COMPLETED

        results = (
            (await session.execute(select(RegressionResult).where(RegressionResult.regression_run_id == regression_run_id)))
            .scalars()
            .all()
        )
        assert len(results) == 1
        assert results[0].score == 0.1
        assert results[0].delta_from_baseline is None  # no baseline requested

    get_settings.cache_clear()
