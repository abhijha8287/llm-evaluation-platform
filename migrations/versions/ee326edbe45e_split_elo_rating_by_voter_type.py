"""split elo_rating into llm-judged and human-judged tracks

Revision ID: ee326edbe45e
Revises: 549b6e9bc2e7
Create Date: 2026-07-09

office-hours design doc Phase 6: the leaderboard shows LLM-judged vs
human-judged Elo separately, not blended into one number — see
app/models/llm_model.py for the full rationale.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ee326edbe45e"
down_revision: Union[str, None] = "549b6e9bc2e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ELO_RATING = 1500.0


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("elo_rating_llm_judge", sa.Float(), nullable=False, server_default=str(DEFAULT_ELO_RATING)),
    )
    op.add_column(
        "llm_models",
        sa.Column("elo_rating_human", sa.Float(), nullable=False, server_default=str(DEFAULT_ELO_RATING)),
    )
    # Backfill from the old single elo_rating column before dropping it, so
    # any ratings already earned aren't silently reset to 1500 on upgrade.
    op.execute("UPDATE llm_models SET elo_rating_llm_judge = elo_rating, elo_rating_human = elo_rating")
    op.drop_column("llm_models", "elo_rating")


def downgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("elo_rating", sa.Float(), nullable=False, server_default=str(DEFAULT_ELO_RATING)),
    )
    # Downgrade collapses back to a single blended-by-average rating —
    # lossy, but there's no single "correct" un-split value.
    op.execute("UPDATE llm_models SET elo_rating = (elo_rating_llm_judge + elo_rating_human) / 2")
    op.drop_column("llm_models", "elo_rating_human")
    op.drop_column("llm_models", "elo_rating_llm_judge")
