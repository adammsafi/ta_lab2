"""phase112_pipeline_name

Add pipeline_name discriminator column to pipeline_run_log and pipeline_stage_log.
This enables multi-pipeline support (daily, weekly, on-demand, etc.) with
per-pipeline dead-man switch queries and dashboard filtering.

Revision ID: b1c2d3e4f5a6
Revises: z9a0b1c2d3e4
Create Date: 2026-04-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pipeline_run_log: add pipeline_name NOT NULL with DEFAULT 'daily'
    # for backward compat (existing rows get 'daily' automatically)
    op.add_column(
        "pipeline_run_log",
        sa.Column(
            "pipeline_name",
            sa.VARCHAR(30),
            nullable=False,
            server_default="daily",
        ),
    )

    # pipeline_stage_log: add pipeline_name nullable (informational, set by callers)
    op.add_column(
        "pipeline_stage_log",
        sa.Column("pipeline_name", sa.VARCHAR(30), nullable=True),
    )

    # Index for per-pipeline dead-man queries and dashboard lookups
    op.create_index(
        "ix_pipeline_run_log_name_ts",
        "pipeline_run_log",
        ["pipeline_name", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_run_log_name_ts", table_name="pipeline_run_log")
    op.drop_column("pipeline_stage_log", "pipeline_name")
    op.drop_column("pipeline_run_log", "pipeline_name")
