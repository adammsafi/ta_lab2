-- ============================================================================
-- Table: cmc_vol_daily
-- Purpose: Daily volatility measures from OHLC bars
-- ============================================================================
-- Volatility Estimators:
--   Parkinson (1980): Range-based vol (high/low)
--   Garman-Klass (1980): OHLC-based vol estimator
--   Rogers-Satchell (1991): Drift-independent vol estimator
--   ATR (Wilder): Average True Range
--   Rolling historical: Log return standard deviation
--
-- All volatility measures annualized using sqrt(252) for trading days.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.cmc_vol_daily (
    -- Primary key
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,

    -- OHLC context (for reference)
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,

    -- Parkinson (1980) range-based volatility
    vol_parkinson_20    DOUBLE PRECISION,  -- 20-day (1 month)
    vol_parkinson_63    DOUBLE PRECISION,  -- ~3 months
    vol_parkinson_126   DOUBLE PRECISION,  -- ~6 months

    -- Garman-Klass (1980) OHLC volatility
    vol_gk_20           DOUBLE PRECISION,
    vol_gk_63           DOUBLE PRECISION,
    vol_gk_126          DOUBLE PRECISION,

    -- Rogers-Satchell (1991) drift-independent volatility
    vol_rs_20           DOUBLE PRECISION,
    vol_rs_63           DOUBLE PRECISION,
    vol_rs_126          DOUBLE PRECISION,

    -- ATR (Wilder) for reference
    atr_14              DOUBLE PRECISION,

    -- Rolling historical volatility from returns
    vol_log_roll_20     DOUBLE PRECISION,
    vol_log_roll_63     DOUBLE PRECISION,
    vol_log_roll_126    DOUBLE PRECISION,

    -- Normalized versions (z-scores)
    vol_parkinson_20_zscore  DOUBLE PRECISION,
    vol_parkinson_63_zscore  DOUBLE PRECISION,
    vol_parkinson_126_zscore DOUBLE PRECISION,
    vol_gk_20_zscore         DOUBLE PRECISION,
    vol_gk_63_zscore         DOUBLE PRECISION,
    vol_gk_126_zscore        DOUBLE PRECISION,
    vol_rs_20_zscore         DOUBLE PRECISION,
    vol_rs_63_zscore         DOUBLE PRECISION,
    vol_rs_126_zscore        DOUBLE PRECISION,

    -- Outlier flags
    vol_parkinson_20_is_outlier  BOOLEAN DEFAULT FALSE,
    vol_parkinson_63_is_outlier  BOOLEAN DEFAULT FALSE,
    vol_parkinson_126_is_outlier BOOLEAN DEFAULT FALSE,
    vol_gk_20_is_outlier         BOOLEAN DEFAULT FALSE,
    vol_gk_63_is_outlier         BOOLEAN DEFAULT FALSE,
    vol_gk_126_is_outlier        BOOLEAN DEFAULT FALSE,
    vol_rs_20_is_outlier         BOOLEAN DEFAULT FALSE,
    vol_rs_63_is_outlier         BOOLEAN DEFAULT FALSE,
    vol_rs_126_is_outlier        BOOLEAN DEFAULT FALSE,
    atr_14_is_outlier            BOOLEAN DEFAULT FALSE,
    vol_log_roll_20_is_outlier   BOOLEAN DEFAULT FALSE,
    vol_log_roll_63_is_outlier   BOOLEAN DEFAULT FALSE,
    vol_log_roll_126_is_outlier  BOOLEAN DEFAULT FALSE,

    -- Metadata
    updated_at          TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts)
);

-- Index for lookups (id DESC, ts DESC for incremental queries)
CREATE INDEX IF NOT EXISTS idx_cmc_vol_daily_id_ts
ON public.cmc_vol_daily (id, ts DESC);

-- Table comment
COMMENT ON TABLE public.cmc_vol_daily IS
'Daily volatility measures calculated from cmc_price_bars_1d OHLC. All volatility measures annualized using sqrt(252) for trading days. Includes Parkinson (range-based), Garman-Klass (OHLC-based), Rogers-Satchell (drift-independent), ATR, and rolling historical volatility from log returns.';

-- Column comments
COMMENT ON COLUMN public.cmc_vol_daily.vol_parkinson_20 IS 'Parkinson (1980) range-based volatility, 20-day window, annualized';
COMMENT ON COLUMN public.cmc_vol_daily.vol_gk_20 IS 'Garman-Klass (1980) OHLC volatility, 20-day window, annualized';
COMMENT ON COLUMN public.cmc_vol_daily.vol_rs_20 IS 'Rogers-Satchell (1991) drift-independent volatility, 20-day window, annualized';
COMMENT ON COLUMN public.cmc_vol_daily.atr_14 IS 'Average True Range (Wilder), 14-day period';
COMMENT ON COLUMN public.cmc_vol_daily.vol_log_roll_20 IS 'Rolling standard deviation of log returns, 20-day window, annualized';
