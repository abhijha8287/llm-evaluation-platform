from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="datasets")
    questions: Mapped[list["Question"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    versions: Mapped[list["DatasetVersion"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class DatasetVersion(Base):
    """eng-review D5: a fixed, seeded sample of a dataset. Every Run pins a
    specific version so all providers in that run are scored on the identical
    question set — the leaderboard compares model quality, not sampling luck.
    eng-review D7: RegressionRun also pins a version so prompt-version diffs
    only compare scores computed against the same underlying questions."""

    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    # Seed makes the sample reproducible: re-deriving the same version_number's
    # question set never requires storing the sample if it can be regenerated,
    # though we also materialize it via DatasetVersionQuestion for fast lookups
    # and to support hand-edited samples that diverge from a pure seed.
    sample_seed: Mapped[int] = mapped_column(Integer)
    sample_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship(back_populates="versions")
    sampled_questions: Mapped[list["DatasetVersionQuestion"]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )


class DatasetVersionQuestion(Base):
    """Materialized join: which Questions belong to a given DatasetVersion's
    sample. Materialized (not recomputed from the seed at read time) so a
    version's sample is stable even if sampling logic changes later."""

    __tablename__ = "dataset_version_questions"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "question_id", name="uq_dataset_version_question"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)

    dataset_version: Mapped["DatasetVersion"] = relationship(back_populates="sampled_questions")
    question: Mapped["Question"] = relationship()
