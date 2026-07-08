from datetime import datetime

from sqlalchemy import DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

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
    # eng-review D4: updated under a row-level lock (SELECT ... FOR UPDATE) in
    # services/elo_service.py — never updated via a bare read-then-write.
    elo_rating: Mapped[float] = mapped_column(Float, default=DEFAULT_ELO_RATING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    responses: Mapped[list["Response"]] = relationship(back_populates="model")
