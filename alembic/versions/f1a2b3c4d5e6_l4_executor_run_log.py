"""l4_executor_run_log

Phase 69-02: L4 Resolver Integration -- Executor run log L4 columns.

Adds two nullable columns to cmc_executor_run_log so that Plan 03 can record
the active macro regime and its resolved size multiplier for each executor run:

  l4_regime    TEXT NULL     -- macro regime composite key active during this run
  l4_size_mult NUMERIC NULL  -- size_mult resolved from L4 overlay (audit trail)

Also updates the status CHECK constraint to include 'no_signals', which covers
executor runs where signals were read but none met the sizing threshold.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: f1a2b3c4d5e6
Revises: e0d8f7aec87a
Create Date: 2026-03-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e0d8f7aec87a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add l4_regime + l4_size_mult columns and update status CHECK constraint."""

    # ------------------------------------------------------------------
    # 1. Add l4_regime: macro regime composite key for this executor run
    # ------------------------------------------------------------------
    op.add_column(
        "cmc_executor_run_log",
        sa.Column("l4_regime", sa.Text(), nullable=True),
        schema="public",
    )

    # ------------------------------------------------------------------
    # 2. Add l4_size_mult: resolved size multiplier from L4 overlay
    # ------------------------------------------------------------------
    op.add_column(
        "cmc_executor_run_log",
        sa.Column("l4_size_mult", sa.Numeric(), nullable=True),
        schema="public",
    )

    # ------------------------------------------------------------------
    # 3. Update status CHECK constraint to include 'no_signals'
    #    DROP + ADD because PostgreSQL does not support ALTER CONSTRAINT
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_executor_run_log "
        "DROP CONSTRAINT IF EXISTS chk_exec_run_status"
    )
    op.execute(
        "ALTER TABLE public.cmc_executor_run_log "
        "ADD CONSTRAINT chk_exec_run_status "
        "CHECK (status IN ('running', 'success', 'failed', 'stale_signal', 'no_signals'))"
    )


def downgrade() -> None:
    """Reverse l4 columns and restore original status CHECK constraint."""

    # ------------------------------------------------------------------
    # 3-reverse. Restore original status CHECK constraint
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_executor_run_log "
        "DROP CONSTRAINT IF EXISTS chk_exec_run_status"
    )
    op.execute(
        "ALTER TABLE public.cmc_executor_run_log "
        "ADD CONSTRAINT chk_exec_run_status "
        "CHECK (status IN ('running', 'success', 'failed', 'stale_signal'))"
    )

    # ------------------------------------------------------------------
    # 2-reverse. Drop l4_size_mult
    # ------------------------------------------------------------------
    op.drop_column("cmc_executor_run_log", "l4_size_mult", schema="public")

    # ------------------------------------------------------------------
    # 1-reverse. Drop l4_regime
    # ------------------------------------------------------------------
    op.drop_column("cmc_executor_run_log", "l4_regime", schema="public")
