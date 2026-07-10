from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    # See app/models/comparison.py's TYPE_CHECKING comment for why.
    from app.models.response import Response

DEFAULT_ELO_RATING = 1500.0


class LLMModel(Base):
    """A provider+model pair under evaluation (e.g. provider="openai",
    name="gpt-4o"). Distinct from the JUDGE model (app.core.config.judge_model)
    used to score responses — eng-review D9/Constraints: never the same
    model family judging its own answers without disclosure."""

    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider", "name", name="uq_provider_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(150))
    # office-hours design doc Phase 6: LLM-judged vs human-judged Elo are
    # tracked as two independent running ratings, not one blended number —
    # the leaderboard shows them separately since the LLM judge casts the
    # bulk of votes (fast volume) while human votes are comparatively rare
    # but higher-signal; blending them would let judge-model bias quietly
    # dominate a number presented as if humans agreed with it.
    # eng-review D4: both updated under a row-level lock (SELECT ... FOR
    # UPDATE) in services/elo_service.py — never a bare read-then-write.
    elo_rating_llm_judge: Mapped[float] = mapped_column(Float, default=DEFAULT_ELO_RATING)
    elo_rating_human: Mapped[float] = mapped_column(Float, default=DEFAULT_ELO_RATING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    responses: Mapped[list["Response"]] = relationship(back_populates="model")
