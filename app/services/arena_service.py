from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comparison import Comparison, VoterType
from app.models.question import Question
from app.models.response import Response
from app.services.arena_judge import ArenaJudge
from app.services.elo_service import EloService


class ArenaService:
    """Ties ArenaJudge (blind verdict) to EloService (rating update) —
    translates the judge's A/B verdict, which is relative to a randomized
    slot assignment, back to the actual model ids before recording."""

    def __init__(self, session: AsyncSession, judge: ArenaJudge, elo_service: EloService):
        self.session = session
        self.judge = judge
        self.elo_service = elo_service

    async def run_llm_judged_comparison(
        self, project_id: int, question: Question, response_1: Response, response_2: Response
    ) -> Comparison:
        """response_1/response_2 must be two SUCCESSFUL Responses to the
        same question from two different models — callers (see
        app/workers/eval_tasks.py) are responsible for that filtering."""
        result = await self.judge.judge(question.text, response_1.output or "", response_2.output or "")

        if result.verdict == "TIE":
            winner_model_id = None
        elif result.verdict == "A":
            winner_model_id = response_1.model_id if result.response_1_was_a else response_2.model_id
        else:  # "B"
            winner_model_id = response_2.model_id if result.response_1_was_a else response_1.model_id

        return await self.elo_service.record_comparison(
            project_id=project_id,
            question_id=question.id,
            model_a_id=response_1.model_id,
            model_b_id=response_2.model_id,
            winner_model_id=winner_model_id,
            voter_type=VoterType.LLM_JUDGE,
        )
