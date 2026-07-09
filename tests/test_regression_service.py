"""Task T10 verify: same-version diff test + mismatched-version rejection test."""

import pytest
from sqlalchemy import select

from app.models.dataset import Dataset, DatasetVersion
from app.models.evaluation_result import EvaluationResult, EvaluationStatus, MetricName
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.prompt import PromptTemplate, PromptVersion
from app.models.question import Question, QuestionType
from app.models.regression import RegressionResult, RegressionRun, RegressionStatus
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.services.regression_service import RegressionService


async def _seed_base(session):
    """Returns (project_id, dataset_id, dataset_version_id, question_id, model_id, template_id)."""
    user = User(email="regr@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(owner_id=user.id, name="P")
    session.add(project)
    await session.flush()
    dataset = Dataset(project_id=project.id, name="D")
    session.add(dataset)
    await session.flush()
    question = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Q")
    session.add(question)
    await session.flush()
    dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
    session.add(dataset_version)
    await session.flush()
    model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
    session.add(model)
    await session.flush()
    template = PromptTemplate(project_id=project.id, name="Support agent")
    session.add(template)
    await session.flush()
    await session.commit()
    return project.id, dataset.id, dataset_version.id, question.id, model.id, template.id


async def _add_response_and_score(session, run_id, question_id, model_id, score):
    response = Response(
        run_id=run_id, question_id=question_id, model_id=model_id, status=ResponseStatus.SUCCESS, output="x"
    )
    session.add(response)
    await session.flush()
    session.add(
        EvaluationResult(
            response_id=response.id, metric_name=MetricName.TOXICITY, status=EvaluationStatus.SUCCESS,
            score=score, judge_model="gpt-4o-mini",
        )
    )


async def _seed_completed_regression_run(
    session, project_id, prompt_version_id, dataset_version_id, model_id, question_id, score,
    baseline_prompt_version_id=None,
) -> RegressionRun:
    """Seeds a fully-completed regression run with one scored Response, as
    if RegressionService.create_run + the async pipeline + compute_results
    had already run for it — used to build a baseline to diff against."""
    run = Run(project_id=project_id, dataset_version_id=dataset_version_id, status=RunStatus.COMPLETED)
    session.add(run)
    await session.flush()
    await _add_response_and_score(session, run.id, question_id, model_id, score)
    regression_run = RegressionRun(
        prompt_version_id=prompt_version_id,
        baseline_prompt_version_id=baseline_prompt_version_id,
        dataset_version_id=dataset_version_id,
        model_id=model_id,
        run_id=run.id,
        status=RegressionStatus.COMPLETED,
    )
    session.add(regression_run)
    await session.flush()
    await session.commit()
    return regression_run


async def test_create_run_creates_underlying_run_and_links_it(db_session):
    _project_id, _dataset_id, dataset_version_id, _question_id, model_id, template_id = await _seed_base(db_session)
    version = PromptVersion(prompt_template_id=template_id, version_number=1, content="Answer: {question}")
    db_session.add(version)
    await db_session.flush()
    await db_session.commit()

    service = RegressionService(db_session)
    regression_run = await service.create_run(
        version.id, dataset_version_id, model_id, baseline_prompt_version_id=None
    )
    await db_session.commit()

    run = await db_session.get(Run, regression_run.run_id)
    assert run is not None
    assert run.dataset_version_id == dataset_version_id
    assert run.status == RunStatus.RUNNING
    assert regression_run.status == RegressionStatus.RUNNING


async def test_compute_results_with_no_baseline_requested_completes_with_null_deltas(db_session):
    _project_id, _dataset_id, dataset_version_id, question_id, model_id, template_id = await _seed_base(db_session)

    version = PromptVersion(prompt_template_id=template_id, version_number=1, content="Answer: {question}")
    db_session.add(version)
    await db_session.flush()
    await db_session.commit()

    service = RegressionService(db_session)
    regression_run = await service.create_run(
        version.id, dataset_version_id, model_id, baseline_prompt_version_id=None
    )
    await db_session.commit()

    await _add_response_and_score(db_session, regression_run.run_id, question_id, model_id, score=0.8)
    await db_session.commit()

    await service.compute_results(regression_run)
    await db_session.commit()

    assert regression_run.status == RegressionStatus.COMPLETED
    results = (
        await db_session.execute(
            select(RegressionResult).where(RegressionResult.regression_run_id == regression_run.id)
        )
    ).scalars().all()
    assert len(results) == 1
    assert results[0].score == 0.8
    assert results[0].delta_from_baseline is None


async def test_compute_results_same_dataset_version_computes_delta(db_session):
    project_id, _dataset_id, dataset_version_id, question_id, model_id, template_id = await _seed_base(db_session)

    v1 = PromptVersion(prompt_template_id=template_id, version_number=1, content="V1: {question}")
    db_session.add(v1)
    await db_session.flush()
    v2 = PromptVersion(prompt_template_id=template_id, version_number=2, content="V2: {question}")
    db_session.add(v2)
    await db_session.flush()
    await db_session.commit()

    await _seed_completed_regression_run(
        db_session, project_id, v1.id, dataset_version_id, model_id, question_id, score=0.6
    )

    service = RegressionService(db_session)
    current = await service.create_run(v2.id, dataset_version_id, model_id, baseline_prompt_version_id=v1.id)
    await db_session.commit()
    await _add_response_and_score(db_session, current.run_id, question_id, model_id, score=0.9)
    await db_session.commit()

    await service.compute_results(current)
    await db_session.commit()

    assert current.status == RegressionStatus.COMPLETED
    results = (
        await db_session.execute(select(RegressionResult).where(RegressionResult.regression_run_id == current.id))
    ).scalars().all()
    assert len(results) == 1
    assert results[0].score == 0.9
    assert results[0].delta_from_baseline == pytest.approx(0.3)


async def test_compute_results_mismatched_dataset_version_marks_not_comparable(db_session):
    """eng-review D7: the actual claim under test — a baseline from a
    DIFFERENT dataset_version must never be silently diffed against."""
    project_id, dataset_id, dataset_version_id, question_id, model_id, template_id = await _seed_base(db_session)

    # A second, different dataset_version (simulating the dataset having
    # been re-sampled/changed between the baseline run and this one).
    other_dataset_version = DatasetVersion(dataset_id=dataset_id, version_number=2, sample_seed=99, sample_size=1)
    db_session.add(other_dataset_version)
    await db_session.flush()
    await db_session.commit()

    v1 = PromptVersion(prompt_template_id=template_id, version_number=1, content="V1: {question}")
    db_session.add(v1)
    await db_session.flush()
    v2 = PromptVersion(prompt_template_id=template_id, version_number=2, content="V2: {question}")
    db_session.add(v2)
    await db_session.flush()
    await db_session.commit()

    # Baseline ran against the ORIGINAL dataset_version_id.
    await _seed_completed_regression_run(
        db_session, project_id, v1.id, dataset_version_id, model_id, question_id, score=0.6
    )

    # Current run uses the NEW dataset_version (other_dataset_version.id).
    service = RegressionService(db_session)
    current = await service.create_run(
        v2.id, other_dataset_version.id, model_id, baseline_prompt_version_id=v1.id
    )
    await db_session.commit()
    await _add_response_and_score(db_session, current.run_id, question_id, model_id, score=0.9)
    await db_session.commit()

    await service.compute_results(current)
    await db_session.commit()

    assert current.status == RegressionStatus.NOT_COMPARABLE
    results = (
        await db_session.execute(select(RegressionResult).where(RegressionResult.regression_run_id == current.id))
    ).scalars().all()
    assert len(results) == 1
    assert results[0].delta_from_baseline is None  # never silently diffed


async def test_compute_results_no_prior_baseline_run_marks_not_comparable(db_session):
    _project_id, _dataset_id, dataset_version_id, question_id, model_id, template_id = await _seed_base(db_session)

    v1 = PromptVersion(prompt_template_id=template_id, version_number=1, content="V1: {question}")
    db_session.add(v1)
    await db_session.flush()
    v2 = PromptVersion(prompt_template_id=template_id, version_number=2, content="V2: {question}")
    db_session.add(v2)
    await db_session.flush()
    await db_session.commit()

    # v1 was never actually run — baseline_prompt_version_id points at a
    # prompt version with no completed RegressionRun to diff against.
    service = RegressionService(db_session)
    current = await service.create_run(v2.id, dataset_version_id, model_id, baseline_prompt_version_id=v1.id)
    await db_session.commit()
    await _add_response_and_score(db_session, current.run_id, question_id, model_id, score=0.9)
    await db_session.commit()

    await service.compute_results(current)
    await db_session.commit()

    assert current.status == RegressionStatus.NOT_COMPARABLE
