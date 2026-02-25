"""drift_guard

Revision ID: ac4cf1223ec7
Revises: b5178d671e38
Create Date: 2026-02-25 19:12:00.000000

Schema changes for Phase 47 (Drift Guard):

1. cmc_drift_metrics: New table for daily per-strategy drift measurements.
   Trade matching counts, P&L comparison, tracking error, Sharpe divergence,
   threshold breach flag, and 8-source attribution breakdown.

2. v_drift_summary: Materialized view aggregating cmc_drift_metrics by
   (config_id, asset_id, signal_type). Unique index required for CONCURRENTLY.

3. dim_risk_state: Add 4 drift-pause columns: drift_paused, drift_paused_at,
   drift_paused_reason, drift_auto_escalate_after_days.

4. dim_risk_limits: Add 3 drift threshold columns: tracking error thresholds
   (5d, 30d) and drift window days.

5. dim_executor_config: Add fee_bps NUMERIC column for cost model and drift
   attribution (Plans 47-03 and 47-04).

6. cmc_risk_events: Extend chk_risk_events_type with 3 new drift event types
   and chk_risk_events_source with 'drift_monitor'.

7. cmc_executor_run_log: Add data_snapshot JSONB column for point-in-time
   input state snapshot needed by replay engine (Plan 47-02).

Note: All comments use ASCII only (Windows cp1252 compatibility).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ac4cf1223ec7"
down_revision: Union[str, Sequence[str], None] = "b5178d671e38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema -- apply all Phase 47 Drift Guard DDL changes."""

    # ------------------------------------------------------------------
    # 1. cmc_drift_metrics: daily per-strategy drift measurements
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_drift_metrics",
        # Administrative columns
        sa.Column(
            "metric_id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Scope columns
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        # Backtest replay run references
        sa.Column("pit_replay_run_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("cur_replay_run_id", postgresql.UUID(as_uuid=False), nullable=True),
        # Trade matching statistics
        sa.Column(
            "paper_trade_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "replay_trade_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "unmatched_paper",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "unmatched_replay",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        # Cumulative P&L comparison
        sa.Column("paper_cumulative_pnl", sa.Numeric(), nullable=True),
        sa.Column("replay_pit_cumulative_pnl", sa.Numeric(), nullable=True),
        sa.Column("replay_cur_cumulative_pnl", sa.Numeric(), nullable=True),
        sa.Column("absolute_pnl_diff", sa.Numeric(), nullable=True),
        sa.Column("data_revision_pnl_diff", sa.Numeric(), nullable=True),
        # Tracking error and Sharpe metrics
        sa.Column("tracking_error_5d", sa.Numeric(), nullable=True),
        sa.Column("tracking_error_30d", sa.Numeric(), nullable=True),
        sa.Column("paper_sharpe", sa.Numeric(), nullable=True),
        sa.Column("replay_sharpe", sa.Numeric(), nullable=True),
        sa.Column("sharpe_divergence", sa.Numeric(), nullable=True),
        # Threshold breach flag
        sa.Column(
            "threshold_breach",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column("drift_pct_of_threshold", sa.Numeric(), nullable=True),
        # Attribution breakdown columns (8 sources)
        sa.Column("attr_baseline_pnl", sa.Numeric(), nullable=True),
        sa.Column("attr_fee_delta", sa.Numeric(), nullable=True),
        sa.Column("attr_slippage_delta", sa.Numeric(), nullable=True),
        sa.Column("attr_timing_delta", sa.Numeric(), nullable=True),
        sa.Column("attr_data_revision_delta", sa.Numeric(), nullable=True),
        sa.Column("attr_sizing_delta", sa.Numeric(), nullable=True),
        sa.Column("attr_regime_delta", sa.Numeric(), nullable=True),
        sa.Column("attr_unexplained", sa.Numeric(), nullable=True),
        # Constraints
        sa.PrimaryKeyConstraint("metric_id", name="pk_cmc_drift_metrics"),
        sa.UniqueConstraint(
            "metric_date",
            "config_id",
            "asset_id",
            name="uq_drift_metrics_scope",
        ),
    )

    # Indexes on cmc_drift_metrics
    op.create_index(
        "idx_drift_metrics_date",
        "cmc_drift_metrics",
        [sa.text("metric_date DESC")],
    )
    op.create_index(
        "idx_drift_metrics_config",
        "cmc_drift_metrics",
        ["config_id", sa.text("metric_date DESC")],
    )
    op.create_index(
        "idx_drift_metrics_breach",
        "cmc_drift_metrics",
        ["threshold_breach", sa.text("metric_date DESC")],
        postgresql_where=sa.text("threshold_breach = TRUE"),
    )

    op.execute(
        sa.text(
            "COMMENT ON TABLE public.cmc_drift_metrics IS"
            " 'Daily per-strategy drift measurements: trade matching, P&L comparison,"
            " tracking error, Sharpe divergence, threshold breach flag,"
            " and 8-source attribution breakdown. Written by DriftMonitor (Plan 47-03).'"
        )
    )

    # ------------------------------------------------------------------
    # 2. v_drift_summary: materialized view aggregating drift metrics
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
CREATE MATERIALIZED VIEW IF NOT EXISTS public.v_drift_summary AS
SELECT
    config_id,
    asset_id,
    signal_type,
    COUNT(*)                                    AS days_monitored,
    COUNT(*) FILTER (WHERE threshold_breach)    AS breach_count,
    AVG(tracking_error_5d)                      AS avg_tracking_error_5d,
    MAX(tracking_error_5d)                      AS max_tracking_error_5d,
    AVG(tracking_error_30d)                     AS avg_tracking_error_30d,
    MAX(tracking_error_30d)                     AS max_tracking_error_30d,
    AVG(absolute_pnl_diff)                      AS avg_absolute_pnl_diff,
    AVG(sharpe_divergence)                      AS avg_sharpe_divergence,
    MAX(metric_date)                            AS last_metric_date,
    (
        SELECT dm2.tracking_error_5d
        FROM public.cmc_drift_metrics dm2
        WHERE dm2.config_id    = dm.config_id
          AND dm2.asset_id     = dm.asset_id
          AND dm2.signal_type  = dm.signal_type
        ORDER BY dm2.metric_date DESC
        LIMIT 1
    )                                           AS current_tracking_error_5d
FROM public.cmc_drift_metrics dm
GROUP BY
    config_id,
    asset_id,
    signal_type
WITH DATA
"""
        )
    )

    # Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
    # Must cover all 3 GROUP BY columns.
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_drift_summary"
            " ON public.v_drift_summary (config_id, asset_id, signal_type)"
        )
    )

    op.execute(
        sa.text(
            "COMMENT ON MATERIALIZED VIEW public.v_drift_summary IS"
            " 'Aggregated drift summary per (config_id, asset_id, signal_type)."
            " Refresh daily: REFRESH MATERIALIZED VIEW CONCURRENTLY public.v_drift_summary."
            " Unique index on (config_id, asset_id, signal_type) required for CONCURRENTLY.'"
        )
    )

    # ------------------------------------------------------------------
    # 3. dim_risk_state: add drift-pause columns
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
ALTER TABLE public.dim_risk_state
  ADD COLUMN IF NOT EXISTS drift_paused
      BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS drift_paused_at
      TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS drift_paused_reason
      TEXT NULL,
  ADD COLUMN IF NOT EXISTS drift_auto_escalate_after_days
      INTEGER NOT NULL DEFAULT 7
"""
        )
    )

    # ------------------------------------------------------------------
    # 4. dim_risk_limits: add drift threshold columns
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
ALTER TABLE public.dim_risk_limits
  ADD COLUMN IF NOT EXISTS drift_tracking_error_threshold_5d
      NUMERIC NULL DEFAULT 0.015,
  ADD COLUMN IF NOT EXISTS drift_tracking_error_threshold_30d
      NUMERIC NULL DEFAULT 0.005,
  ADD COLUMN IF NOT EXISTS drift_window_days
      INTEGER NULL DEFAULT 5
"""
        )
    )

    # Seed drift thresholds on the existing portfolio-wide row
    op.execute(
        sa.text(
            "UPDATE public.dim_risk_limits"
            " SET drift_tracking_error_threshold_5d  = 0.015,"
            "     drift_tracking_error_threshold_30d = 0.005,"
            "     drift_window_days                  = 5"
            " WHERE asset_id IS NULL AND strategy_id IS NULL"
        )
    )

    # ------------------------------------------------------------------
    # 5. dim_executor_config: add fee_bps column
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "ALTER TABLE public.dim_executor_config"
            " ADD COLUMN IF NOT EXISTS fee_bps NUMERIC NOT NULL DEFAULT 0"
        )
    )
    op.execute(
        sa.text(
            "COMMENT ON COLUMN public.dim_executor_config.fee_bps IS"
            " 'Trading fee in basis points."
            " Plans 47-03/47-04 use this for CostModel and drift attribution.'"
        )
    )

    # ------------------------------------------------------------------
    # 6. cmc_risk_events: extend CHECK constraints with drift event types
    # ------------------------------------------------------------------

    # Drop and recreate event_type CHECK constraint
    # Original 10 types + 3 new drift types = 13 total
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " DROP CONSTRAINT IF EXISTS chk_risk_events_type"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " ADD CONSTRAINT chk_risk_events_type CHECK ("
            "event_type IN ("
            "'kill_switch_activated', 'kill_switch_disabled',"
            " 'position_cap_scaled', 'position_cap_blocked',"
            " 'daily_loss_stop_triggered', 'circuit_breaker_tripped',"
            " 'circuit_breaker_reset', 'override_created',"
            " 'override_applied', 'override_reverted',"
            " 'drift_pause_activated', 'drift_pause_disabled', 'drift_escalated'"
            "))"
        )
    )

    # Drop and recreate trigger_source CHECK constraint
    # Original 4 sources + 1 new = 5 total
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " DROP CONSTRAINT IF EXISTS chk_risk_events_source"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " ADD CONSTRAINT chk_risk_events_source CHECK ("
            "trigger_source IN ("
            "'manual', 'daily_loss_stop', 'circuit_breaker', 'system',"
            " 'drift_monitor'"
            "))"
        )
    )

    # ------------------------------------------------------------------
    # 7. cmc_executor_run_log: add data_snapshot JSONB column
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_executor_run_log"
            " ADD COLUMN IF NOT EXISTS data_snapshot JSONB NULL"
        )
    )
    op.execute(
        sa.text(
            "COMMENT ON COLUMN public.cmc_executor_run_log.data_snapshot IS"
            " 'Point-in-time input data snapshot: latest bar ts per asset,"
            " feature state at executor run time. Used by drift guard replay engine"
            " (Plan 47-02) to reconstruct PIT data visibility.'"
        )
    )


def downgrade() -> None:
    """Downgrade schema -- reverse all Phase 47 Drift Guard changes."""

    # 7-reverse: drop data_snapshot from cmc_executor_run_log
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_executor_run_log"
            " DROP COLUMN IF EXISTS data_snapshot"
        )
    )

    # 6-reverse: restore original CHECK constraints on cmc_risk_events
    # Restore chk_risk_events_source (remove drift_monitor)
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " DROP CONSTRAINT IF EXISTS chk_risk_events_source"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " ADD CONSTRAINT chk_risk_events_source CHECK ("
            "trigger_source IN ("
            "'manual', 'daily_loss_stop', 'circuit_breaker', 'system'"
            "))"
        )
    )

    # Restore chk_risk_events_type (remove 3 drift event types)
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " DROP CONSTRAINT IF EXISTS chk_risk_events_type"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE public.cmc_risk_events"
            " ADD CONSTRAINT chk_risk_events_type CHECK ("
            "event_type IN ("
            "'kill_switch_activated', 'kill_switch_disabled',"
            " 'position_cap_scaled', 'position_cap_blocked',"
            " 'daily_loss_stop_triggered', 'circuit_breaker_tripped',"
            " 'circuit_breaker_reset', 'override_created',"
            " 'override_applied', 'override_reverted'"
            "))"
        )
    )

    # 5-reverse: drop fee_bps from dim_executor_config
    op.execute(
        sa.text("ALTER TABLE public.dim_executor_config DROP COLUMN IF EXISTS fee_bps")
    )

    # 4-reverse: drop drift threshold columns from dim_risk_limits
    op.execute(
        sa.text(
            "ALTER TABLE public.dim_risk_limits"
            " DROP COLUMN IF EXISTS drift_tracking_error_threshold_5d,"
            " DROP COLUMN IF EXISTS drift_tracking_error_threshold_30d,"
            " DROP COLUMN IF EXISTS drift_window_days"
        )
    )

    # 3-reverse: drop drift-pause columns from dim_risk_state
    op.execute(
        sa.text(
            "ALTER TABLE public.dim_risk_state"
            " DROP COLUMN IF EXISTS drift_paused,"
            " DROP COLUMN IF EXISTS drift_paused_at,"
            " DROP COLUMN IF EXISTS drift_paused_reason,"
            " DROP COLUMN IF EXISTS drift_auto_escalate_after_days"
        )
    )

    # 2-reverse: drop v_drift_summary materialized view
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS public.v_drift_summary"))

    # 1-reverse: drop cmc_drift_metrics table (indexes dropped automatically)
    op.drop_table("cmc_drift_metrics")
