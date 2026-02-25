-- ============================================================================
-- Table: cmc_rolling_extremes
-- Purpose: Rolling high/low over configurable lookback windows
-- ============================================================================
-- Rolling maximum and minimum close price over N-bar windows.
-- Window dimension allows multiple lookback periods per bar (like EMA periods).
--
-- Default target durations: 90d, 180d, 365d, 730d
-- Converted to bars per TF: round(target_days / tf_days_nominal)
-- e.g. 365d on 1D = 365 bars, on 1W = 52 bars, on 1M = 12 bars
--
-- range_position: (close - rolling_low) / (rolling_high - rolling_low)
-- Normalized 0-1 position within the rolling range.
-- 0 = at the low, 1 = at the high (like "% off 52-week high").
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.cmc_rolling_extremes (
    -- Primary key (includes window dimension)
    id                      INTEGER NOT NULL,
    ts                      TIMESTAMPTZ NOT NULL,
    tf                      TEXT NOT NULL,
    alignment_source        TEXT NOT NULL,
    lookback_bars           INTEGER NOT NULL,       -- lookback window in bars
    tf_days                 INTEGER NOT NULL,

    -- Current bar context
    close                   DOUBLE PRECISION,

    -- Rolling high
    rolling_high            DOUBLE PRECISION,       -- max(close) over window
    rolling_high_ts         TIMESTAMPTZ,            -- when rolling high occurred
    bars_since_rolling_high INTEGER,                -- bars since rolling high
    days_since_rolling_high INTEGER,                -- calendar days since rolling high

    -- Rolling low
    rolling_low             DOUBLE PRECISION,       -- min(close) over window
    rolling_low_ts          TIMESTAMPTZ,            -- when rolling low occurred
    bars_since_rolling_low  INTEGER,                -- bars since rolling low
    days_since_rolling_low  INTEGER,                -- calendar days since rolling low

    -- Derived
    range_position          DOUBLE PRECISION,       -- (close - low) / (high - low), 0-1
    dd_from_rolling_high    DOUBLE PRECISION,       -- (close - rolling_high) / rolling_high

    -- Metadata
    updated_at              TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts, tf, alignment_source, lookback_bars)
);

-- Index for per-asset window queries
CREATE INDEX IF NOT EXISTS idx_cmc_rolling_extremes_id_tf_w_ts
ON public.cmc_rolling_extremes (id, tf, alignment_source, lookback_bars, ts DESC);

COMMENT ON TABLE public.cmc_rolling_extremes IS
'Rolling high/low over N-bar windows with range position. lookback_bars is in bars; target durations (90d/180d/365d/730d) converted via tf_days_nominal.';
