import asyncio
import itertools

from celery import chord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.evaluation.scoring_service import EvaluationService
from app.llm.runner import LLMRunner
from app.models.llm_model import LLMModel
from app.models.prompt import PromptVersion
from app.models.question import Question
from app.models.regression import RegressionRun
from app.models.response import Response, ResponseStatus
from app.models.run import Run
from app.repositories.run_repository import RunRepository
from app.services.arena_judge import ArenaJudge
from app.services.arena_service import ArenaService
from app.services.elo_service import EloService
from app.services.leaderboard_cache import invalidate_leaderboard_cache
from app.services.prompt_service import render_prompt
from app.services.regression_service import RegressionService
from app.services.run_orchestrator import RunOrchestrator
from app.workers.celery_app import celery_app


@celery_app.task(name="eval_tasks.run_pair")
def run_pair_task(run_id: int, question_id: int, model_id: int) -> None:
    """eng-review D1/D12: one Celery task per (question, model) pair — lets
    horizontal worker scaling (docker compose up --scale celery-worker=3)
    actually parallelize a Run, unlike one task per Run.

    Thin sync wrapper: Celery's worker pool executes tasks synchronously, so
    asyncio.run() bridges into the fully-async eval pipeline (LLMRunner,
    EvaluationService) — those stay pure-async and testable in isolation
    from Celery entirely (see tests/test_runner.py, test_scoring_service.py).

    A fresh engine is created and disposed per task, not the shared
    lru_cache'd app.core.database engine — verified directly (Phase 5) that
    asyncpg connections are bound to the event loop they were created on,
    and each asyncio.run() call opens a new loop; reusing a pooled engine
    across two asyncio.run() calls crashes the second one outright
    ("Event loop is closed" deep inside asyncpg's protocol layer). This is
    the accepted tradeoff eng-review D1 named explicitly (~one connection
    setup per task, fine at portfolio scale — see TODOS.md's shared-event-
    loop item for the real-production-scale follow-up).
    """
    asyncio.run(_run_pair_async(run_id, question_id, model_id))


@celery_app.task(name="eval_tasks.mark_run_completed")
def mark_run_completed_task(_group_results: list, run_id: int) -> None:
    """Celery chord callback — fires once every run_pair_task in the group
    has finished, regardless of each one's individual success/failure (D3:
    a failed pair is still a *finished* task). _group_results is unused; the
    outcome of each pair already lives in its own Response row.

    Also dispatches arena comparisons (office-hours Phase 6): once a run's
    responses are in, every pair of models that both succeeded on the same
    question is blind-judged — this is what "reach meaningful Elo volume
    quickly" (the original design doc's phrase) actually means in code."""
    asyncio.run(_mark_run_completed_async(run_id))


@celery_app.task(name="eval_tasks.arena_judge_pair")
def arena_judge_pair_task(project_id: int, question_id: int, response_1_id: int, response_2_id: int) -> None:
    """One task per pairwise comparison, same granularity rationale as
    run_pair_task — an arena judgment is its own LLM call and shouldn't
    block or be blocked by any other comparison."""
    asyncio.run(_arena_judge_pair_async(project_id, question_id, response_1_id, response_2_id))


@celery_app.task(name="eval_tasks.regression_pair")
def regression_pair_task(regression_run_id: int, question_id: int) -> None:
    """Phase 7: one task per question — unlike run_pair_task, there is no
    (question, model) cross product here, since a single RegressionRun tests
    exactly one model with exactly one prompt version."""
    asyncio.run(_regression_pair_async(regression_run_id, question_id))


@celery_app.task(name="eval_tasks.mark_regression_completed")
def mark_regression_completed_task(_group_results: list, regression_run_id: int) -> None:
    """Celery chord callback — marks the underlying Run complete, then runs
    RegressionService.compute_results (D7's baseline-diff step, including
    the NOT_COMPARABLE gate)."""
    asyncio.run(_mark_regression_completed_async(regression_run_id))


def dispatch_run(run_id: int, question_ids: list[int], model_ids: list[int]) -> None:
    """eng-review D12: one task per (question, model) pair, grouped under a
    chord whose callback marks the Run complete only once every pair has
    finished. Called from app/api/routes/runs.py after the Run row (and its
    dispatch inputs) are committed — Celery workers run in separate
    processes and need to see the row before a task references it.

    A plain function, not inline in the route, specifically so dispatch
    count/args can be unit-tested (Task T7's verify requirement) without an
    HTTP round trip or a live broker — see tests/test_eval_tasks.py."""
    pair_signatures = [
        run_pair_task.s(run_id, question_id, model_id)
        for question_id in question_ids
        for model_id in model_ids
    ]
    chord(pair_signatures)(mark_run_completed_task.s(run_id))


def dispatch_regression_run(regression_run_id: int, question_ids: list[int]) -> None:
    """See dispatch_run's docstring — same chord pattern, one task per
    question rather than one per (question, model) pair."""
    pair_signatures = [regression_pair_task.s(regression_run_id, question_id) for question_id in question_ids]
    chord(pair_signatures)(mark_regression_completed_task.s(regression_run_id))


async def _run_pair_async(run_id: int, question_id: int, model_id: int) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            run = await session.get(Run, run_id)
            question = await session.get(Question, question_id)
            model = await session.get(LLMModel, model_id)

            llm_runner = LLMRunner()
            evaluation_service = EvaluationService(
                judge_model=settings.judge_model, judge_api_key=settings.openai_api_key
            )
            orchestrator = RunOrchestrator(session, llm_runner, evaluation_service)
            await orchestrator.run_pair(run, question, model)
            await session.commit()
    finally:
        await engine.dispose()

    # D13: invalidate after commit, not before — a reader must never see a
    # freshly-emptied cache repopulated with data from a transaction that
    # hasn't actually landed yet.
    await invalidate_leaderboard_cache()


async def _mark_run_completed_async(run_id: int) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            run = await session.get(Run, run_id)
            await RunRepository(session).mark_completed(run)

            # Group successful responses by question, dispatch one arena
            # judgment per unique model pair within each question. A
            # question with only 0-1 successful responses has no pairs.
            successful = (
                await session.execute(
                    select(Response).where(Response.run_id == run_id, Response.status == ResponseStatus.SUCCESS)
                )
            ).scalars().all()
            await session.commit()

            by_question: dict[int, list[Response]] = {}
            for response in successful:
                by_question.setdefault(response.question_id, []).append(response)

            project_id = run.project_id
    finally:
        await engine.dispose()

    for question_id, responses in by_question.items():
        for response_1, response_2 in itertools.combinations(responses, 2):
            arena_judge_pair_task.delay(project_id, question_id, response_1.id, response_2.id)


async def _arena_judge_pair_async(project_id: int, question_id: int, response_1_id: int, response_2_id: int) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            question = await session.get(Question, question_id)
            response_1 = await session.get(Response, response_1_id)
            response_2 = await session.get(Response, response_2_id)

            judge = ArenaJudge(judge_model=settings.judge_model)
            arena_service = ArenaService(session, judge, EloService(session))
            await arena_service.run_llm_judged_comparison(project_id, question, response_1, response_2)
            await session.commit()
    finally:
        await engine.dispose()

    # D13: Elo changed, not just a Response — the leaderboard's elo_rating_*
    # columns are part of the cached payload too.
    await invalidate_leaderboard_cache()


async def _regression_pair_async(regression_run_id: int, question_id: int) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            regression_run = await session.get(RegressionRun, regression_run_id)
            run = await session.get(Run, regression_run.run_id)
            question = await session.get(Question, question_id)
            model = await session.get(LLMModel, regression_run.model_id)
            prompt_version = await session.get(PromptVersion, regression_run.prompt_version_id)
            rendered_prompt = render_prompt(prompt_version, question)

            llm_runner = LLMRunner()
            evaluation_service = EvaluationService(
                judge_model=settings.judge_model, judge_api_key=settings.openai_api_key
            )
            orchestrator = RunOrchestrator(session, llm_runner, evaluation_service)
            await orchestrator.run_pair(run, question, model, prompt_override=rendered_prompt)
            await session.commit()
    finally:
        await engine.dispose()

    # Phase 7's leaderboard-exclusion filter means regression responses
    # never change what the leaderboard shows, but invalidate anyway — the
    # filter itself depends on regression_runs existing, and a stale cached
    # entry from before this regression_run existed could theoretically
    # predate the exclusion being correct for it. Cheap and correct beats
    # explaining why it's skippable.
    await invalidate_leaderboard_cache()


async def _mark_regression_completed_async(regression_run_id: int) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            regression_run = await session.get(RegressionRun, regression_run_id)
            run = await session.get(Run, regression_run.run_id)
            await RunRepository(session).mark_completed(run)

            await RegressionService(session).compute_results(regression_run)
            await session.commit()
    finally:
        await engine.dispose()
