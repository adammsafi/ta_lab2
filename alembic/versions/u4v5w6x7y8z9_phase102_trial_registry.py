"""phase102_trial_registry

Revision ID: u4v5w6x7y8z9
Revises: t4u5v6w7x8y9
Create Date: 2026-04-01

Phase 102 Plan 01: Indicator Research Framework -- Trial Registry.

Two schema changes:

1. Create public.trial_registry (RESEARCH-01)
   Persistent trial log for multiple-comparison testing of indicators.
   Tracks every IC sweep result with permutation p-values, FDR-adjusted
   p-values, block-bootstrap CI bounds, and IC-IR haircut values.
   Backfilled from ic_results WHERE regime_col='all' AND regime_label='all'
   for the cross-asset baseline sweep.

2. Add haircut_sharpe to public.strategy_bakeoff_results (RESEARCH-02)
   Stores IC-IR haircut-adjusted Sharpe ratio output from Phase 102
   haircut computation pipeline.

Note: All comments use ASCII only (Windows cp1252 compatibility).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "u4v5w6x7y8z9"
down_revision = "t4u5v6w7x8y9"
branch_labels = None
depends_on = None


def upgrade() -> None:  # noqa: PLR0912,PLR0915
    # =========================================================================
    # Part A: Create trial_registry table (RESEARCH-01)
    # Persistent log of every IC sweep trial with statistical gating results.
    # =========================================================================

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.trial_registry (
            trial_id        BIGSERIAL PRIMARY KEY,
            indicator_name  VARCHAR(128) NOT NULL,
            param_set       VARCHAR(256) NOT NULL DEFAULT '',
            tf              VARCHAR(32)  NOT NULL,
            asset_id        INTEGER      NOT NULL,
            venue_id        SMALLINT     NOT NULL DEFAULT 1
                            REFERENCES public.dim_venues(venue_id),
            horizon         SMALLINT     NOT NULL DEFAULT 1,
            return_type     VARCHAR(8)   NOT NULL DEFAULT 'arith',
            ic_observed     DOUBLE PRECISION,
            ic_p_value      DOUBLE PRECISION,
            perm_p_value    DOUBLE PRECISION,
            fdr_p_adjusted  DOUBLE PRECISION,
            passes_fdr      BOOLEAN,
            n_obs           INTEGER,
            bb_ci_lo        DOUBLE PRECISION,
            bb_ci_hi        DOUBLE PRECISION,
            bb_block_len    INTEGER,
            haircut_ic_ir   DOUBLE PRECISION,
            source_table    VARCHAR(64)  NOT NULL DEFAULT 'ic_results',
            sweep_ts        TIMESTAMPTZ  NOT NULL DEFAULT now(),
            UNIQUE (indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type)
        )
        """
    )

    op.execute(
        """
        COMMENT ON TABLE public.trial_registry IS
        'Persistent trial log for multiple-comparison testing of indicators.
Each row represents one (indicator, param_set, tf, asset_id, venue_id, horizon,
return_type) combination evaluated during a sweep run. Columns filled
incrementally: ic_observed/ic_p_value from IC sweep, perm_p_value from
permutation test, fdr_p_adjusted/passes_fdr from batch BH correction,
bb_ci_lo/bb_ci_hi/bb_block_len from block bootstrap, haircut_ic_ir from
IC-IR haircut computation. source_table tracks backfill origin.'
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_trial_registry_indicator_tf
            ON public.trial_registry (indicator_name, tf)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_trial_registry_sweep_ts
            ON public.trial_registry (sweep_ts DESC)
        """
    )

    logger.info("phase102 migration: created trial_registry table with indexes")

    # =========================================================================
    # Part B: Add haircut_sharpe to strategy_bakeoff_results (RESEARCH-02)
    # =========================================================================

    op.execute(
        """
        ALTER TABLE public.strategy_bakeoff_results
            ADD COLUMN IF NOT EXISTS haircut_sharpe DOUBLE PRECISION
        """
    )

    op.execute(
        """
        COMMENT ON COLUMN public.strategy_bakeoff_results.haircut_sharpe IS
        'IC-IR haircut-adjusted Sharpe ratio from Phase 102 haircut computation.
Applies Harvey-Liu-Zhu haircut to deflate Sharpe by IC-IR degradation factor.
NULL until Phase 102 haircut pipeline is run for this row.'
        """
    )

    logger.info("phase102 migration: added haircut_sharpe to strategy_bakeoff_results")

    # =========================================================================
    # Part C: Backfill trial_registry from ic_results
    # Only backfill regime_col='all' AND regime_label='all' (cross-asset baseline).
    # Map alignment_source -> venue_id: all existing sweeps used CMC_AGG (venue_id=1).
    # Set source_table='backfill' to distinguish from live sweep writes.
    # Use horizon=1, return_type='arith' rows only (permutation scope reduction).
    # =========================================================================

    bind = op.get_bind()
    count_result = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM public.ic_results
            WHERE regime_col = 'all'
              AND regime_label = 'all'
              AND horizon = 1
              AND return_type = 'arith'
            """
        )
    )
    source_count = count_result.scalar() or 0
    logger.info(
        "phase102 migration: %d ic_results rows qualify for trial_registry backfill",
        source_count,
    )

    if source_count > 0:
        op.execute(
            """
            INSERT INTO public.trial_registry (
                indicator_name,
                param_set,
                tf,
                asset_id,
                venue_id,
                horizon,
                return_type,
                ic_observed,
                ic_p_value,
                n_obs,
                source_table,
                sweep_ts
            )
            SELECT
                feature                         AS indicator_name,
                ''                              AS param_set,
                tf,
                asset_id,
                CASE
                    WHEN alignment_source = 'multi_tf' THEN 1
                    ELSE 1
                END                             AS venue_id,
                horizon,
                return_type,
                ic                              AS ic_observed,
                ic_p_value,
                n_obs,
                'backfill'                      AS source_table,
                COALESCE(computed_at, now())    AS sweep_ts
            FROM public.ic_results
            WHERE regime_col    = 'all'
              AND regime_label  = 'all'
              AND horizon       = 1
              AND return_type   = 'arith'
            ON CONFLICT (indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type)
            DO NOTHING
            """
        )
        logger.info(
            "phase102 migration: backfill complete (%d source rows processed)",
            source_count,
        )
    else:
        logger.info(
            "phase102 migration: no qualifying ic_results rows -- skipping backfill"
        )


def downgrade() -> None:
    # =========================================================================
    # Reverse Part C + A: Drop trial_registry.
    # =========================================================================
    op.execute("DROP TABLE IF EXISTS public.trial_registry CASCADE")
    logger.info("phase102 downgrade: dropped trial_registry")

    # =========================================================================
    # Reverse Part B: Drop haircut_sharpe from strategy_bakeoff_results.
    # =========================================================================
    op.execute(
        """
        ALTER TABLE public.strategy_bakeoff_results
            DROP COLUMN IF EXISTS haircut_sharpe
        """
    )
    logger.info(
        "phase102 downgrade: removed haircut_sharpe from strategy_bakeoff_results"
    )
