import enum
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VoterType(str, enum.Enum):
    """office-hours design doc Phase 6 / eng-review: a fixed neutral LLM judge
    casts the bulk of blind pairwise votes to reach meaningful Elo volume
    quickly; a manual voting UI lets real human votes be cast too. Both write
    here, tagged by voter_type, so the leaderboard can show LLM-judged vs
    human-judged Elo separately."""

    LLM_JUDGE = "llm_judge"
    HUMAN = "human"


class Comparison(Base):
    """A single blind pairwise comparison between two models on one question.
    Elo updates derived from this row are applied under a row-level lock on
    LLMModel (eng-review D4) — see services/elo_service.py."""

    __tablename__ = "comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)

    model_a_id: Mapped[int] = mapped_column(ForeignKey("llm_models.id", ondelete="CASCADE"), index=True)
    model_b_id: Mapped[int] = mapped_column(ForeignKey("llm_models.id", ondelete="CASCADE"), index=True)
    # Null winner_model_id means a tie.
    winner_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id", ondelete="SET NULL"), nullable=True
    )

    voter_type: Mapped[VoterType] = mapped_column(String(20))
    elo_delta_a: Mapped[float] = mapped_column(Float)
    elo_delta_b: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    question: Mapped["Question"] = relationship()
    model_a: Mapped["LLMModel"] = relationship(foreign_keys=[model_a_id])
    model_b: Mapped["LLMModel"] = relationship(foreign_keys=[model_b_id])
    winner: Mapped["LLMModel | None"] = relationship(foreign_keys=[winner_model_id])
