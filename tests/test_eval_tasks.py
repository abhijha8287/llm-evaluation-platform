"""Task T7 verify: N tasks enqueued for N (question, model) pairs, not 1 per
Run — plus an integration check that the task body's fresh-engine-per-task
pattern (Phase 5's verified asyncpg/asyncio.run() constraint) actually
persists data correctly."""

from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from app.core.config import get_settings
from app.models.dataset import Dataset, DatasetVersion, DatasetVersionQuestion
from app.models.evaluation_result import EvaluationResult
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.workers import eval_tasks
from tests.conftest import make_fake_evaluation_service, make_fake_llm_runner


def test_dispatch_run_creates_one_task_per_question_model_pair():
    with patch.object(eval_tasks, "chord") as mock_chord, patch.object(
        eval_tasks.run_pair_task, "s"
    ) as mock_pair_sig, patch.object(eval_tasks.mark_run_completed_task, "s") as mock_callback_sig:
        mock_chord_instance = MagicMock()
        mock_chord.return_value = mock_chord_instance

        eval_tasks.dispatch_run(run_id=42, question_ids=[1, 2], model_ids=[10, 20, 30])

        # 2 questions x 3 models = 6 tasks, NOT 1 task for the whole Run —
        # this is the actual behavior eng-review D12 chose horizontal
        # worker scaling over.
        assert mock_pair_sig.call_count == 6
        called_args = [call.args for call in mock_pair_sig.call_args_list]
        assert called_args == [
            (42, 1, 10),
            (42, 1, 20),
            (42, 1, 30),
            (42, 2, 10),
            (42, 2, 20),
            (42, 2, 30),
        ]

        mock_callback_sig.assert_called_once_with(42)
        mock_chord.assert_called_once()
        mock_chord_instance.assert_called_once()


def test_dispatch_run_single_pair():
    with patch.object(eval_tasks, "chord") as mock_chord, patch.object(
        eval_tasks.run_pair_task, "s"
    ) as mock_pair_sig, patch.object(eval_tasks.mark_run_completed_task, "s"):
        mock_chord.return_value = MagicMock()
        eval_tasks.dispatch_run(run_id=1, question_ids=[5], model_ids=[7])
        assert mock_pair_sig.call_count == 1
        assert mock_pair_sig.call_args.args == (1, 5, 7)


async def _seed_pair_fixture(session_factory) -> tuple[int, int, int]:
    async with session_factory() as session:
        user = User(email="task@example.com", hashed_password="x")
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
        session.add(DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=question.id))
        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()
        run = Run(project_id=project.id, dataset_version_id=dataset_version.id, status=RunStatus.RUNNING)
        session.add(run)
        await session.flush()
        await session.commit()
        return run.id, question.id, model.id


async def test_run_pair_async_persists_response_via_fresh_engine(
    session_factory, async_engine, monkeypatch
):
    """Integration check for the fresh-engine-per-task pattern itself (not
    just RunOrchestrator.run_pair's logic, already covered by
    test_run_orchestrator.py) — points get_settings().database_url at the
    test DB, same as any other test, but exercises the actual
    _run_pair_async code path including its own create_async_engine +
    dispose."""
    monkeypatch.setenv("DATABASE_URL", str(async_engine.url))
    get_settings.cache_clear()

    run_id, question_id, model_id = await _seed_pair_fixture(session_factory)

    fake_runner = make_fake_llm_runner(default_output="Paris")
    fake_evaluator = make_fake_evaluation_service()

    with patch.object(eval_tasks, "LLMRunner", return_value=fake_runner), patch.object(
        eval_tasks, "EvaluationService", return_value=fake_evaluator
    ):
        await eval_tasks._run_pair_async(run_id, question_id, model_id)

    async with session_factory() as session:
        responses = (await session.execute(select(Response).where(Response.run_id == run_id))).scalars().all()
        assert len(responses) == 1
        assert responses[0].status == ResponseStatus.SUCCESS
        assert responses[0].output == "Paris"

        eval_results = (
            (await session.execute(select(EvaluationResult).where(EvaluationResult.response_id == responses[0].id)))
            .scalars()
            .all()
        )
        assert len(eval_results) == 1

    get_settings.cache_clear()


async def test_mark_run_completed_async_updates_status(session_factory, async_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(async_engine.url))
    get_settings.cache_clear()

    run_id, _question_id, _model_id = await _seed_pair_fixture(session_factory)

    await eval_tasks._mark_run_completed_async(run_id)

    async with session_factory() as session:
        run = await session.get(Run, run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.completed_at is not None

    get_settings.cache_clear()


async def _seed_run_with_responses(
    session_factory,
) -> tuple[int, int, dict[str, int]]:
    """Question 1: 3 successful responses (models A, B, C) -> C(3,2) = 3 pairs.
    Question 2: 1 successful + 1 failed response -> 0 pairs (failed excluded,
    and a lone success has no partner)."""
    async with session_factory() as session:
        user = User(email="arena-dispatch@example.com", hashed_password="x")
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
        model_a = LLMModel(provider="openai", name="gpt-4o-mini", display_name="A")
        model_b = LLMModel(provider="anthropic", name="claude-haiku-4-5", display_name="B")
        model_c = LLMModel(provider="groq", name="groq/llama-3.3-70b-versatile", display_name="C")
        session.add_all([model_a, model_b, model_c])
        await session.flush()
        run = Run(project_id=project.id, dataset_version_id=dataset_version.id, status=RunStatus.RUNNING)
        session.add(run)
        await session.flush()

        session.add_all(
            [
                Response(run_id=run.id, question_id=q1.id, model_id=model_a.id, status=ResponseStatus.SUCCESS, output="a"),
                Response(run_id=run.id, question_id=q1.id, model_id=model_b.id, status=ResponseStatus.SUCCESS, output="b"),
                Response(run_id=run.id, question_id=q1.id, model_id=model_c.id, status=ResponseStatus.SUCCESS, output="c"),
                Response(run_id=run.id, question_id=q2.id, model_id=model_a.id, status=ResponseStatus.SUCCESS, output="a2"),
                Response(run_id=run.id, question_id=q2.id, model_id=model_b.id, status=ResponseStatus.FAILED, error_message="x"),
            ]
        )
        await session.flush()
        await session.commit()
        return run.id, project.id, {"q1": q1.id, "q2": q2.id}


async def test_mark_run_completed_dispatches_arena_comparisons_for_successful_pairs_only(
    session_factory, async_engine, monkeypatch
):
    """eng-review Phase 6: arena comparisons are dispatched per question for
    every pair of SUCCESSFUL responses — a failed response has no output to
    judge, and a question with fewer than 2 successes has no pair at all."""
    monkeypatch.setenv("DATABASE_URL", str(async_engine.url))
    get_settings.cache_clear()

    run_id, project_id, question_ids = await _seed_run_with_responses(session_factory)

    with patch.object(eval_tasks.arena_judge_pair_task, "delay") as mock_delay:
        await eval_tasks._mark_run_completed_async(run_id)

    # Q1 has 3 successful responses -> C(3,2) = 3 pairs. Q2 has 1 successful
    # + 1 failed -> 0 pairs. Total: 3, not 4 or 5.
    assert mock_delay.call_count == 3
    for call in mock_delay.call_args_list:
        dispatched_project_id, dispatched_question_id = call.args[0], call.args[1]
        assert dispatched_project_id == project_id
        assert dispatched_question_id == question_ids["q1"]

    get_settings.cache_clear()


async def test_arena_judge_pair_async_persists_comparison_and_updates_elo(
    session_factory, async_engine, monkeypatch
):
    from app.models.comparison import Comparison
    from app.services.arena_judge import ArenaJudgeResult

    monkeypatch.setenv("DATABASE_URL", str(async_engine.url))
    get_settings.cache_clear()

    async with session_factory() as session:
        user = User(email="arena-pair@example.com", hashed_password="x")
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
        model_a = LLMModel(provider="openai", name="gpt-4o-mini", display_name="A")
        model_b = LLMModel(provider="anthropic", name="claude-haiku-4-5", display_name="B")
        session.add_all([model_a, model_b])
        await session.flush()
        run = Run(project_id=project.id, dataset_version_id=dataset_version.id)
        session.add(run)
        await session.flush()
        response_1 = Response(run_id=run.id, question_id=question.id, model_id=model_a.id, status=ResponseStatus.SUCCESS, output="a")
        response_2 = Response(run_id=run.id, question_id=question.id, model_id=model_b.id, status=ResponseStatus.SUCCESS, output="b")
        session.add_all([response_1, response_2])
        await session.flush()
        await session.commit()
        project_id, question_id, r1_id, r2_id, model_a_id = (
            project.id, question.id, response_1.id, response_2.id, model_a.id,
        )

    fake_judge = MagicMock()
    fake_judge.judge = AsyncMock(return_value=ArenaJudgeResult(verdict="A", response_1_was_a=True))

    with patch.object(eval_tasks, "ArenaJudge", return_value=fake_judge):
        await eval_tasks._arena_judge_pair_async(project_id, question_id, r1_id, r2_id)

    async with session_factory() as session:
        comparisons = (await session.execute(select(Comparison).where(Comparison.question_id == question_id))).scalars().all()
        assert len(comparisons) == 1
        assert comparisons[0].winner_model_id == model_a_id

        winner = await session.get(LLMModel, model_a_id)
        from app.models.llm_model import DEFAULT_ELO_RATING

        assert winner.elo_rating_llm_judge > DEFAULT_ELO_RATING

    get_settings.cache_clear()
