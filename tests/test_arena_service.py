"""ArenaService: verifies the judge's A/B verdict (relative to a randomized
slot) maps back to the correct model_id as the Comparison winner — this is
the one place a position-bias bug would silently misattribute a win."""

from unittest.mock import AsyncMock

from app.models.dataset import Dataset, DatasetVersion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.response import Response, ResponseStatus
from app.models.run import Run
from app.models.user import User
from app.services.arena_judge import ArenaJudgeResult
from app.services.arena_service import ArenaService
from app.services.elo_service import EloService


async def _seed_two_responses(session) -> tuple[int, "Question", "Response", "Response"]:
    user = User(email="arena@example.com", hashed_password="x")
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
    model_1 = LLMModel(provider="openai", name="gpt-4o-mini", display_name="Model1")
    model_2 = LLMModel(provider="anthropic", name="claude-haiku-4-5", display_name="Model2")
    session.add_all([model_1, model_2])
    await session.flush()
    run = Run(project_id=project.id, dataset_version_id=dataset_version.id)
    session.add(run)
    await session.flush()
    response_1 = Response(
        run_id=run.id, question_id=question.id, model_id=model_1.id, status=ResponseStatus.SUCCESS, output="r1"
    )
    response_2 = Response(
        run_id=run.id, question_id=question.id, model_id=model_2.id, status=ResponseStatus.SUCCESS, output="r2"
    )
    session.add_all([response_1, response_2])
    await session.flush()
    await session.commit()
    return project.id, question, response_1, response_2


def _fake_judge(verdict: str, response_1_was_a: bool):
    judge = AsyncMock()
    judge.judge = AsyncMock(return_value=ArenaJudgeResult(verdict=verdict, response_1_was_a=response_1_was_a))
    return judge


async def test_verdict_a_not_swapped_credits_response_1_model(db_session):
    project_id, question, response_1, response_2 = await _seed_two_responses(db_session)
    service = ArenaService(db_session, _fake_judge("A", response_1_was_a=True), EloService(db_session))

    comparison = await service.run_llm_judged_comparison(project_id, question, response_1, response_2)

    assert comparison.winner_model_id == response_1.model_id


async def test_verdict_a_swapped_credits_response_2_model(db_session):
    """response_1 was placed in slot B (response_1_was_a=False), so a
    verdict of "A" actually means response_2's model won — this is exactly
    the bug a naive (non-position-aware) implementation would get backwards."""
    project_id, question, response_1, response_2 = await _seed_two_responses(db_session)
    service = ArenaService(db_session, _fake_judge("A", response_1_was_a=False), EloService(db_session))

    comparison = await service.run_llm_judged_comparison(project_id, question, response_1, response_2)

    assert comparison.winner_model_id == response_2.model_id


async def test_verdict_b_not_swapped_credits_response_2_model(db_session):
    project_id, question, response_1, response_2 = await _seed_two_responses(db_session)
    service = ArenaService(db_session, _fake_judge("B", response_1_was_a=True), EloService(db_session))

    comparison = await service.run_llm_judged_comparison(project_id, question, response_1, response_2)

    assert comparison.winner_model_id == response_2.model_id


async def test_verdict_b_swapped_credits_response_1_model(db_session):
    project_id, question, response_1, response_2 = await _seed_two_responses(db_session)
    service = ArenaService(db_session, _fake_judge("B", response_1_was_a=False), EloService(db_session))

    comparison = await service.run_llm_judged_comparison(project_id, question, response_1, response_2)

    assert comparison.winner_model_id == response_1.model_id


async def test_verdict_tie_has_no_winner(db_session):
    project_id, question, response_1, response_2 = await _seed_two_responses(db_session)
    service = ArenaService(db_session, _fake_judge("TIE", response_1_was_a=True), EloService(db_session))

    comparison = await service.run_llm_judged_comparison(project_id, question, response_1, response_2)

    assert comparison.winner_model_id is None
