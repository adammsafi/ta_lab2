"""phase106_composite_source_type

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
Create Date: 2026-04-01

Phase 106 Plan 01: Custom Composite Indicators -- Schema.

Two schema changes:

1. Add source_type TEXT NULL to public.dim_feature_registry with a CHECK
   constraint limiting values to ('standard', 'proprietary', 'derived', 'ctf',
   'macro').  NULL is allowed for legacy rows that predate this column.

2. Add 6 DOUBLE PRECISION NULL columns to public.features for the proprietary
   composite indicator suite:
     ama_er_regime_signal          -- Kaufman ER quantile x KAMA direction [-1,+1]
     oi_divergence_ctf_agreement   -- HL OI divergence x CTF agreement
     funding_adjusted_momentum     -- Momentum minus cumulative funding z-score
     cross_asset_lead_lag_composite -- IC-weighted lagged predictor combination
     tf_alignment_score            -- Average CTF agreement across TF pairs, centered
     volume_regime_gated_trend     -- Trend signal gated by continuous volume regime

All new columns are nullable (no DEFAULT) to avoid touching existing rows.
Uses ADD COLUMN IF NOT EXISTS and ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS
for idempotency.

ASCII-only comments throughout (Windows cp1252 compatibility).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "z9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "y8z9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. dim_feature_registry: add source_type + CHECK constraint
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        ALTER TABLE public.dim_feature_registry
            ADD COLUMN IF NOT EXISTS source_type TEXT
        """)
    )

    # Add CHECK constraint only if it does not already exist (idempotent).
    conn.execute(
        text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'dim_feature_registry'
                  AND c.conname = 'ck_feature_registry_source_type'
            ) THEN
                ALTER TABLE public.dim_feature_registry
                    ADD CONSTRAINT ck_feature_registry_source_type
                    CHECK (source_type IN (
                        'standard', 'proprietary', 'derived', 'ctf', 'macro'
                    ));
            END IF;
        END
        $$
        """)
    )

    # ------------------------------------------------------------------
    # 2. features: add 6 composite indicator columns
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        ALTER TABLE public.features
            ADD COLUMN IF NOT EXISTS ama_er_regime_signal          DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS oi_divergence_ctf_agreement   DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS funding_adjusted_momentum      DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS cross_asset_lead_lag_composite DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS tf_alignment_score             DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS volume_regime_gated_trend      DOUBLE PRECISION
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop composite columns in reverse order.
    conn.execute(
        text("""
        ALTER TABLE public.features
            DROP COLUMN IF EXISTS volume_regime_gated_trend,
            DROP COLUMN IF EXISTS tf_alignment_score,
            DROP COLUMN IF EXISTS cross_asset_lead_lag_composite,
            DROP COLUMN IF EXISTS funding_adjusted_momentum,
            DROP COLUMN IF EXISTS oi_divergence_ctf_agreement,
            DROP COLUMN IF EXISTS ama_er_regime_signal
        """)
    )

    # Drop CHECK constraint then source_type column.
    conn.execute(
        text("""
        ALTER TABLE public.dim_feature_registry
            DROP CONSTRAINT IF EXISTS ck_feature_registry_source_type,
            DROP COLUMN IF EXISTS source_type
        """)
    )
