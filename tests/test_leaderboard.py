"""Leaderboard aggregation: only SUCCESS-status Responses/EvaluationResults
count toward averages (eng-review D3/D9) — a failed or timed-out call must
never read as a real 0."""

from app.models.dataset import Dataset, DatasetVersion
from app.models.evaluation_result import EvaluationResult, EvaluationStatus, MetricName
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.response import Response, ResponseStatus
from app.models.run import Run
from app.models.user import User


async def _seed_leaderboard_fixture(session):
    user = User(email="lb@example.com", hashed_password="x")
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
    run = Run(project_id=project.id, dataset_version_id=dataset_version.id)
    session.add(run)
    await session.flush()

    success = Response(
        run_id=run.id, question_id=question.id, model_id=model.id,
        status=ResponseStatus.SUCCESS, output="ok", latency_ms=100, cost_usd=0.001,
    )
    failed = Response(
        run_id=run.id, question_id=question.id, model_id=model.id,
        status=ResponseStatus.FAILED, error_message="rate limited",
    )
    session.add_all([success, failed])
    await session.flush()

    session.add(
        EvaluationResult(
            response_id=success.id, metric_name=MetricName.TOXICITY,
            status=EvaluationStatus.SUCCESS, score=0.9, judge_model="gpt-4o-mini",
        )
    )
    session.add(
        EvaluationResult(
            response_id=success.id, metric_name=MetricName.BIAS,
            status=EvaluationStatus.FAILED, error_message="judge timed out", judge_model="gpt-4o-mini",
        )
    )
    await session.commit()
    return model.id


async def test_leaderboard_excludes_failed_responses_from_latency_average(test_client, session_factory):
    async with session_factory() as session:
        model_id = await _seed_leaderboard_fixture(session)

    response = await test_client.get("/leaderboard")
    assert response.status_code == 200
    entries = {e["model_id"]: e for e in response.json()}
    entry = entries[model_id]

    # Only the SUCCESS response counts — the FAILED one must not drag the
    # average down or inflate response_count.
    assert entry["response_count"] == 1
    assert entry["avg_latency_ms"] == 100
    assert entry["avg_cost_usd"] == 0.001


async def test_leaderboard_excludes_failed_evaluation_results_from_metric_averages(
    test_client, session_factory
):
    async with session_factory() as session:
        model_id = await _seed_leaderboard_fixture(session)

    response = await test_client.get("/leaderboard")
    entries = {e["model_id"]: e for e in response.json()}
    entry = entries[model_id]

    # TOXICITY succeeded (score 0.9) -> included. BIAS failed -> excluded
    # entirely, never averaged in as a 0.
    assert entry["metric_averages"]["toxicity"] == 0.9
    assert "bias" not in entry["metric_averages"]


async def test_leaderboard_requires_no_auth(test_client, session_factory):
    async with session_factory() as session:
        await _seed_leaderboard_fixture(session)

    response = await test_client.get("/leaderboard")
    assert response.status_code == 200


async def test_leaderboard_empty_when_no_models(test_client):
    response = await test_client.get("/leaderboard")
    assert response.status_code == 200
    assert response.json() == []
