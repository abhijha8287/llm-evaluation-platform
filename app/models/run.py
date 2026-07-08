import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    # A Run can complete with some Responses failed (eng-review D3: one failed
    # provider never blocks the others) — COMPLETED means "all tasks finished",
    # not "all succeeded". Per-Response status carries the actual outcome.
    FAILED = "failed"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[RunStatus] = mapped_column(String(20), default=RunStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="runs")
    dataset_version: Mapped["DatasetVersion"] = relationship()
    responses: Mapped[list["Response"]] = relationship(back_populates="run", cascade="all, delete-orphan")
