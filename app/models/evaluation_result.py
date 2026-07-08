import enum
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MetricName(str, enum.Enum):
    """RAG-only metrics require Question.retrieval_context (enforced in
    evaluation/scoring_service.py, eng-review D8's shared EvaluationService).
    FAITHFULNESS is this platform's hallucination signal — see design doc
    Success Criteria: contradiction between the answer and retrieval_context."""

    FAITHFULNESS = "faithfulness"  # RAG-only
    TOXICITY = "toxicity"
    BIAS = "bias"
    ANSWER_RELEVANCY = "answer_relevancy"


class EvaluationStatus(str, enum.Enum):
    """eng-review D9: distinct from Response.status. A Response can succeed
    while its judge-model scoring call independently fails. FAILED results
    are EXCLUDED from leaderboard averages, never counted as a real 0.0."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("response_id", "metric_name", name="uq_response_metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("responses.id", ondelete="CASCADE"), index=True)
    metric_name: Mapped[MetricName] = mapped_column(String(30))
    status: Mapped[EvaluationStatus] = mapped_column(String(20), default=EvaluationStatus.PENDING)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fixed, separate judge model for every response regardless of provider
    # (see app.core.config.Settings.judge_model) — recorded per-result so
    # historical scores remain interpretable if the judge model is ever changed.
    judge_model: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    response: Mapped["Response"] = relationship(back_populates="evaluation_results")
