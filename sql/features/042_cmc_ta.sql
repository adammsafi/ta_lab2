-- cmc_ta: Multi-TF technical indicators
--
-- Stores RSI, MACD, Stochastic, Bollinger Bands, ATR, ADX with multiple parameter sets.
-- Parameter sets defined in dim_indicators.

CREATE TABLE IF NOT EXISTS public.cmc_ta (
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT NOT NULL,
    tf_days         INTEGER NOT NULL,

    -- Price context
    close           DOUBLE PRECISION,

    -- RSI (multiple periods)
    rsi_7           DOUBLE PRECISION,
    rsi_14          DOUBLE PRECISION,
    rsi_21          DOUBLE PRECISION,

    -- MACD (multiple parameter sets)
    macd_12_26      DOUBLE PRECISION,      -- MACD line
    macd_signal_9   DOUBLE PRECISION,      -- Signal line
    macd_hist_12_26_9 DOUBLE PRECISION,    -- Histogram
    macd_8_17       DOUBLE PRECISION,
    macd_signal_9_fast DOUBLE PRECISION,
    macd_hist_8_17_9 DOUBLE PRECISION,

    -- Stochastic
    stoch_k_14      DOUBLE PRECISION,
    stoch_d_3       DOUBLE PRECISION,

    -- Bollinger Bands
    bb_ma_20        DOUBLE PRECISION,
    bb_up_20_2      DOUBLE PRECISION,
    bb_lo_20_2      DOUBLE PRECISION,
    bb_width_20     DOUBLE PRECISION,

    -- ATR and ADX
    atr_14          DOUBLE PRECISION,
    adx_14          DOUBLE PRECISION,

    -- Normalized versions
    rsi_14_zscore   DOUBLE PRECISION,

    -- Data quality
    is_outlier      BOOLEAN DEFAULT FALSE,

    -- Metadata
    updated_at      TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts, tf)
);

CREATE INDEX IF NOT EXISTS idx_cmc_ta_id_tf_ts
ON public.cmc_ta (id, tf, ts DESC);

COMMENT ON TABLE public.cmc_ta IS
'Multi-TF technical indicators. Parameter sets defined in dim_indicators.';
