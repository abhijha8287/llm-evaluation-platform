import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ResponseStatus(str, enum.Enum):
    """eng-review D3: per-response failure isolation. One provider timing out
    or erroring never blocks or corrupts the other providers in the same Run.
    Only SUCCESS responses are included in leaderboard averages."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class Response(Base):
    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("llm_models.id", ondelete="CASCADE"), index=True)

    # SAEnum, not String — see question.py's comment; a plain String column
    # silently loses the Python enum type on every fresh load from the DB.
    status: Mapped[ResponseStatus] = mapped_column(
        SAEnum(ResponseStatus, native_enum=False, length=20), default=ResponseStatus.PENDING
    )
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # eng-review D6: sourced from LiteLLM's pricing map (litellm.model_cost) at
    # scoring time, not a hand-maintained Costs table. Null (not 0.0) when the
    # model is missing from LiteLLM's map — see services/cost_service.py and
    # TODOS.md item 2 (cost-service missing-model test).
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="responses")
    question: Mapped["Question"] = relationship()
    model: Mapped["LLMModel"] = relationship(back_populates="responses")
    evaluation_results: Mapped[list["EvaluationResult"]] = relationship(
        back_populates="response", cascade="all, delete-orphan"
    )
