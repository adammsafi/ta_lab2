-- sql/views/050_cmc_features.sql
-- Unified multi-TF bar-level feature store (materialized table, not view)
--
-- Purpose: Single-table access to all bar-level features for ML pipelines
-- Source tables:
--   - cmc_price_bars_multi_tf (OHLCV, all TFs)
--   - cmc_returns_bars_multi_tf (bar returns, canonical + roll columns)
--   - cmc_vol (volatility estimators)
--   - cmc_ta (technical indicators)
--
-- NOT included (different granularity — has period dimension):
--   - cmc_ema_multi_tf_u (EMA values) — query directly
--   - cmc_returns_ema_multi_tf_u (EMA returns) — query directly
--
-- Refresh pattern: Incremental via FeaturesStore
-- State tracking: cmc_feature_state (feature_type='daily_features')

CREATE TABLE IF NOT EXISTS public.cmc_features (
    -- Primary key
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT NOT NULL,
    tf_days         INTEGER NOT NULL,

    -- Asset metadata
    asset_class     TEXT,

    -- ═══════════════════════════════════════════════════════════════
    -- OHLCV (from cmc_price_bars_multi_tf)
    -- ═══════════════════════════════════════════════════════════════
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    volume          DOUBLE PRECISION,

    -- ═══════════════════════════════════════════════════════════════
    -- Bar Returns (from cmc_returns_bars_multi_tf, join on roll=FALSE)
    -- Both canonical and roll columns are populated on roll=FALSE rows
    -- ═══════════════════════════════════════════════════════════════

    -- Gap tracking
    gap_bars                        INTEGER,

    -- Canonical columns (partitioned LAG, bar-to-bar)
    delta1                          DOUBLE PRECISION,
    delta2                          DOUBLE PRECISION,
    ret_arith                       DOUBLE PRECISION,
    delta_ret_arith                 DOUBLE PRECISION,
    ret_log                         DOUBLE PRECISION,
    delta_ret_log                   DOUBLE PRECISION,
    "range"                         DOUBLE PRECISION,
    range_pct                       DOUBLE PRECISION,
    true_range                      DOUBLE PRECISION,
    true_range_pct                  DOUBLE PRECISION,

    -- Roll columns (unified LAG, daily-frequency)
    delta1_roll                     DOUBLE PRECISION,
    delta2_roll                     DOUBLE PRECISION,
    ret_arith_roll                  DOUBLE PRECISION,
    delta_ret_arith_roll            DOUBLE PRECISION,
    ret_log_roll                    DOUBLE PRECISION,
    delta_ret_log_roll              DOUBLE PRECISION,
    range_roll                      DOUBLE PRECISION,
    range_pct_roll                  DOUBLE PRECISION,
    true_range_roll                 DOUBLE PRECISION,
    true_range_pct_roll             DOUBLE PRECISION,

    -- Z-scores: canonical, 30-day window
    ret_arith_zscore_30             DOUBLE PRECISION,
    delta_ret_arith_zscore_30       DOUBLE PRECISION,
    ret_log_zscore_30               DOUBLE PRECISION,
    delta_ret_log_zscore_30         DOUBLE PRECISION,
    -- Z-scores: roll, 30-day window
    ret_arith_roll_zscore_30        DOUBLE PRECISION,
    delta_ret_arith_roll_zscore_30  DOUBLE PRECISION,
    ret_log_roll_zscore_30          DOUBLE PRECISION,
    delta_ret_log_roll_zscore_30    DOUBLE PRECISION,

    -- Z-scores: canonical, 90-day window
    ret_arith_zscore_90             DOUBLE PRECISION,
    delta_ret_arith_zscore_90       DOUBLE PRECISION,
    ret_log_zscore_90               DOUBLE PRECISION,
    delta_ret_log_zscore_90         DOUBLE PRECISION,
    -- Z-scores: roll, 90-day window
    ret_arith_roll_zscore_90        DOUBLE PRECISION,
    delta_ret_arith_roll_zscore_90  DOUBLE PRECISION,
    ret_log_roll_zscore_90          DOUBLE PRECISION,
    delta_ret_log_roll_zscore_90    DOUBLE PRECISION,

    -- Z-scores: canonical, 365-day window
    ret_arith_zscore_365            DOUBLE PRECISION,
    delta_ret_arith_zscore_365      DOUBLE PRECISION,
    ret_log_zscore_365              DOUBLE PRECISION,
    delta_ret_log_zscore_365        DOUBLE PRECISION,
    -- Z-scores: roll, 365-day window
    ret_arith_roll_zscore_365       DOUBLE PRECISION,
    delta_ret_arith_roll_zscore_365 DOUBLE PRECISION,
    ret_log_roll_zscore_365         DOUBLE PRECISION,
    delta_ret_log_roll_zscore_365   DOUBLE PRECISION,

    -- Returns outlier flag
    ret_is_outlier                  BOOLEAN,

    -- ═══════════════════════════════════════════════════════════════
    -- Volatility (from cmc_vol)
    -- ═══════════════════════════════════════════════════════════════

    -- Parkinson volatility (3 windows)
    vol_parkinson_20                DOUBLE PRECISION,
    vol_parkinson_63                DOUBLE PRECISION,
    vol_parkinson_126               DOUBLE PRECISION,

    -- Garman-Klass volatility (3 windows)
    vol_gk_20                       DOUBLE PRECISION,
    vol_gk_63                       DOUBLE PRECISION,
    vol_gk_126                      DOUBLE PRECISION,

    -- Rogers-Satchell volatility (3 windows)
    vol_rs_20                       DOUBLE PRECISION,
    vol_rs_63                       DOUBLE PRECISION,
    vol_rs_126                      DOUBLE PRECISION,

    -- Rolling log volatility (3 windows)
    vol_log_roll_20                 DOUBLE PRECISION,
    vol_log_roll_63                 DOUBLE PRECISION,
    vol_log_roll_126                DOUBLE PRECISION,

    -- ATR
    atr_14                          DOUBLE PRECISION,

    -- Vol z-scores (parkinson, gk, rs)
    vol_parkinson_20_zscore         DOUBLE PRECISION,
    vol_parkinson_63_zscore         DOUBLE PRECISION,
    vol_parkinson_126_zscore        DOUBLE PRECISION,
    vol_gk_20_zscore                DOUBLE PRECISION,
    vol_gk_63_zscore                DOUBLE PRECISION,
    vol_gk_126_zscore               DOUBLE PRECISION,
    vol_rs_20_zscore                DOUBLE PRECISION,
    vol_rs_63_zscore                DOUBLE PRECISION,
    vol_rs_126_zscore               DOUBLE PRECISION,

    -- Vol outlier flags
    vol_parkinson_20_is_outlier     BOOLEAN DEFAULT FALSE,
    vol_parkinson_63_is_outlier     BOOLEAN DEFAULT FALSE,
    vol_parkinson_126_is_outlier    BOOLEAN DEFAULT FALSE,
    vol_gk_20_is_outlier            BOOLEAN DEFAULT FALSE,
    vol_gk_63_is_outlier            BOOLEAN DEFAULT FALSE,
    vol_gk_126_is_outlier           BOOLEAN DEFAULT FALSE,
    vol_rs_20_is_outlier            BOOLEAN DEFAULT FALSE,
    vol_rs_63_is_outlier            BOOLEAN DEFAULT FALSE,
    vol_rs_126_is_outlier           BOOLEAN DEFAULT FALSE,
    vol_log_roll_20_is_outlier      BOOLEAN DEFAULT FALSE,
    vol_log_roll_63_is_outlier      BOOLEAN DEFAULT FALSE,
    vol_log_roll_126_is_outlier     BOOLEAN DEFAULT FALSE,
    atr_14_is_outlier               BOOLEAN DEFAULT FALSE,

    -- ═══════════════════════════════════════════════════════════════
    -- Technical Indicators (from cmc_ta)
    -- ═══════════════════════════════════════════════════════════════

    -- RSI
    rsi_7                           DOUBLE PRECISION,
    rsi_14                          DOUBLE PRECISION,
    rsi_21                          DOUBLE PRECISION,

    -- MACD set 1 (12/26/9)
    macd_12_26                      DOUBLE PRECISION,
    macd_signal_9                   DOUBLE PRECISION,
    macd_hist_12_26_9               DOUBLE PRECISION,

    -- MACD set 2 (8/17/9)
    macd_8_17                       DOUBLE PRECISION,
    macd_signal_9_fast              DOUBLE PRECISION,
    macd_hist_8_17_9                DOUBLE PRECISION,

    -- Stochastic
    stoch_k_14                      DOUBLE PRECISION,
    stoch_d_3                       DOUBLE PRECISION,

    -- Bollinger Bands
    bb_ma_20                        DOUBLE PRECISION,
    bb_up_20_2                      DOUBLE PRECISION,
    bb_lo_20_2                      DOUBLE PRECISION,
    bb_width_20                     DOUBLE PRECISION,

    -- ADX
    adx_14                          DOUBLE PRECISION,

    -- TA z-score + outlier
    rsi_14_zscore                   DOUBLE PRECISION,
    ta_is_outlier                   BOOLEAN DEFAULT FALSE,

    -- ═══════════════════════════════════════════════════════════════
    -- Derived flags + metadata
    -- ═══════════════════════════════════════════════════════════════
    has_price_gap   BOOLEAN DEFAULT FALSE,
    has_outlier     BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts, tf)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_cmc_features_id_tf_ts
ON public.cmc_features (id, tf, ts DESC);

CREATE INDEX IF NOT EXISTS idx_cmc_features_asset_class
ON public.cmc_features (asset_class, tf, ts DESC);

COMMENT ON TABLE public.cmc_features IS
'Unified multi-TF bar-level feature store for ML pipelines. Materialized from prices, returns, vol, TA. EMAs excluded (different granularity — query cmc_ema_multi_tf_u directly).';
