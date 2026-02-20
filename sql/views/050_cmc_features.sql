-- sql/views/050_cmc_features.sql
-- Unified multi-TF feature store (materialized table, not view)
--
-- Purpose: Single-table access to all features for ML pipelines
-- Source tables:
--   - cmc_price_bars_multi_tf (OHLCV, all TFs)
--   - cmc_ema_multi_tf_u (EMAs)
--   - cmc_returns (returns across multiple lookbacks)
--   - cmc_vol (volatility estimators)
--   - cmc_ta (technical indicators)
--
-- Refresh pattern: Incremental via FeaturesStore
-- State tracking: cmc_feature_state (feature_type='daily_features')

CREATE TABLE IF NOT EXISTS public.cmc_features (
    -- Primary key
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT NOT NULL,
    tf_days         INTEGER NOT NULL,

    -- Asset metadata (from join with dim tables)
    asset_class     TEXT,              -- 'crypto', 'equity' from dim_sessions

    -- Price context (from cmc_price_bars_multi_tf)
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    volume          DOUBLE PRECISION,

    -- EMAs (from cmc_ema_multi_tf_u, pivoted for matching tf)
    ema_9           DOUBLE PRECISION,
    ema_10          DOUBLE PRECISION,
    ema_21          DOUBLE PRECISION,
    ema_50          DOUBLE PRECISION,
    ema_200         DOUBLE PRECISION,
    ema_9_d1        DOUBLE PRECISION,  -- First derivative
    ema_21_d1       DOUBLE PRECISION,

    -- Returns (from cmc_returns)
    ret_1_pct       DOUBLE PRECISION,
    ret_1_log       DOUBLE PRECISION,
    ret_7_pct       DOUBLE PRECISION,
    ret_30_pct      DOUBLE PRECISION,
    ret_1_pct_zscore DOUBLE PRECISION,
    gap_days        INTEGER,

    -- Volatility (from cmc_vol)
    vol_parkinson_20    DOUBLE PRECISION,
    vol_gk_20           DOUBLE PRECISION,
    vol_parkinson_20_zscore DOUBLE PRECISION,
    atr_14              DOUBLE PRECISION,

    -- Technical indicators (from cmc_ta)
    rsi_7           DOUBLE PRECISION,
    rsi_14          DOUBLE PRECISION,
    rsi_21          DOUBLE PRECISION,
    macd_12_26      DOUBLE PRECISION,
    macd_signal_9   DOUBLE PRECISION,
    macd_hist_12_26_9 DOUBLE PRECISION,
    stoch_k_14      DOUBLE PRECISION,
    stoch_d_3       DOUBLE PRECISION,
    bb_ma_20        DOUBLE PRECISION,
    bb_up_20_2      DOUBLE PRECISION,
    bb_lo_20_2      DOUBLE PRECISION,
    bb_width_20     DOUBLE PRECISION,
    adx_14          DOUBLE PRECISION,

    -- Data quality flags (union of source flags)
    has_price_gap   BOOLEAN DEFAULT FALSE,
    has_outlier     BOOLEAN DEFAULT FALSE,

    -- Refresh metadata
    updated_at      TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts, tf)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_cmc_features_id_tf_ts
ON public.cmc_features (id, tf, ts DESC);

CREATE INDEX IF NOT EXISTS idx_cmc_features_asset_class
ON public.cmc_features (asset_class, tf, ts DESC);

COMMENT ON TABLE public.cmc_features IS
'Unified multi-TF feature store for ML pipelines. Materialized from prices, EMAs, returns, vol, TA.';
