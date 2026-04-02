"""phase105_sweep_columns

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
Create Date: 2026-04-01

Phase 105 Plan 01: Parameter Optimization -- Sweep Columns.

Adds 7 nullable sweep-tracking columns to public.trial_registry, plus a
partial index on sweep_id for efficient sweep-group queries.

Columns added (all nullable to preserve backward compat with Phase 102 rows):
  sweep_id                UUID    -- groups all trials from one run_sweep() call
  n_sweep_trials          INTEGER -- total trials in this sweep run
  plateau_score           FLOAT   -- IC plateau detection score (post-sweep)
  rolling_stability_passes BOOL   -- TRUE if rolling-window IC std passes gate
  ic_cv                   FLOAT   -- coefficient of variation of IC across folds
  sign_flips              SMALLINT -- count of IC sign flips across rolling windows
  dsr_adjusted_sharpe     FLOAT   -- deflated Sharpe ratio adjusted for multiple tests

Index added:
  ix_trial_registry_sweep_id  ON trial_registry (sweep_id) WHERE sweep_id IS NOT NULL

Phase 102 (u4v5w6x7y8z9) created trial_registry.
Phase 105 extends it with sweep orchestration metadata.

ASCII-only comments throughout (Windows cp1252 compatibility).
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "y8z9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "x7y8z9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # Add 7 sweep-tracking columns to trial_registry.
    # All nullable -- Phase 102 rows remain valid with NULLs.
    # ADD COLUMN IF NOT EXISTS is idempotent for re-run safety.
    # =========================================================================
    conn.execute(
        text("""
        ALTER TABLE public.trial_registry
            ADD COLUMN IF NOT EXISTS sweep_id                UUID,
            ADD COLUMN IF NOT EXISTS n_sweep_trials          INTEGER,
            ADD COLUMN IF NOT EXISTS plateau_score           DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS rolling_stability_passes BOOLEAN,
            ADD COLUMN IF NOT EXISTS ic_cv                   DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS sign_flips              SMALLINT,
            ADD COLUMN IF NOT EXISTS dsr_adjusted_sharpe     DOUBLE PRECISION
        """)
    )

    logger.info("phase105 migration: added 7 sweep columns to trial_registry")

    # =========================================================================
    # Partial index on sweep_id for sweep-group queries.
    # WHERE sweep_id IS NOT NULL keeps the index small (Phase 102 backfill
    # rows have sweep_id=NULL and do not need to be indexed).
    # =========================================================================
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_trial_registry_sweep_id
            ON public.trial_registry (sweep_id)
            WHERE sweep_id IS NOT NULL
        """)
    )

    logger.info("phase105 migration: created partial index ix_trial_registry_sweep_id")


def downgrade() -> None:
    conn = op.get_bind()

    # Drop partial index first.
    conn.execute(
        text("""
        DROP INDEX IF EXISTS public.ix_trial_registry_sweep_id
        """)
    )

    logger.info("phase105 downgrade: dropped ix_trial_registry_sweep_id")

    # Drop the 7 columns in reverse order.
    conn.execute(
        text("""
        ALTER TABLE public.trial_registry
            DROP COLUMN IF EXISTS dsr_adjusted_sharpe,
            DROP COLUMN IF EXISTS sign_flips,
            DROP COLUMN IF EXISTS ic_cv,
            DROP COLUMN IF EXISTS rolling_stability_passes,
            DROP COLUMN IF EXISTS plateau_score,
            DROP COLUMN IF EXISTS n_sweep_trials,
            DROP COLUMN IF EXISTS sweep_id
        """)
    )

    logger.info("phase105 downgrade: removed 7 sweep columns from trial_registry")
