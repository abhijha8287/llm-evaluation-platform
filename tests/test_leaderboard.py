"""Leaderboard aggregation: only SUCCESS-status Responses/EvaluationResults
count toward averages (eng-review D3/D9) — a failed or timed-out call must
never read as a real 0."""

import pytest

from app.models.comparison import Comparison, VoterType
from app.models.dataset import Dataset, DatasetVersion
from app.models.evaluation_result import EvaluationResult, EvaluationStatus, MetricName
from app.models.llm_model import DEFAULT_ELO_RATING, LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.response import Response, ResponseStatus
from app.models.run import Run
from app.models.user import User
from app.services.leaderboard_cache import invalidate_leaderboard_cache


@pytest.fixture(autouse=True)
async def _isolate_leaderboard_cache():
    # D13's cache is a single shared Redis key — each test here seeds its
    # own isolated SQLite DB, but without this they'd all read/write the
    # SAME cache entry and see each other's stale data. Fails open (no-op)
    # if Redis isn't running, same as the cache module itself.
    await invalidate_leaderboard_cache()
    yield
    await invalidate_leaderboard_cache()


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


async def test_leaderboard_shows_llm_judged_and_human_elo_separately(test_client, session_factory):
    """office-hours design doc Phase 6: LLM-judged and human-judged Elo must
    be two distinct fields, not blended into one number."""
    async with session_factory() as session:
        model_id = await _seed_leaderboard_fixture(session)
        model = await session.get(LLMModel, model_id)
        model.elo_rating_llm_judge = 1550.0
        model.elo_rating_human = 1450.0
        opponent = LLMModel(provider="anthropic", name="claude-haiku-4-5", display_name="Opponent")
        session.add(opponent)
        await session.flush()
        session.add(
            Comparison(
                project_id=1,
                question_id=1,
                model_a_id=model_id,
                model_b_id=opponent.id,
                winner_model_id=None,
                voter_type=VoterType.HUMAN,
                elo_delta_a=0,
                elo_delta_b=0,
            )
        )
        await session.commit()

    response = await test_client.get("/leaderboard")
    entries = {e["model_id"]: e for e in response.json()}
    entry = entries[model_id]

    assert entry["elo_rating_llm_judge"] == 1550.0
    assert entry["elo_rating_human"] == 1450.0
    assert entry["human_comparison_count"] == 1
    assert entry["llm_judge_comparison_count"] == 0


async def test_leaderboard_defaults_elo_to_1500_with_no_comparisons(test_client, session_factory):
    async with session_factory() as session:
        model_id = await _seed_leaderboard_fixture(session)

    response = await test_client.get("/leaderboard")
    entries = {e["model_id"]: e for e in response.json()}
    entry = entries[model_id]

    assert entry["elo_rating_llm_judge"] == DEFAULT_ELO_RATING
    assert entry["elo_rating_human"] == DEFAULT_ELO_RATING
    assert entry["llm_judge_comparison_count"] == 0
    assert entry["human_comparison_count"] == 0


async def test_leaderboard_serves_from_cache_on_second_read(test_client, session_factory):
    """Proves D13's cache is actually consulted, not just correct when
    empty: seed data, read once (populates cache), delete the underlying
    model without invalidating the cache, read again — a cache-less
    implementation would 404/empty on the second read since the model is
    gone from the DB; a working cache still serves the first read's data."""
    from sqlalchemy import delete

    async with session_factory() as session:
        model_id = await _seed_leaderboard_fixture(session)

    first = await test_client.get("/leaderboard")
    assert any(e["model_id"] == model_id for e in first.json())

    async with session_factory() as session:
        await session.execute(delete(LLMModel).where(LLMModel.id == model_id))
        await session.commit()

    second = await test_client.get("/leaderboard")
    assert any(e["model_id"] == model_id for e in second.json()), (
        "cache should still serve the first read's entries even though the "
        "model was deleted from the DB without invalidating the cache"
    )
