import random

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.comparison import VoterType
from app.models.question import Question
from app.models.response import Response, ResponseStatus
from app.models.run import Run
from app.services.elo_service import EloService
from app.services.leaderboard_cache import invalidate_leaderboard_cache

# office-hours design doc Phase 6: a manual voting UI where a human can cast
# real votes, alongside the LLM judge's automatic ones (app/workers/eval_tasks.py).
# eng-review D2: public, no auth — voting costs nothing (no LLM call), unlike
# POST /runs, so there's no abuse-cost reason to gate it. A determined user
# could technically correlate response ids across requests to de-blind a
# pairing, but the UI never displays model identity before a vote is cast —
# that's the level of "blind" this demo needs, not adversarial-proof blinding.
router = APIRouter(prefix="/arena", tags=["arena"])


class ArenaComparisonOption(BaseModel):
    question_id: int
    question_text: str
    response_1_id: int
    response_1_text: str
    response_2_id: int
    response_2_text: str


class VoteRequest(BaseModel):
    question_id: int
    response_1_id: int
    response_2_id: int
    winner_response_id: int | None  # None means a tie


class VoteResponse(BaseModel):
    comparison_id: int
    winner_model_id: int | None


@router.get("/next-comparison", response_model=ArenaComparisonOption)
async def get_next_comparison(session: AsyncSession = Depends(get_session)) -> ArenaComparisonOption:
    question_stmt = (
        select(Response.question_id)
        .where(Response.status == ResponseStatus.SUCCESS)
        .group_by(Response.question_id)
        .having(func.count(func.distinct(Response.model_id)) >= 2)
        .order_by(func.random())
        .limit(1)
    )
    question_id = (await session.execute(question_stmt)).scalar_one_or_none()
    if question_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No comparisons available yet")

    question = await session.get(Question, question_id)

    all_responses = (
        await session.execute(
            select(Response).where(Response.question_id == question_id, Response.status == ResponseStatus.SUCCESS)
        )
    ).scalars().all()

    # One response per model — a question could have multiple successful
    # responses from the SAME model across repeated runs, and pairing a
    # model against itself would be meaningless.
    by_model: dict[int, Response] = {}
    for response in all_responses:
        by_model.setdefault(response.model_id, response)
    candidates = list(by_model.values())
    if len(candidates) < 2:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No comparisons available yet")

    response_1, response_2 = random.sample(candidates, 2)

    return ArenaComparisonOption(
        question_id=question_id,
        question_text=question.text,
        response_1_id=response_1.id,
        response_1_text=response_1.output or "",
        response_2_id=response_2.id,
        response_2_text=response_2.output or "",
    )


@router.post("/vote", response_model=VoteResponse, status_code=status.HTTP_201_CREATED)
async def submit_vote(body: VoteRequest, session: AsyncSession = Depends(get_session)) -> VoteResponse:
    response_1 = await session.get(Response, body.response_1_id)
    response_2 = await session.get(Response, body.response_2_id)
    if (
        response_1 is None
        or response_2 is None
        or response_1.question_id != body.question_id
        or response_2.question_id != body.question_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid response ids for this question"
        )
    if response_1.model_id == response_2.model_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot compare a model against itself")

    if body.winner_response_id is None:
        winner_model_id = None
    elif body.winner_response_id == body.response_1_id:
        winner_model_id = response_1.model_id
    elif body.winner_response_id == body.response_2_id:
        winner_model_id = response_2.model_id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="winner_response_id must match one of the two responses, or be null for a tie",
        )

    # project_id is derived from the response's Run, never trusted from the
    # client — the client only ever sees response ids, not project scope.
    run = await session.get(Run, response_1.run_id)

    elo_service = EloService(session)
    comparison = await elo_service.record_comparison(
        project_id=run.project_id,
        question_id=body.question_id,
        model_a_id=response_1.model_id,
        model_b_id=response_2.model_id,
        winner_model_id=winner_model_id,
        voter_type=VoterType.HUMAN,
    )
    await session.commit()

    # D13: a human vote changes elo_rating_human, which the leaderboard
    # serves from cache — same invalidate-after-commit rule as every other
    # EvaluationResult/Elo write.
    await invalidate_leaderboard_cache()

    return VoteResponse(comparison_id=comparison.id, winner_model_id=winner_model_id)
