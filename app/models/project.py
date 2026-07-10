from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    # See app/models/comparison.py's TYPE_CHECKING comment for why.
    from app.models.dataset import Dataset
    from app.models.prompt import PromptTemplate
    from app.models.run import Run
    from app.models.user import User


class Project(Base):
    """Real project-scoped resources even in a solo demo — see design doc
    Next Steps Phase 1 note: this is a portfolio signal (multi-tenant SaaS
    pattern), not vestigial. The demo seeds one user/project by default."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship(back_populates="projects")
    datasets: Mapped[list["Dataset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    prompt_templates: Mapped[list["PromptTemplate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="project", cascade="all, delete-orphan")
