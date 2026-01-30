-- dim_indicators: Technical indicator parameter configuration
--
-- Defines which technical indicators to compute and their parameter sets.
-- New indicators can be added without code changes.

CREATE TABLE IF NOT EXISTS public.dim_indicators (
    indicator_id    SERIAL PRIMARY KEY,
    indicator_type  TEXT NOT NULL,         -- 'rsi', 'macd', 'stoch', 'bb', 'atr', 'adx'
    indicator_name  TEXT NOT NULL UNIQUE,  -- 'rsi_14', 'macd_12_26_9'
    params          JSONB NOT NULL,        -- {"period": 14} or {"fast": 12, "slow": 26, "signal": 9}
    is_active       BOOLEAN DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Insert standard parameter sets
INSERT INTO public.dim_indicators (indicator_type, indicator_name, params, description)
VALUES
    -- RSI variations
    ('rsi', 'rsi_14', '{"period": 14}', 'Standard RSI (14 periods)'),
    ('rsi', 'rsi_21', '{"period": 21}', 'RSI (21 periods)'),
    ('rsi', 'rsi_7', '{"period": 7}', 'Short-term RSI'),

    -- MACD variations
    ('macd', 'macd_12_26_9', '{"fast": 12, "slow": 26, "signal": 9}', 'Standard MACD'),
    ('macd', 'macd_8_17_9', '{"fast": 8, "slow": 17, "signal": 9}', 'Fast MACD'),

    -- Stochastic
    ('stoch', 'stoch_14_3', '{"k": 14, "d": 3}', 'Standard Stochastic'),

    -- Bollinger Bands
    ('bb', 'bb_20_2', '{"window": 20, "n_sigma": 2.0}', 'Standard Bollinger Bands'),

    -- ATR
    ('atr', 'atr_14', '{"period": 14}', 'Standard ATR'),

    -- ADX
    ('adx', 'adx_14', '{"period": 14}', 'Standard ADX')
ON CONFLICT (indicator_name) DO NOTHING;

COMMENT ON TABLE public.dim_indicators IS
'Technical indicator parameter definitions. Controls which indicators are computed in cmc_ta_daily.';
