-- sql/features/040_cmc_returns_daily.sql
-- Daily returns feature table with multiple lookback windows
--
-- Lookback windows derived from dim_timeframe tf_days values:
-- 1D, 3D, 5D, 7D, 14D, 21D, 30D, 63D, 126D, 252D
--
-- Source: cmc_price_bars_1d (daily validated bars)
-- State tracking: cmc_feature_state (feature_type='returns')

CREATE TABLE IF NOT EXISTS public.cmc_returns_daily (
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,

    -- Price context
    close           DOUBLE PRECISION,

    -- Bar-to-bar returns (always computed)
    ret_1d_pct      DOUBLE PRECISION,  -- 1-day percent return
    ret_1d_log      DOUBLE PRECISION,  -- 1-day log return

    -- Multi-day percent returns (lookbacks from dim_timeframe tf_days)
    ret_3d_pct      DOUBLE PRECISION,  -- 3-day percent return
    ret_5d_pct      DOUBLE PRECISION,  -- 5-day percent return
    ret_7d_pct      DOUBLE PRECISION,  -- 7-day percent return
    ret_14d_pct     DOUBLE PRECISION,  -- 14-day percent return
    ret_21d_pct     DOUBLE PRECISION,  -- 21-day percent return
    ret_30d_pct     DOUBLE PRECISION,  -- 30-day percent return
    ret_63d_pct     DOUBLE PRECISION,  -- ~3 months
    ret_126d_pct    DOUBLE PRECISION,  -- ~6 months
    ret_252d_pct    DOUBLE PRECISION,  -- ~1 year

    -- Normalized versions (z-scores)
    ret_1d_pct_zscore   DOUBLE PRECISION,
    ret_7d_pct_zscore   DOUBLE PRECISION,
    ret_30d_pct_zscore  DOUBLE PRECISION,

    -- Data quality flags
    gap_days        INTEGER,           -- Days since previous observation
    is_outlier      BOOLEAN DEFAULT FALSE,

    -- Metadata
    updated_at      TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts)
);

-- Index for time-series lookups
CREATE INDEX IF NOT EXISTS idx_cmc_returns_daily_id_ts
ON public.cmc_returns_daily (id, ts DESC);

-- Comment
COMMENT ON TABLE public.cmc_returns_daily IS
'Daily returns calculated from cmc_price_bars_1d. Lookback windows derived from dim_timeframe tf_days.';
