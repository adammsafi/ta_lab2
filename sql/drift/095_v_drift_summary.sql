-- =============================================================================
-- 095_v_drift_summary.sql
-- Reference DDL for v_drift_summary materialized view.
-- Phase 47: Drift Guard
--
-- NOTE: All comments use ASCII-only characters (Windows cp1252 compatibility).
-- Open this file with encoding='utf-8' on Windows.
--
-- Purpose: Aggregated drift summary per (config_id, asset_id, signal_type).
-- Refreshed daily after DriftMonitor writes to cmc_drift_metrics. Provides
-- fast dashboard queries without scanning the full metrics table.
--
-- The unique index on (config_id, asset_id, signal_type) is REQUIRED for
-- REFRESH MATERIALIZED VIEW CONCURRENTLY to work without table locks.
--
-- Downstream consumers: Streamlit dashboard (Phase 52), drift report CLI
-- (Plan 47-05), and ad-hoc operational queries.
-- =============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS public.v_drift_summary AS
SELECT
    config_id,
    asset_id,
    signal_type,

    -- Number of days with a measurement row
    COUNT(*)                                    AS days_monitored,

    -- Number of days where threshold was breached
    COUNT(*) FILTER (WHERE threshold_breach)    AS breach_count,

    -- 5-day tracking error statistics
    AVG(tracking_error_5d)                      AS avg_tracking_error_5d,
    MAX(tracking_error_5d)                      AS max_tracking_error_5d,

    -- 30-day tracking error statistics
    AVG(tracking_error_30d)                     AS avg_tracking_error_30d,
    MAX(tracking_error_30d)                     AS max_tracking_error_30d,

    -- Average absolute P&L difference
    AVG(absolute_pnl_diff)                      AS avg_absolute_pnl_diff,

    -- Average Sharpe divergence
    AVG(sharpe_divergence)                      AS avg_sharpe_divergence,

    -- Most recent measurement date
    MAX(metric_date)                            AS last_metric_date,

    -- Tracking error from most recent measurement row
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
WITH DATA;

-- Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- Covers all 3 GROUP BY columns.
CREATE UNIQUE INDEX IF NOT EXISTS uq_drift_summary
    ON public.v_drift_summary (config_id, asset_id, signal_type);

COMMENT ON MATERIALIZED VIEW public.v_drift_summary IS
    'Aggregated drift summary per (config_id, asset_id, signal_type).'
    ' Refresh daily after DriftMonitor writes: REFRESH MATERIALIZED VIEW CONCURRENTLY public.v_drift_summary.'
    ' Unique index on (config_id, asset_id, signal_type) required for CONCURRENTLY.';
