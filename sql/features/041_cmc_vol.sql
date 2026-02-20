-- ============================================================================
-- Table: cmc_vol
-- Purpose: Multi-TF volatility measures from OHLC bars
-- ============================================================================
-- Volatility Estimators:
--   Parkinson (1980): Range-based vol (high/low)
--   Garman-Klass (1980): OHLC-based vol estimator
--   Rogers-Satchell (1991): Drift-independent vol estimator
--   ATR (Wilder): Average True Range
--   Rolling historical: Log return standard deviation
--
-- Annualization: periods_per_year = max(12, round(252 / tf_days))
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.cmc_vol (
    -- Primary key
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT NOT NULL,
    tf_days         INTEGER NOT NULL,

    -- OHLC context (for reference)
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,

    -- Parkinson (1980) range-based volatility
    vol_parkinson_20    DOUBLE PRECISION,  -- 20-bar
    vol_parkinson_63    DOUBLE PRECISION,  -- 63-bar
    vol_parkinson_126   DOUBLE PRECISION,  -- 126-bar

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

    PRIMARY KEY (id, ts, tf)
);

-- Index for lookups per TF
CREATE INDEX IF NOT EXISTS idx_cmc_vol_id_tf_ts
ON public.cmc_vol (id, tf, ts DESC);

COMMENT ON TABLE public.cmc_vol IS
'Multi-TF volatility measures from cmc_price_bars_multi_tf OHLC. Annualization: periods_per_year = max(12, round(252/tf_days)).';
