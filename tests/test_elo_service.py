"""Task T9 verify: test fires N concurrent comparisons, asserts final Elo
reflects all N.

Pure Elo math is tested against the SQLite fixture (db_session) — no
concurrency involved. The actual concurrency test needs a REAL Postgres
row-level lock: SQLite is single-writer at the file level regardless of any
application-level FOR UPDATE clause, so a broken/missing lock would still
"pass" there by accident. See test_concurrent_comparisons_no_lost_updates."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.exc import OperationalError

from app.models.comparison import Comparison, VoterType
from app.models.dataset import Dataset
from app.models.llm_model import DEFAULT_ELO_RATING, LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.user import User
from app.services.elo_service import EloService, expected_score

POSTGRES_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/llm_eval"


def test_expected_score_equal_ratings_is_half():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_expected_score_higher_rating_is_favored():
    assert expected_score(1600, 1400) > 0.5
    assert expected_score(1400, 1600) < 0.5


async def _seed_pair(session) -> tuple[int, int, int, int, int]:
    # Unique suffix per call — test_concurrent_comparisons_no_lost_updates
    # runs against the real, persistent dev Postgres (docker-compose), which
    # already carries seeded demo models (see app/core/seed_data.py) and
    # residue from earlier manual smoke tests. Fixed provider/name values
    # would collide with those via the (provider, name) unique constraint.
    suffix = uuid.uuid4().hex[:8]
    user = User(email=f"elo-{suffix}@example.com", hashed_password="x")
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
    model_a = LLMModel(provider="openai", name=f"gpt-4o-mini-test-{suffix}", display_name="A")
    model_b = LLMModel(provider="anthropic", name=f"claude-haiku-4-5-test-{suffix}", display_name="B")
    session.add_all([model_a, model_b])
    await session.flush()
    await session.commit()
    return project.id, question.id, model_a.id, model_b.id, user.id


async def test_record_comparison_winner_gains_loser_loses(db_session):
    project_id, question_id, model_a_id, model_b_id, _user_id = await _seed_pair(db_session)

    elo = EloService(db_session)
    comparison = await elo.record_comparison(
        project_id, question_id, model_a_id, model_b_id, winner_model_id=model_a_id, voter_type=VoterType.LLM_JUDGE
    )
    await db_session.commit()

    model_a = await db_session.get(LLMModel, model_a_id)
    model_b = await db_session.get(LLMModel, model_b_id)
    assert model_a.elo_rating_llm_judge > DEFAULT_ELO_RATING
    assert model_b.elo_rating_llm_judge < DEFAULT_ELO_RATING
    assert comparison.elo_delta_a > 0
    assert comparison.elo_delta_b < 0
    # Equal starting ratings -> symmetric deltas.
    assert comparison.elo_delta_a == pytest.approx(-comparison.elo_delta_b)


async def test_record_comparison_tie_keeps_equal_ratings_equal(db_session):
    project_id, question_id, model_a_id, model_b_id, _user_id = await _seed_pair(db_session)

    elo = EloService(db_session)
    await elo.record_comparison(
        project_id, question_id, model_a_id, model_b_id, winner_model_id=None, voter_type=VoterType.LLM_JUDGE
    )
    await db_session.commit()

    model_a = await db_session.get(LLMModel, model_a_id)
    model_b = await db_session.get(LLMModel, model_b_id)
    # Equal ratings + tie -> no rating change at all (expected score was
    # already 0.5, actual score is 0.5, delta is zero).
    assert model_a.elo_rating_llm_judge == pytest.approx(DEFAULT_ELO_RATING)
    assert model_b.elo_rating_llm_judge == pytest.approx(DEFAULT_ELO_RATING)


async def test_record_comparison_updates_only_the_matching_voter_type_field(db_session):
    project_id, question_id, model_a_id, model_b_id, _user_id = await _seed_pair(db_session)

    elo = EloService(db_session)
    await elo.record_comparison(
        project_id, question_id, model_a_id, model_b_id, winner_model_id=model_a_id, voter_type=VoterType.HUMAN
    )
    await db_session.commit()

    model_a = await db_session.get(LLMModel, model_a_id)
    # office-hours Phase 6: LLM-judged and human-judged Elo are independent
    # tracks — a human vote must never move the LLM-judge rating.
    assert model_a.elo_rating_human > DEFAULT_ELO_RATING
    assert model_a.elo_rating_llm_judge == pytest.approx(DEFAULT_ELO_RATING)


async def test_record_comparison_invalid_winner_raises(db_session):
    project_id, question_id, model_a_id, model_b_id, _user_id = await _seed_pair(db_session)
    elo = EloService(db_session)
    with pytest.raises(ValueError):
        await elo.record_comparison(
            project_id, question_id, model_a_id, model_b_id, winner_model_id=999999, voter_type=VoterType.LLM_JUDGE
        )


@pytest.fixture
async def postgres_session_factory():
    engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        async with engine.connect():
            pass
    except OperationalError:
        pytest.skip("Postgres not reachable — run `docker compose up -d postgres` (and alembic upgrade head)")
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_concurrent_comparisons_no_lost_updates(postgres_session_factory):
    """eng-review D4's actual claim under test: N comparisons resolving
    concurrently must all land — none silently overwritten by a
    read-modify-write race. Verified via an exact invariant: the sum of
    every recorded elo_delta must equal the model's total rating change,
    which only holds if every comparison's delta was computed against the
    rating state that was actually current at write time (i.e. the lock
    genuinely serialized the updates rather than letting them race)."""
    async with postgres_session_factory() as session:
        project_id, question_id, model_a_id, model_b_id, user_id = await _seed_pair(session)

    try:
        concurrency = 10

        async def run_one(i: int) -> None:
            async with postgres_session_factory() as session:
                elo = EloService(session)
                winner = model_a_id if i % 2 == 0 else model_b_id
                await elo.record_comparison(
                    project_id, question_id, model_a_id, model_b_id,
                    winner_model_id=winner, voter_type=VoterType.LLM_JUDGE,
                )
                await session.commit()

        await asyncio.gather(*[run_one(i) for i in range(concurrency)])

        async with postgres_session_factory() as session:
            comparisons = (
                (await session.execute(select(Comparison).where(Comparison.question_id == question_id)))
                .scalars()
                .all()
            )
            assert len(comparisons) == concurrency

            model_a = await session.get(LLMModel, model_a_id)
            total_delta_a = sum(c.elo_delta_a for c in comparisons)
            assert model_a.elo_rating_llm_judge == pytest.approx(DEFAULT_ELO_RATING + total_delta_a, abs=1e-6)

            model_b = await session.get(LLMModel, model_b_id)
            total_delta_b = sum(c.elo_delta_b for c in comparisons)
            assert model_b.elo_rating_llm_judge == pytest.approx(DEFAULT_ELO_RATING + total_delta_b, abs=1e-6)
    finally:
        # This test runs against the real, persistent dev Postgres (not an
        # ephemeral SQLite temp file) — without cleanup, every run leaves a
        # phantom user/project/dataset/question/models/comparisons behind
        # forever. Deleting the User cascades Project->Dataset->Question;
        # deleting the LLMModels cascades their Comparisons (both FKs are
        # ondelete="CASCADE" — see app/models/*.py).
        async with postgres_session_factory() as session:
            await session.execute(delete(LLMModel).where(LLMModel.id.in_((model_a_id, model_b_id))))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
