import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RegressionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    # eng-review D7: a RegressionRun whose baseline was pinned to a different
    # dataset_version than the current one is never silently diffed — it's
    # marked NOT_COMPARABLE and the UI must show that explicitly, not a diff.
    NOT_COMPARABLE = "not_comparable"


class RegressionRun(Base):
    """eng-review D7: pins a Dataset version at creation time. Comparisons
    only happen between RegressionRuns that share the same dataset_version_id
    — see services/regression_service.py.

    Phase 7 build-out: model_id and run_id were added on top of the original
    Phase 1 schema — a prompt-version regression comparison is only
    meaningful if the MODEL is held constant while the prompt changes (the
    original spec omitted this, which would have let a prompt "regression"
    actually be a model-choice difference in disguise). run_id points at a
    real Run created and executed through the existing pipeline
    (RunOrchestrator.run_pair, EvaluationService) — a RegressionRun doesn't
    duplicate response generation or scoring, it reuses D8's shared
    infrastructure wholesale and adds a diff-against-baseline step on top."""

    __tablename__ = "regression_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_version_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="CASCADE"), index=True
    )
    baseline_prompt_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True
    )
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), index=True
    )
    model_id: Mapped[int] = mapped_column(ForeignKey("llm_models.id", ondelete="RESTRICT"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, unique=True)
    # SAEnum, not String — see question.py's comment; a plain String column
    # silently loses the Python enum type on every fresh load from the DB.
    status: Mapped[RegressionStatus] = mapped_column(
        SAEnum(RegressionStatus, native_enum=False, length=20), default=RegressionStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    prompt_version: Mapped["PromptVersion"] = relationship(foreign_keys=[prompt_version_id])
    baseline_prompt_version: Mapped["PromptVersion | None"] = relationship(
        foreign_keys=[baseline_prompt_version_id]
    )
    dataset_version: Mapped["DatasetVersion"] = relationship()
    model: Mapped["LLMModel"] = relationship()
    run: Mapped["Run"] = relationship()
    results: Mapped[list["RegressionResult"]] = relationship(
        back_populates="regression_run", cascade="all, delete-orphan"
    )


class RegressionResult(Base):
    __tablename__ = "regression_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    regression_run_id: Mapped[int] = mapped_column(
        ForeignKey("regression_runs.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    metric_name: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Null when there is no comparable baseline score for this question+metric
    # (e.g. first-ever run of this prompt template) or when the baseline run's
    # dataset_version didn't match (status=NOT_COMPARABLE at the run level).
    delta_from_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    regression_run: Mapped["RegressionRun"] = relationship(back_populates="results")
    question: Mapped["Question"] = relationship()
