"""D2: arena endpoints are public (no auth) since voting is zero-cost."""

from sqlalchemy import select

from app.models.comparison import Comparison
from app.models.dataset import Dataset, DatasetVersion
from app.models.llm_model import DEFAULT_ELO_RATING, LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.response import Response, ResponseStatus
from app.models.run import Run
from app.models.user import User


async def _seed_two_model_responses(session_factory) -> tuple[int, int, int, int, int]:
    async with session_factory() as session:
        user = User(email="arena-route@example.com", hashed_password="x")
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
        model_a = LLMModel(provider="openai", name="gpt-4o-mini", display_name="A")
        model_b = LLMModel(provider="anthropic", name="claude-haiku-4-5", display_name="B")
        session.add_all([model_a, model_b])
        await session.flush()
        run = Run(project_id=project.id, dataset_version_id=dataset_version.id)
        session.add(run)
        await session.flush()
        response_1 = Response(
            run_id=run.id, question_id=question.id, model_id=model_a.id, status=ResponseStatus.SUCCESS, output="4"
        )
        response_2 = Response(
            run_id=run.id, question_id=question.id, model_id=model_b.id, status=ResponseStatus.SUCCESS, output="Four"
        )
        session.add_all([response_1, response_2])
        await session.flush()
        await session.commit()
        return question.id, response_1.id, response_2.id, model_a.id, model_b.id


async def test_next_comparison_requires_no_auth_and_returns_blind_pair(test_client, session_factory):
    question_id, response_1_id, response_2_id, _model_a_id, _model_b_id = await _seed_two_model_responses(
        session_factory
    )

    response = await test_client.get("/arena/next-comparison")

    assert response.status_code == 200
    body = response.json()
    assert body["question_id"] == question_id
    assert {body["response_1_id"], body["response_2_id"]} == {response_1_id, response_2_id}
    # Blind: the payload must never include a model_id or provider name.
    assert "model_id" not in body
    assert "model_a_id" not in body
    assert "provider" not in str(body)


async def test_next_comparison_404_when_no_pairs_available(test_client):
    response = await test_client.get("/arena/next-comparison")
    assert response.status_code == 404


async def test_vote_records_comparison_and_updates_human_elo_only(test_client, session_factory):
    question_id, response_1_id, response_2_id, model_a_id, model_b_id = await _seed_two_model_responses(
        session_factory
    )

    response = await test_client.post(
        "/arena/vote",
        json={
            "question_id": question_id,
            "response_1_id": response_1_id,
            "response_2_id": response_2_id,
            "winner_response_id": response_1_id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["winner_model_id"] == model_a_id

    async with session_factory() as session:
        comparisons = (await session.execute(select(Comparison))).scalars().all()
        assert len(comparisons) == 1
        assert comparisons[0].voter_type.value == "human"

        winner = await session.get(LLMModel, model_a_id)
        loser = await session.get(LLMModel, model_b_id)
        assert winner.elo_rating_human > DEFAULT_ELO_RATING
        assert loser.elo_rating_human < DEFAULT_ELO_RATING
        # office-hours Phase 6: a human vote must never move the LLM-judge track.
        assert winner.elo_rating_llm_judge == DEFAULT_ELO_RATING
        assert loser.elo_rating_llm_judge == DEFAULT_ELO_RATING


async def test_vote_tie_records_null_winner(test_client, session_factory):
    question_id, response_1_id, response_2_id, _model_a_id, _model_b_id = await _seed_two_model_responses(
        session_factory
    )

    response = await test_client.post(
        "/arena/vote",
        json={
            "question_id": question_id,
            "response_1_id": response_1_id,
            "response_2_id": response_2_id,
            "winner_response_id": None,
        },
    )

    assert response.status_code == 201
    assert response.json()["winner_model_id"] is None


async def test_vote_rejects_response_ids_from_a_different_question(test_client, session_factory):
    question_id, response_1_id, response_2_id, _model_a_id, _model_b_id = await _seed_two_model_responses(
        session_factory
    )
    response = await test_client.post(
        "/arena/vote",
        json={
            "question_id": 999999,
            "response_1_id": response_1_id,
            "response_2_id": response_2_id,
            "winner_response_id": response_1_id,
        },
    )
    assert response.status_code == 400


async def test_vote_rejects_winner_id_that_matches_neither_response(test_client, session_factory):
    question_id, response_1_id, response_2_id, _model_a_id, _model_b_id = await _seed_two_model_responses(
        session_factory
    )
    response = await test_client.post(
        "/arena/vote",
        json={
            "question_id": question_id,
            "response_1_id": response_1_id,
            "response_2_id": response_2_id,
            "winner_response_id": 999999,
        },
    )
    assert response.status_code == 400
