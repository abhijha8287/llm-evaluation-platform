from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comparison import Comparison, VoterType
from app.models.llm_model import LLMModel

K_FACTOR = 32.0

_ELO_FIELD_BY_VOTER_TYPE = {
    VoterType.LLM_JUDGE: "elo_rating_llm_judge",
    VoterType.HUMAN: "elo_rating_human",
}


def expected_score(rating_a: float, rating_b: float) -> float:
    """Standard Elo expected-score formula: probability A beats B given the
    two ratings."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


class EloService:
    """eng-review D4: Elo updates race under concurrency — two comparisons
    resolving at once for the same model can both read the same starting
    rating and one write clobbers the other. Every update here happens
    inside a row-level lock (SELECT ... FOR UPDATE) on both models involved,
    acquired in a fixed order (ascending id) regardless of which is
    "model_a"/"model_b" in the comparison — locking in comparison order
    instead would deadlock the moment two concurrent comparisons involve the
    same pair of models in opposite order (A-vs-B locks A then B; B-vs-A
    locks B then A; each waits on the other's held lock)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_comparison(
        self,
        project_id: int,
        question_id: int,
        model_a_id: int,
        model_b_id: int,
        winner_model_id: int | None,
        voter_type: VoterType,
    ) -> Comparison:
        field = _ELO_FIELD_BY_VOTER_TYPE[voter_type]

        low_id, high_id = sorted((model_a_id, model_b_id))
        stmt = select(LLMModel).where(LLMModel.id.in_((low_id, high_id))).with_for_update().order_by(LLMModel.id)
        result = await self.session.execute(stmt)
        models_by_id = {model.id: model for model in result.scalars().all()}
        model_a = models_by_id[model_a_id]
        model_b = models_by_id[model_b_id]

        rating_a = getattr(model_a, field)
        rating_b = getattr(model_b, field)
        expected_a = expected_score(rating_a, rating_b)
        expected_b = 1.0 - expected_a

        if winner_model_id == model_a_id:
            actual_a, actual_b = 1.0, 0.0
        elif winner_model_id == model_b_id:
            actual_a, actual_b = 0.0, 1.0
        elif winner_model_id is None:
            actual_a, actual_b = 0.5, 0.5
        else:
            raise ValueError(
                f"winner_model_id={winner_model_id} is neither model_a_id={model_a_id} "
                f"nor model_b_id={model_b_id} nor None (tie)"
            )

        delta_a = K_FACTOR * (actual_a - expected_a)
        delta_b = K_FACTOR * (actual_b - expected_b)

        setattr(model_a, field, rating_a + delta_a)
        setattr(model_b, field, rating_b + delta_b)

        comparison = Comparison(
            project_id=project_id,
            question_id=question_id,
            model_a_id=model_a_id,
            model_b_id=model_b_id,
            winner_model_id=winner_model_id,
            voter_type=voter_type,
            elo_delta_a=delta_a,
            elo_delta_b=delta_b,
        )
        self.session.add(comparison)
        await self.session.flush()
        return comparison
