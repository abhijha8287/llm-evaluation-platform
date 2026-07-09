import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class QuestionType(str, enum.Enum):
    """D3 (Constraints)/eng-review Premise 3: DeepEval's RAG metrics
    (Faithfulness, Context Precision, Context Recall) require a
    retrieval_context. open_domain questions never attempt those metrics;
    rag questions require retrieval_context to be non-null."""

    OPEN_DOMAIN = "open_domain"
    RAG = "rag"


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    # eng-review follow-up (Phase 4): SAEnum(..., native_enum=False), not a
    # plain String — verified that a plain String column loses the Python
    # enum type on every fresh load (returns a raw str), which silently
    # breaks any code relying on .value or isinstance() after a DB round-trip
    # (== comparisons still work via str equality, so this bug is easy to
    # miss until something calls .value). Applied consistently across every
    # enum column in this schema, not just this one.
    type: Mapped[QuestionType] = mapped_column(SAEnum(QuestionType, native_enum=False, length=20))
    text: Mapped[str] = mapped_column(Text)
    # Required when type == RAG, must be null when type == OPEN_DOMAIN.
    # Enforced in the repository layer (see repositories/question_repository.py)
    # rather than a DB CHECK constraint, to keep the constraint's rationale
    # colocated with the validation error message shown to API callers.
    retrieval_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship(back_populates="questions")
