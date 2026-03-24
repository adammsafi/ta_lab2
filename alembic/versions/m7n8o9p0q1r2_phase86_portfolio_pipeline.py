"""Phase 86 portfolio pipeline schema extensions.

Creates:
  stop_calibrations - stores MAE/MFE percentile-based stop levels per (id, strategy).
    PK: (id, strategy)

Extends:
  dim_executor_config - adds target_annual_vol NUMERIC column with positive CHECK constraint.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-03-24
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "m7n8o9p0q1r2"
down_revision: Union[str, Sequence[str], None] = "l6m7n8o9p0q1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # stop_calibrations table
    # Stores MAE/MFE percentile-derived stop levels per (asset, strategy).
    # PK: (id, strategy)
    # sl_p25/sl_p50/sl_p75 = absolute MAE percentiles (tight to wide stop)
    # tp_p50/tp_p75 = MFE percentiles (conservative to aggressive TP)
    # n_trades = number of bake-off trades used in calibration
    # calibrated_at = timestamp of last calibration run
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.stop_calibrations (
            id              INTEGER     NOT NULL,
            strategy        TEXT        NOT NULL,
            sl_p25          NUMERIC,
            sl_p50          NUMERIC,
            sl_p75          NUMERIC,
            tp_p50          NUMERIC,
            tp_p75          NUMERIC,
            n_trades        INTEGER,
            calibrated_at   TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (id, strategy)
        )
        """)
    )

    # ------------------------------------------------------------------
    # dim_executor_config: add target_annual_vol column
    # NULL = target-vol mode disabled (uses fixed_fraction sizing).
    # Non-null enables GARCH-informed target-vol sizing mode.
    # CHECK ensures value is strictly positive when set.
    # Example: 0.80 = target 80% annualized vol.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            ADD COLUMN IF NOT EXISTS target_annual_vol NUMERIC DEFAULT NULL
        """)
    )

    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            ADD CONSTRAINT chk_target_annual_vol_positive
            CHECK (target_annual_vol IS NULL OR target_annual_vol > 0)
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove CHECK constraint before dropping column
    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            DROP CONSTRAINT IF EXISTS chk_target_annual_vol_positive
        """)
    )

    conn.execute(
        text("""
        ALTER TABLE public.dim_executor_config
            DROP COLUMN IF EXISTS target_annual_vol
        """)
    )

    conn.execute(text("DROP TABLE IF EXISTS public.stop_calibrations"))
