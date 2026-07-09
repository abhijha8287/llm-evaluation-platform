"""add model_id and run_id to regression_runs

Revision ID: b141057e6263
Revises: ee326edbe45e
Create Date: 2026-07-09

Phase 7: a prompt-version regression comparison is only meaningful if the
model is held constant while the prompt changes — the original Phase 1
schema omitted this. run_id points at a real Run, executed through the
existing RunOrchestrator/EvaluationService pipeline (D8) rather than a
parallel response-generation path — see app/models/regression.py.

Added as NOT NULL directly (no nullable-then-backfill dance): regression_runs
has zero rows at this point in the migration history — Phase 7 is the first
implementation to ever write to this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b141057e6263"
down_revision: Union[str, None] = "ee326edbe45e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "regression_runs",
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("llm_models.id", ondelete="RESTRICT"), nullable=False),
    )
    op.add_column(
        "regression_runs",
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_regression_runs_model_id", "regression_runs", ["model_id"])
    op.create_index("ix_regression_runs_run_id", "regression_runs", ["run_id"])
    op.create_unique_constraint("uq_regression_runs_run_id", "regression_runs", ["run_id"])


def downgrade() -> None:
    op.drop_constraint("uq_regression_runs_run_id", "regression_runs", type_="unique")
    op.drop_index("ix_regression_runs_run_id", table_name="regression_runs")
    op.drop_index("ix_regression_runs_model_id", table_name="regression_runs")
    op.drop_column("regression_runs", "run_id")
    op.drop_column("regression_runs", "model_id")
