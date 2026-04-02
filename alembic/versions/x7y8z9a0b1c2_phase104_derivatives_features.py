"""phase104_derivatives_features

Revision ID: x7y8z9a0b1c2
Revises: u5v6w7x8y9z0
Create Date: 2026-04-01

Phase 104 Plan 01: Crypto-Native Derivatives Indicators -- Input Layer.

Adds 8 nullable derivatives indicator columns (plus 1 SMALLINT) to
public.features.  These columns are the output targets for the Phase 104
derivatives indicator suite.

Columns added:
  oi_mom_14         FLOAT   -- OI momentum (14-period rate of change)
  oi_price_div_z    FLOAT   -- OI-price divergence z-score
  funding_z_14      FLOAT   -- Funding rate z-score (14-period)
  funding_mom_14    FLOAT   -- Funding rate momentum
  vol_oi_regime     SMALLINT -- Volume-OI regime classifier (1-6)
  force_idx_deriv_13 FLOAT  -- OI-weighted Force Index (13-period EMA)
  oi_conc_ratio     FLOAT   -- OI concentration ratio (cross-asset)
  liq_pressure      FLOAT   -- Liquidation pressure proxy (composite)

All columns are nullable (no DEFAULT) so existing rows are unaffected.
Uses ADD COLUMN IF NOT EXISTS for idempotency.

downgrade() drops all 8 columns in reverse order.

ASCII-only comments throughout (Windows cp1252 compatibility).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "x7y8z9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "u5v6w7x8y9z0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ADD COLUMN IF NOT EXISTS -- idempotent, safe to re-run.
    conn.execute(
        text("""
        ALTER TABLE public.features
            ADD COLUMN IF NOT EXISTS oi_mom_14          DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS oi_price_div_z     DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS funding_z_14        DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS funding_mom_14      DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS vol_oi_regime       SMALLINT,
            ADD COLUMN IF NOT EXISTS force_idx_deriv_13  DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS oi_conc_ratio       DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS liq_pressure        DOUBLE PRECISION
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop in reverse order.
    conn.execute(
        text("""
        ALTER TABLE public.features
            DROP COLUMN IF EXISTS liq_pressure,
            DROP COLUMN IF EXISTS oi_conc_ratio,
            DROP COLUMN IF EXISTS force_idx_deriv_13,
            DROP COLUMN IF EXISTS vol_oi_regime,
            DROP COLUMN IF EXISTS funding_mom_14,
            DROP COLUMN IF EXISTS funding_z_14,
            DROP COLUMN IF EXISTS oi_price_div_z,
            DROP COLUMN IF EXISTS oi_mom_14
        """)
    )
