"""add passed column to evaluation_results

Revision ID: ac9ab3ff3011
Revises: b141057e6263
Create Date: 2026-07-09

Phase 8: a "Pass Rate" chart needs pass/fail data per metric. Captured
directly from DeepEval's own metric.success (verified against the installed
library: pass/fail direction differs by metric — Faithfulness/
AnswerRelevancy pass when score >= threshold, Toxicity/Bias pass when
score <= threshold) rather than reimplemented, to avoid getting a direction
wrong. See app/models/evaluation_result.py.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ac9ab3ff3011"
down_revision: Union[str, None] = "b141057e6263"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evaluation_results", sa.Column("passed", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("evaluation_results", "passed")
