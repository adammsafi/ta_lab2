-- =============================================================================
-- 094_drift_metrics.sql
-- Reference DDL for drift_metrics table.
-- Phase 47: Drift Guard
--
-- NOTE: All comments use ASCII-only characters (Windows cp1252 compatibility).
-- Open this file with encoding='utf-8' on Windows.
--
-- Purpose: Store daily per-strategy drift measurements produced by the drift
-- guard monitor. One row per (metric_date, config_id, asset_id). Contains raw
-- P&L comparison, trade matching counts, tracking error metrics, Sharpe
-- divergence, threshold breach flag, and 8-source attribution breakdown.
--
-- This table is the primary output of Plan 47-03 (DriftMonitor). Downstream
-- consumers: v_drift_summary (095), Streamlit dashboard (Phase 52), and the
-- weekly drift report CLI (Plan 47-05).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.drift_metrics (

    -- -------------------------------------------------------------------------
    -- Primary key and administrative columns
    -- -------------------------------------------------------------------------
    metric_id           UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_date         DATE            NOT NULL,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- -------------------------------------------------------------------------
    -- Scope: which executor config, asset, and signal type was measured
    -- -------------------------------------------------------------------------
    config_id           INTEGER         NOT NULL,   -- FK concept: dim_executor_config
    asset_id            INTEGER         NOT NULL,
    signal_type         TEXT            NOT NULL,

    -- -------------------------------------------------------------------------
    -- Backtest replay run references
    -- -------------------------------------------------------------------------
    pit_replay_run_id   UUID            NULL,   -- FK concept: backtest_runs (PIT replay)
    cur_replay_run_id   UUID            NULL,   -- FK concept: backtest_runs (current-data replay)

    -- -------------------------------------------------------------------------
    -- Trade matching statistics
    -- -------------------------------------------------------------------------
    paper_trade_count   INTEGER         NOT NULL DEFAULT 0,
    replay_trade_count  INTEGER         NOT NULL DEFAULT 0,
    unmatched_paper     INTEGER         NOT NULL DEFAULT 0,
    unmatched_replay    INTEGER         NOT NULL DEFAULT 0,

    -- -------------------------------------------------------------------------
    -- Cumulative P&L comparison
    -- -------------------------------------------------------------------------
    paper_cumulative_pnl            NUMERIC NULL,
    replay_pit_cumulative_pnl       NUMERIC NULL,   -- Point-in-time replay P&L
    replay_cur_cumulative_pnl       NUMERIC NULL,   -- Current-data replay P&L
    absolute_pnl_diff               NUMERIC NULL,   -- abs(paper - replay_pit)
    data_revision_pnl_diff          NUMERIC NULL,   -- abs(replay_cur - replay_pit)

    -- -------------------------------------------------------------------------
    -- Tracking error and Sharpe metrics
    -- -------------------------------------------------------------------------
    tracking_error_5d               NUMERIC NULL,   -- Rolling 5-day tracking error
    tracking_error_30d              NUMERIC NULL,   -- Rolling 30-day tracking error
    paper_sharpe                    NUMERIC NULL,
    replay_sharpe                   NUMERIC NULL,
    sharpe_divergence               NUMERIC NULL,   -- abs(paper_sharpe - replay_sharpe)

    -- -------------------------------------------------------------------------
    -- Threshold breach flag
    -- -------------------------------------------------------------------------
    threshold_breach                BOOLEAN NOT NULL DEFAULT FALSE,
    drift_pct_of_threshold          NUMERIC NULL,   -- tracking_error / threshold * 100

    -- -------------------------------------------------------------------------
    -- Attribution breakdown (6 sources + baseline + unexplained)
    -- Each delta column holds the signed P&L contribution from that source.
    -- -------------------------------------------------------------------------
    attr_baseline_pnl               NUMERIC NULL,   -- Replay baseline P&L
    attr_fee_delta                  NUMERIC NULL,   -- Fee model difference
    attr_slippage_delta             NUMERIC NULL,   -- Fill price slippage difference
    attr_timing_delta               NUMERIC NULL,   -- Signal timing execution delay
    attr_data_revision_delta        NUMERIC NULL,   -- PIT vs current data revision
    attr_sizing_delta               NUMERIC NULL,   -- Position sizing / rounding drift
    attr_regime_delta               NUMERIC NULL,   -- Regime label divergence at execution
    attr_unexplained                NUMERIC NULL,   -- Residual after all attribution

    -- -------------------------------------------------------------------------
    -- Unique constraint: one row per (date, config, asset)
    -- signal_type is included in the GROUP BY of v_drift_summary but not
    -- here since config_id already scopes to a single signal configuration.
    -- -------------------------------------------------------------------------
    CONSTRAINT uq_drift_metrics_scope UNIQUE (metric_date, config_id, asset_id)
);

-- Descending date index for recent-first queries
CREATE INDEX IF NOT EXISTS idx_drift_metrics_date
    ON public.drift_metrics (metric_date DESC);

-- Config + date index for per-executor lookups
CREATE INDEX IF NOT EXISTS idx_drift_metrics_config
    ON public.drift_metrics (config_id, metric_date DESC);

-- Partial index on breaches only (sparse, low cardinality)
CREATE INDEX IF NOT EXISTS idx_drift_metrics_breach
    ON public.drift_metrics (threshold_breach, metric_date DESC)
    WHERE threshold_breach = TRUE;

COMMENT ON TABLE public.drift_metrics IS
    'Daily per-strategy drift measurements: trade matching, P&L comparison,'
    ' tracking error, Sharpe divergence, threshold breach flag,'
    ' and 8-source attribution breakdown. Written by DriftMonitor (Plan 47-03).';
