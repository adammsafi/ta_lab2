"""paper_trade_executor

Revision ID: 225bf8646f03
Revises: 9e692eb7b762
Create Date: 2026-02-25 00:07:54.982878

Phase 45: Paper Trade Executor schema changes.
Creates 2 new tables, extends cmc_positions PK to include strategy_id,
updates v_cmc_positions_agg, adds executor_processed_at to signal tables,
and seeds V1 signal configs into dim_signals.

Note: All comments use ASCII only (Windows cp1252 compatibility).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "225bf8646f03"
down_revision: Union[str, Sequence[str], None] = "9e692eb7b762"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema -- Phase 45 executor tables, PK extension, and signal seeding."""

    # ------------------------------------------------------------------
    # 1. dim_executor_config: strategy execution parameters
    # ------------------------------------------------------------------
    op.create_table(
        "dim_executor_config",
        sa.Column("config_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("config_name", sa.Text(), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("TRUE"),
            nullable=False,
        ),
        sa.Column(
            "exchange",
            sa.Text(),
            server_default=sa.text("'paper'"),
            nullable=False,
        ),
        sa.Column(
            "environment",
            sa.Text(),
            server_default=sa.text("'sandbox'"),
            nullable=False,
        ),
        sa.Column(
            "sizing_mode",
            sa.Text(),
            server_default=sa.text("'fixed_fraction'"),
            nullable=False,
        ),
        sa.Column(
            "position_fraction",
            sa.Numeric(),
            server_default=sa.text("0.10"),
            nullable=False,
        ),
        sa.Column(
            "max_position_fraction",
            sa.Numeric(),
            server_default=sa.text("0.20"),
            nullable=False,
        ),
        sa.Column(
            "fill_price_mode",
            sa.Text(),
            server_default=sa.text("'next_bar_open'"),
            nullable=False,
        ),
        sa.Column(
            "slippage_mode",
            sa.Text(),
            server_default=sa.text("'lognormal'"),
            nullable=False,
        ),
        sa.Column(
            "slippage_base_bps",
            sa.Numeric(),
            server_default=sa.text("3.0"),
            nullable=False,
        ),
        sa.Column(
            "slippage_noise_sigma",
            sa.Numeric(),
            server_default=sa.text("0.5"),
            nullable=False,
        ),
        sa.Column(
            "volume_impact_factor",
            sa.Numeric(),
            server_default=sa.text("0.1"),
            nullable=False,
        ),
        sa.Column(
            "rejection_rate",
            sa.Numeric(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "partial_fill_rate",
            sa.Numeric(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "execution_delay_bars",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "last_processed_signal_ts", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "cadence_hours",
            sa.Numeric(),
            server_default=sa.text("26.0"),
            nullable=False,
        ),
        # Primary key
        sa.PrimaryKeyConstraint("config_id", name="pk_dim_executor_config"),
        # Unique constraint on config_name
        sa.UniqueConstraint("config_name", name="uq_exec_config_name"),
        # Check constraints
        sa.CheckConstraint(
            "signal_type IN ('ema_crossover', 'rsi_mean_revert', 'atr_breakout')",
            name="chk_exec_config_signal_type",
        ),
        sa.CheckConstraint(
            "exchange IN ('paper', 'coinbase', 'kraken')",
            name="chk_exec_config_exchange",
        ),
        sa.CheckConstraint(
            "environment IN ('sandbox', 'production')",
            name="chk_exec_config_environment",
        ),
        sa.CheckConstraint(
            "sizing_mode IN ('fixed_fraction', 'regime_adjusted', 'signal_strength')",
            name="chk_exec_config_sizing_mode",
        ),
        sa.CheckConstraint(
            "position_fraction > 0 AND position_fraction <= 1",
            name="chk_exec_config_position_fraction",
        ),
        sa.CheckConstraint(
            "fill_price_mode IN ('next_bar_open', 'exchange_mid')",
            name="chk_exec_config_fill_price_mode",
        ),
        sa.CheckConstraint(
            "slippage_mode IN ('zero', 'fixed', 'lognormal')",
            name="chk_exec_config_slippage_mode",
        ),
        sa.CheckConstraint(
            "rejection_rate >= 0 AND rejection_rate <= 1",
            name="chk_exec_config_rejection_rate",
        ),
        sa.CheckConstraint(
            "partial_fill_rate >= 0 AND partial_fill_rate <= 1",
            name="chk_exec_config_partial_fill_rate",
        ),
        schema="public",
    )

    # Indexes on dim_executor_config
    op.create_index(
        "idx_exec_config_active",
        "dim_executor_config",
        ["config_id"],
        schema="public",
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.create_index(
        "idx_exec_config_signal",
        "dim_executor_config",
        ["signal_id"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 2. cmc_executor_run_log: audit log for each executor invocation
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_executor_run_log",
        sa.Column(
            "run_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # config_ids stored as JSON array string (e.g. "[1,2]")
        sa.Column("config_ids", sa.Text(), nullable=False),
        sa.Column(
            "dry_run",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column(
            "replay_historical",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column(
            "signals_read",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "orders_generated",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "fills_processed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "skipped_no_delta",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Primary key
        sa.PrimaryKeyConstraint("run_id", name="pk_cmc_executor_run_log"),
        # Check constraint on status
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'stale_signal')",
            name="chk_exec_run_status",
        ),
        schema="public",
    )

    # Index on cmc_executor_run_log
    op.create_index(
        "idx_exec_run_log_ts",
        "cmc_executor_run_log",
        [sa.text("started_at DESC")],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 3. Extend cmc_positions PK to include strategy_id
    #    ADD COLUMN strategy_id, DROP old PK, ADD new PK
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_positions "
        "ADD COLUMN IF NOT EXISTS strategy_id INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE public.cmc_positions DROP CONSTRAINT IF EXISTS pk_cmc_positions"
    )
    op.execute(
        "ALTER TABLE public.cmc_positions "
        "ADD CONSTRAINT pk_cmc_positions PRIMARY KEY (asset_id, exchange, strategy_id)"
    )

    # ------------------------------------------------------------------
    # 4. Update v_cmc_positions_agg to include strategy_id
    #    Must DROP + CREATE (not CREATE OR REPLACE) when adding a column
    #    because PostgreSQL does not allow reordering view columns in place.
    # ------------------------------------------------------------------
    op.execute("DROP VIEW IF EXISTS public.v_cmc_positions_agg")
    op.execute(
        """
        CREATE VIEW public.v_cmc_positions_agg AS
        SELECT
            asset_id,
            'aggregate'::TEXT AS exchange,
            0 AS strategy_id,
            SUM(quantity) AS quantity,
            CASE
                WHEN SUM(ABS(quantity)) = 0 THEN 0
                ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
            END AS avg_cost_basis,
            SUM(realized_pnl) AS realized_pnl,
            SUM(COALESCE(unrealized_pnl, 0)) AS unrealized_pnl,
            MAX(last_mark_price) AS last_mark_price,
            MAX(last_updated) AS last_updated
        FROM public.cmc_positions
        WHERE exchange != 'aggregate'
        GROUP BY asset_id
        """
    )

    # ------------------------------------------------------------------
    # 5. Add executor_processed_at to signal tables (deduplication watermark)
    # ------------------------------------------------------------------
    for tbl in [
        "cmc_signals_ema_crossover",
        "cmc_signals_rsi_mean_revert",
        "cmc_signals_atr_breakout",
    ]:
        op.execute(
            f"ALTER TABLE public.{tbl} "
            f"ADD COLUMN IF NOT EXISTS executor_processed_at TIMESTAMPTZ NULL"
        )

    # ------------------------------------------------------------------
    # 6. Seed V1 signal configs into dim_signals (INSERT WHERE NOT EXISTS)
    # ------------------------------------------------------------------
    conn = op.get_bind()

    # Seed ema_17_77_long (V1 top-1 robust strategy)
    conn.execute(
        sa.text(
            """
            INSERT INTO public.dim_signals
                (signal_type, signal_name, params, is_active, description, regime_enabled)
            SELECT
                'ema_crossover',
                'ema_17_77_long',
                '{"fast_period": 17, "slow_period": 77, "direction": "long"}'::jsonb,
                TRUE,
                'EMA crossover 17/77 long -- V1 top-1 robust strategy (4/4 weighting schemes)',
                TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM public.dim_signals WHERE signal_name = 'ema_17_77_long'
            )
            """
        )
    )

    # ema_21_50_long already seeded in Phase 43 baseline (signal_id=2)
    # Insert only if missing (guards re-entrancy)
    conn.execute(
        sa.text(
            """
            INSERT INTO public.dim_signals
                (signal_type, signal_name, params, is_active, description, regime_enabled)
            SELECT
                'ema_crossover',
                'ema_21_50_long',
                '{"fast_period": 21, "slow_period": 50, "direction": "long"}'::jsonb,
                TRUE,
                'EMA crossover 21/50 long -- V1 top-2 robust strategy (3/4 weighting schemes)',
                TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM public.dim_signals WHERE signal_name = 'ema_21_50_long'
            )
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema -- reverse all Phase 45 changes in reverse order."""

    # ------------------------------------------------------------------
    # 6-reverse. Remove V1 signal seeds (only the ones we added)
    # ------------------------------------------------------------------
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM public.dim_signals WHERE signal_name = 'ema_17_77_long'")
    )
    # Note: ema_21_50_long (signal_id=2) was pre-existing; only remove if we added it
    # Safe to leave it -- it was already there before Phase 45

    # ------------------------------------------------------------------
    # 5-reverse. Remove executor_processed_at from signal tables
    # ------------------------------------------------------------------
    for tbl in [
        "cmc_signals_ema_crossover",
        "cmc_signals_rsi_mean_revert",
        "cmc_signals_atr_breakout",
    ]:
        op.execute(
            f"ALTER TABLE public.{tbl} DROP COLUMN IF EXISTS executor_processed_at"
        )

    # ------------------------------------------------------------------
    # 4-reverse. Restore v_cmc_positions_agg without strategy_id
    #    Must DROP + CREATE when removing a column from view definition.
    # ------------------------------------------------------------------
    op.execute("DROP VIEW IF EXISTS public.v_cmc_positions_agg")
    op.execute(
        """
        CREATE VIEW public.v_cmc_positions_agg AS
        SELECT
            asset_id,
            'aggregate'::TEXT AS exchange,
            SUM(quantity) AS quantity,
            CASE
                WHEN SUM(ABS(quantity)) = 0 THEN 0
                ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
            END AS avg_cost_basis,
            SUM(realized_pnl) AS realized_pnl,
            SUM(COALESCE(unrealized_pnl, 0)) AS unrealized_pnl,
            MAX(last_mark_price) AS last_mark_price,
            MAX(last_updated) AS last_updated
        FROM public.cmc_positions
        WHERE exchange != 'aggregate'
        GROUP BY asset_id
        """
    )

    # ------------------------------------------------------------------
    # 3-reverse. Restore cmc_positions PK to (asset_id, exchange)
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_positions DROP CONSTRAINT IF EXISTS pk_cmc_positions"
    )
    op.execute(
        "ALTER TABLE public.cmc_positions "
        "ADD CONSTRAINT pk_cmc_positions PRIMARY KEY (asset_id, exchange)"
    )
    op.execute("ALTER TABLE public.cmc_positions DROP COLUMN IF EXISTS strategy_id")

    # ------------------------------------------------------------------
    # 2-reverse. Drop cmc_executor_run_log
    # ------------------------------------------------------------------
    op.drop_table("cmc_executor_run_log", schema="public")

    # ------------------------------------------------------------------
    # 1-reverse. Drop dim_executor_config
    # ------------------------------------------------------------------
    op.drop_table("dim_executor_config", schema="public")
