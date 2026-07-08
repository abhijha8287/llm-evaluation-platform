"""Phase 1 schema verification (Task T1): every table accepts one row and the
full FK graph (User -> Project -> Dataset -> Question -> DatasetVersion ->
Run -> Response -> EvaluationResult, plus Comparison and the Prompt/Regression
chain) round-trips through a real async session."""

import pytest

from app.models import (
    Comparison,
    Dataset,
    DatasetVersion,
    DatasetVersionQuestion,
    EvaluationResult,
    EvaluationStatus,
    LLMModel,
    MetricName,
    Project,
    PromptTemplate,
    PromptVersion,
    Question,
    QuestionType,
    RegressionResult,
    RegressionRun,
    RegressionStatus,
    Response,
    ResponseStatus,
    Run,
    RunStatus,
    User,
    VoterType,
)


async def test_seed_one_row_per_table(db_session):
    user = User(email="demo@example.com", hashed_password="not-a-real-hash")
    db_session.add(user)
    await db_session.flush()

    project = Project(owner_id=user.id, name="Demo Project")
    db_session.add(project)
    await db_session.flush()

    dataset = Dataset(project_id=project.id, name="Open-domain smoke set")
    db_session.add(dataset)
    await db_session.flush()

    open_question = Question(
        dataset_id=dataset.id,
        type=QuestionType.OPEN_DOMAIN,
        text="What is the capital of France?",
    )
    rag_question = Question(
        dataset_id=dataset.id,
        type=QuestionType.RAG,
        text="What did the document say about refund windows?",
        retrieval_context="Refunds are accepted within 30 days of purchase.",
        expected_output="30 days",
    )
    db_session.add_all([open_question, rag_question])
    await db_session.flush()

    dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=42, sample_size=2)
    db_session.add(dataset_version)
    await db_session.flush()

    db_session.add_all(
        [
            DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=open_question.id),
            DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=rag_question.id),
        ]
    )

    model_a = LLMModel(provider="openai", name="gpt-4o", display_name="GPT-4o")
    model_b = LLMModel(provider="anthropic", name="claude-sonnet", display_name="Claude Sonnet")
    db_session.add_all([model_a, model_b])
    await db_session.flush()

    run = Run(project_id=project.id, dataset_version_id=dataset_version.id, status=RunStatus.COMPLETED)
    db_session.add(run)
    await db_session.flush()

    response = Response(
        run_id=run.id,
        question_id=rag_question.id,
        model_id=model_a.id,
        status=ResponseStatus.SUCCESS,
        output="30 days",
        latency_ms=842,
        prompt_tokens=120,
        completion_tokens=8,
        cost_usd=0.0021,
    )
    db_session.add(response)
    await db_session.flush()

    eval_result = EvaluationResult(
        response_id=response.id,
        metric_name=MetricName.FAITHFULNESS,
        status=EvaluationStatus.SUCCESS,
        score=0.95,
        reason="Answer matches retrieval_context exactly.",
        judge_model="gpt-4o-mini",
    )
    db_session.add(eval_result)

    comparison = Comparison(
        project_id=project.id,
        question_id=open_question.id,
        model_a_id=model_a.id,
        model_b_id=model_b.id,
        winner_model_id=model_a.id,
        voter_type=VoterType.LLM_JUDGE,
        elo_delta_a=8.0,
        elo_delta_b=-8.0,
    )
    db_session.add(comparison)

    prompt_template = PromptTemplate(project_id=project.id, name="Support agent system prompt")
    db_session.add(prompt_template)
    await db_session.flush()

    prompt_version = PromptVersion(
        prompt_template_id=prompt_template.id, version_number=1, content="You are a helpful support agent."
    )
    db_session.add(prompt_version)
    await db_session.flush()

    regression_run = RegressionRun(
        prompt_version_id=prompt_version.id,
        dataset_version_id=dataset_version.id,
        status=RegressionStatus.COMPLETED,
    )
    db_session.add(regression_run)
    await db_session.flush()

    regression_result = RegressionResult(
        regression_run_id=regression_run.id,
        question_id=rag_question.id,
        metric_name=MetricName.FAITHFULNESS.value,
        score=0.95,
        delta_from_baseline=None,
    )
    db_session.add(regression_result)

    await db_session.commit()

    assert user.id is not None
    assert dataset_version.sample_seed == 42
    assert eval_result.status == EvaluationStatus.SUCCESS
    assert comparison.winner_model_id == model_a.id
    assert regression_result.delta_from_baseline is None


async def test_evaluation_result_unique_metric_per_response(db_session):
    """eng-review D9 depends on one EvaluationResult per (response, metric) —
    a duplicate insert must be rejected, not silently double-counted in
    leaderboard averages."""
    user = User(email="unique@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    project = Project(owner_id=user.id, name="P")
    db_session.add(project)
    await db_session.flush()
    dataset = Dataset(project_id=project.id, name="D")
    db_session.add(dataset)
    await db_session.flush()
    question = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Q")
    db_session.add(question)
    await db_session.flush()
    dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
    db_session.add(dataset_version)
    await db_session.flush()
    model = LLMModel(provider="openai", name="gpt-4o", display_name="GPT-4o")
    db_session.add(model)
    await db_session.flush()
    run = Run(project_id=project.id, dataset_version_id=dataset_version.id)
    db_session.add(run)
    await db_session.flush()
    response = Response(run_id=run.id, question_id=question.id, model_id=model.id, status=ResponseStatus.SUCCESS)
    db_session.add(response)
    await db_session.flush()

    db_session.add(
        EvaluationResult(
            response_id=response.id,
            metric_name=MetricName.TOXICITY,
            status=EvaluationStatus.SUCCESS,
            score=0.1,
            judge_model="gpt-4o-mini",
        )
    )
    await db_session.commit()

    db_session.add(
        EvaluationResult(
            response_id=response.id,
            metric_name=MetricName.TOXICITY,
            status=EvaluationStatus.SUCCESS,
            score=0.2,
            judge_model="gpt-4o-mini",
        )
    )
    with pytest.raises(Exception):  # noqa: B017 - IntegrityError wraps differently per driver
        await db_session.commit()
