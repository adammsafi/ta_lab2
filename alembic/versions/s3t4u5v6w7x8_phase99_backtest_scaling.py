"""phase99_backtest_scaling

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-03-31

Phase 99 Plan 01: Backtest Scaling schema changes.

Three schema changes:

1. Create public.mass_backtest_state (BT-01)
   Resume-safe orchestration table. Tracks completion of each
   (strategy, asset, params, tf, cost) combination so run_mass_backtest.py
   --resume can skip already-completed rows and restart interrupted runs.

2. Partition public.backtest_trades by strategy_name (BT-02)
   Before scaling to 20-40M rows the table must be LIST-partitioned on
   strategy_name. Existing data is migrated to the new partitioned table.
   The FK to backtest_runs is deliberately dropped (partitioned tables
   do not support row-level FK constraints in PostgreSQL < 16 and the
   volume makes cross-table lookups prohibitive).

3. Add mc_sharpe_lo / mc_sharpe_hi / mc_sharpe_median to
   public.strategy_bakeoff_results (BT-04)
   The bakeoff pipeline writes exclusively to strategy_bakeoff_results
   and stores fold-level Sharpe values in fold_metrics_json. These columns
   hold the CI bounds from fold-level bootstrap sampling.
   NOTE: backtest_metrics already has mc_sharpe_* columns from migration
   c3d4e5f6a1b2 — those are left untouched.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "s3t4u5v6w7x8"
down_revision = "r2s3t4u5v6w7"
branch_labels = None
depends_on = None

# Named strategy partitions for backtest_trades.
# Add new strategy names here when new generators are introduced.
_STRATEGY_PARTITIONS = [
    "ema_trend",
    "rsi_mean_revert",
    "breakout_atr",
    "macd_crossover",
    "ama_momentum",
    "ama_mean_reversion",
    "ama_regime_conditional",
    "ctf_threshold",
]


def upgrade() -> None:  # noqa: PLR0912,PLR0915
    # =========================================================================
    # Part A: Create mass_backtest_state (BT-01)
    # Resume-safe orchestration table.
    # =========================================================================

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.mass_backtest_state (
            id              SERIAL PRIMARY KEY,
            strategy_name   TEXT NOT NULL,
            asset_id        INTEGER NOT NULL,
            params_hash     TEXT NOT NULL,
            tf              TEXT NOT NULL,
            cost_bps        NUMERIC NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            error_msg       TEXT,
            created_at      TIMESTAMPTZ DEFAULT now(),
            UNIQUE (strategy_name, asset_id, params_hash, tf, cost_bps),
            CHECK (status IN ('pending', 'running', 'done', 'error'))
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mass_backtest_state_status
            ON public.mass_backtest_state (status)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mass_backtest_state_strategy
            ON public.mass_backtest_state (strategy_name, asset_id)
        """
    )

    op.execute(
        """
        COMMENT ON TABLE public.mass_backtest_state IS
        'Resume-safe orchestration state for run_mass_backtest.py. Each row
represents one (strategy_name, asset_id, params_hash, tf, cost_bps) work unit.
status transitions: pending -> running -> done | error.
--resume mode skips rows with status=done and restarts status=running rows
that were interrupted (stale running rows indicate a previous crash).'
        """
    )

    logger.info("phase99 migration: created mass_backtest_state table")

    # =========================================================================
    # Part B: Partition backtest_trades by strategy_name (BT-02)
    # =========================================================================

    # ------------------------------------------------------------------
    # Step B-1: Check existing row count for logging.
    # ------------------------------------------------------------------
    bind = op.get_bind()
    count_result = bind.execute(sa.text("SELECT COUNT(*) FROM public.backtest_trades"))
    row_count = count_result.scalar() or 0
    logger.info(
        "phase99 migration: backtest_trades has %d rows before partitioning",
        row_count,
    )

    # ------------------------------------------------------------------
    # Step B-2: Add strategy_name column (nullable initially).
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE public.backtest_trades
            ADD COLUMN IF NOT EXISTS strategy_name TEXT
        """
    )

    # ------------------------------------------------------------------
    # Step B-3: Populate strategy_name from backtest_runs.signal_type.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE public.backtest_trades bt
        SET    strategy_name = br.signal_type
        FROM   public.backtest_runs br
        WHERE  bt.run_id = br.run_id
          AND  bt.strategy_name IS NULL
        """
    )

    # ------------------------------------------------------------------
    # Step B-4: Set orphan rows (no matching run) to 'unknown'.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE public.backtest_trades
        SET    strategy_name = 'unknown'
        WHERE  strategy_name IS NULL
        """
    )

    # ------------------------------------------------------------------
    # Step B-5: Make strategy_name NOT NULL.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE public.backtest_trades
            ALTER COLUMN strategy_name SET NOT NULL
        """
    )

    # ------------------------------------------------------------------
    # Step B-6: Rename existing table to backtest_trades_old.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE public.backtest_trades
            RENAME TO backtest_trades_old
        """
    )

    # ------------------------------------------------------------------
    # Step B-7: Create new partitioned table.
    # Primary key must include the partition key (strategy_name).
    # FK to backtest_runs deliberately omitted (partitioned tables do not
    # support referential integrity constraints in PostgreSQL < 16, and
    # at 20-40M rows the FK check overhead is unacceptable).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE public.backtest_trades (
            trade_id        UUID NOT NULL DEFAULT gen_random_uuid(),
            run_id          UUID NOT NULL,
            strategy_name   TEXT NOT NULL,

            -- Trade details
            entry_ts        TIMESTAMPTZ NOT NULL,
            entry_price     NUMERIC NOT NULL,
            exit_ts         TIMESTAMPTZ,
            exit_price      NUMERIC,
            direction       TEXT NOT NULL,
            size            NUMERIC,

            -- Results
            pnl_pct         NUMERIC,
            pnl_dollars     NUMERIC,

            -- Costs
            fees_paid       NUMERIC,
            slippage_cost   NUMERIC,

            created_at      TIMESTAMPTZ DEFAULT now(),

            CHECK (direction IN ('long', 'short')),
            PRIMARY KEY (trade_id, strategy_name)
        ) PARTITION BY LIST (strategy_name)
        """
    )

    # ------------------------------------------------------------------
    # Step B-8: Create default partition (catches any strategy name not
    # listed explicitly, including 'unknown' and future strategies).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE public.backtest_trades_default
            PARTITION OF public.backtest_trades DEFAULT
        """
    )

    # ------------------------------------------------------------------
    # Step B-9: Create named partitions for known strategies.
    # ------------------------------------------------------------------
    for strategy in _STRATEGY_PARTITIONS:
        # Sanitize partition table name (replace hyphens, lowercase).
        part_name = strategy.lower().replace("-", "_")
        op.execute(
            f"""
            CREATE TABLE public.backtest_trades_{part_name}
                PARTITION OF public.backtest_trades
                FOR VALUES IN ('{strategy}')
            """
        )
        logger.info(
            "phase99 migration: created backtest_trades partition for strategy '%s'",
            strategy,
        )

    # ------------------------------------------------------------------
    # Step B-10: Re-insert data from old table.
    # ------------------------------------------------------------------
    if row_count > 0:
        logger.info(
            "phase99 migration: copying %d rows from backtest_trades_old ...",
            row_count,
        )
        op.execute(
            """
            INSERT INTO public.backtest_trades (
                trade_id,
                run_id,
                strategy_name,
                entry_ts,
                entry_price,
                exit_ts,
                exit_price,
                direction,
                size,
                pnl_pct,
                pnl_dollars,
                fees_paid,
                slippage_cost,
                created_at
            )
            SELECT
                trade_id,
                run_id,
                strategy_name,
                entry_ts,
                entry_price,
                exit_ts,
                exit_price,
                direction,
                size,
                pnl_pct,
                pnl_dollars,
                fees_paid,
                slippage_cost,
                created_at
            FROM public.backtest_trades_old
            """
        )
        logger.info("phase99 migration: data copy complete")
    else:
        logger.info("phase99 migration: backtest_trades_old is empty, no data to copy")

    # ------------------------------------------------------------------
    # Step B-11: Recreate indexes on the partitioned table.
    # Indexes on partitioned tables propagate to all partitions.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
            ON public.backtest_trades (run_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_backtest_trades_entry_ts
            ON public.backtest_trades (entry_ts)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_backtest_trades_direction
            ON public.backtest_trades (direction)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_backtest_trades_strategy_name
            ON public.backtest_trades (strategy_name)
        """
    )

    # ------------------------------------------------------------------
    # Step B-12: Add comments.
    # ------------------------------------------------------------------
    op.execute(
        """
        COMMENT ON TABLE public.backtest_trades IS
        'Individual trade records from backtest execution. LIST-partitioned by
strategy_name for scalable storage (target: 20-40M rows across all strategies).
Each row is one complete trade (entry + exit) with PnL and costs.
FK to backtest_runs deliberately omitted after partitioning (PostgreSQL
partitioned tables do not support row-level FK constraints; join via run_id).'
        """
    )

    logger.info(
        "phase99 migration: backtest_trades partitioning complete "
        "(%d named partitions + default)",
        len(_STRATEGY_PARTITIONS),
    )

    # =========================================================================
    # Part C: Add MC Sharpe CI columns to strategy_bakeoff_results (BT-04)
    # NOTE: These go on strategy_bakeoff_results, NOT on backtest_metrics.
    # backtest_metrics already has mc_sharpe_* from migration c3d4e5f6a1b2.
    # =========================================================================

    op.execute(
        """
        ALTER TABLE public.strategy_bakeoff_results
            ADD COLUMN IF NOT EXISTS mc_sharpe_lo     DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS mc_sharpe_hi     DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS mc_sharpe_median DOUBLE PRECISION
        """
    )

    op.execute(
        """
        COMMENT ON COLUMN public.strategy_bakeoff_results.mc_sharpe_lo IS
        'Monte Carlo 5th-percentile Sharpe ratio (lower bound of 90% CI).
Computed by fold-level bootstrap: resample fold_metrics_json Sharpe values
with replacement N=1000 times and take 5th/95th percentiles.
NULL until run_mass_backtest.py --mc-ci is run for this row.'
        """
    )

    op.execute(
        """
        COMMENT ON COLUMN public.strategy_bakeoff_results.mc_sharpe_hi IS
        'Monte Carlo 95th-percentile Sharpe ratio (upper bound of 90% CI).
Computed by fold-level bootstrap from fold_metrics_json Sharpe values.
NULL until run_mass_backtest.py --mc-ci is run for this row.'
        """
    )

    op.execute(
        """
        COMMENT ON COLUMN public.strategy_bakeoff_results.mc_sharpe_median IS
        'Monte Carlo median Sharpe ratio across all bootstrap resamples.
More robust than the point estimate (sharpe_mean) for noisy return series.
NULL until run_mass_backtest.py --mc-ci is run for this row.'
        """
    )

    logger.info(
        "phase99 migration: added mc_sharpe_lo/hi/median to strategy_bakeoff_results"
    )


def downgrade() -> None:
    # =========================================================================
    # Reverse Part C: Drop MC Sharpe CI columns from strategy_bakeoff_results.
    # =========================================================================
    op.execute(
        """
        ALTER TABLE public.strategy_bakeoff_results
            DROP COLUMN IF EXISTS mc_sharpe_lo,
            DROP COLUMN IF EXISTS mc_sharpe_hi,
            DROP COLUMN IF EXISTS mc_sharpe_median
        """
    )

    logger.info(
        "phase99 downgrade: removed mc_sharpe_lo/hi/median from strategy_bakeoff_results"
    )

    # =========================================================================
    # Reverse Part B: Restore original non-partitioned backtest_trades.
    # =========================================================================

    # Drop the partitioned table (cascades to all named partitions and default).
    op.execute("DROP TABLE IF EXISTS public.backtest_trades CASCADE")

    # Rename old table back.
    op.execute(
        """
        ALTER TABLE IF EXISTS public.backtest_trades_old
            RENAME TO backtest_trades
        """
    )

    # Drop the strategy_name column added during upgrade.
    op.execute(
        """
        ALTER TABLE IF EXISTS public.backtest_trades
            DROP COLUMN IF EXISTS strategy_name
        """
    )

    logger.info("phase99 downgrade: restored original non-partitioned backtest_trades")

    # =========================================================================
    # Reverse Part A: Drop mass_backtest_state.
    # =========================================================================
    op.execute("DROP TABLE IF EXISTS public.mass_backtest_state CASCADE")

    logger.info("phase99 downgrade: dropped mass_backtest_state")
