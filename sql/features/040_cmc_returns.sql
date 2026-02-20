-- sql/features/040_cmc_returns.sql
-- DEPRECATED: This table is replaced by cmc_returns_bars_multi_tf which provides
-- period-over-period returns with z-scores across all timeframes.
-- Kept for reference only. Do not use for new features.
--
-- Old: Multi-TF returns feature table with multiple lookback windows
-- Lookback windows in bars (not days): 1, 3, 5, 7, 14, 21, 30, 63, 126, 252
-- Column naming: ret_N_pct = N-bar return (timeframe-agnostic)
--
-- Source: cmc_price_bars_multi_tf (all timeframes)
-- State tracking: cmc_feature_state (feature_type='returns')

CREATE TABLE IF NOT EXISTS public.cmc_returns (
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT NOT NULL,
    tf_days         INTEGER NOT NULL,

    -- Price context
    close           DOUBLE PRECISION,

    -- Bar-to-bar returns (always computed)
    ret_1_pct       DOUBLE PRECISION,  -- 1-bar percent return
    ret_1_log       DOUBLE PRECISION,  -- 1-bar log return

    -- Multi-bar percent returns (lookbacks from dim_timeframe tf_days)
    ret_3_pct       DOUBLE PRECISION,  -- 3-bar percent return
    ret_5_pct       DOUBLE PRECISION,  -- 5-bar percent return
    ret_7_pct       DOUBLE PRECISION,  -- 7-bar percent return
    ret_14_pct      DOUBLE PRECISION,  -- 14-bar percent return
    ret_21_pct      DOUBLE PRECISION,  -- 21-bar percent return
    ret_30_pct      DOUBLE PRECISION,  -- 30-bar percent return
    ret_63_pct      DOUBLE PRECISION,  -- ~3 months equivalent
    ret_126_pct     DOUBLE PRECISION,  -- ~6 months equivalent
    ret_252_pct     DOUBLE PRECISION,  -- ~1 year equivalent

    -- Normalized versions (z-scores)
    ret_1_pct_zscore    DOUBLE PRECISION,
    ret_7_pct_zscore    DOUBLE PRECISION,
    ret_30_pct_zscore   DOUBLE PRECISION,

    -- Data quality flags
    gap_days        INTEGER,           -- Days since previous observation
    is_outlier      BOOLEAN DEFAULT FALSE,

    -- Metadata
    updated_at      TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts, tf)
);

-- Index for time-series lookups per TF
CREATE INDEX IF NOT EXISTS idx_cmc_returns_id_tf_ts
ON public.cmc_returns (id, tf, ts DESC);

COMMENT ON TABLE public.cmc_returns IS
'Multi-TF returns calculated from cmc_price_bars_multi_tf. Column ret_N_pct = N-bar return (timeframe-agnostic).';
