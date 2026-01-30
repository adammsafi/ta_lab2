-- dim_signals: Signal strategy configuration
--
-- Defines which trading signals to generate and their parameter sets.
-- New signal configurations can be added without code changes.
-- Follows dim_indicators pattern from Phase 7.

CREATE TABLE IF NOT EXISTS public.dim_signals (
    signal_id       SERIAL PRIMARY KEY,
    signal_type     TEXT NOT NULL,         -- 'ema_crossover', 'rsi_mean_revert', 'atr_breakout'
    signal_name     TEXT NOT NULL UNIQUE,  -- 'ema_9_21_long', 'rsi_30_70_mr'
    params          JSONB NOT NULL,        -- Signal-specific parameters as JSON
    is_active       BOOLEAN DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Create index on signal_type for efficient filtering
CREATE INDEX IF NOT EXISTS idx_dim_signals_type_active
    ON public.dim_signals (signal_type, is_active)
    WHERE is_active = TRUE;

-- Insert seed data for signal strategies
INSERT INTO public.dim_signals (signal_type, signal_name, params, description)
VALUES
    -- EMA Crossover signals
    ('ema_crossover', 'ema_9_21_long', '{"fast_period": 9, "slow_period": 21, "direction": "long"}', 'Short-term EMA crossover (9/21) - Long signals only'),
    ('ema_crossover', 'ema_21_50_long', '{"fast_period": 21, "slow_period": 50, "direction": "long"}', 'Medium-term EMA crossover (21/50) - Long signals only'),
    ('ema_crossover', 'ema_50_200_long', '{"fast_period": 50, "slow_period": 200, "direction": "long"}', 'Long-term EMA crossover (50/200) - Golden cross strategy'),

    -- RSI Mean Reversion signals
    ('rsi_mean_revert', 'rsi_30_70_mr', '{"rsi_period": 14, "oversold": 30, "overbought": 70}', 'Standard RSI mean reversion (30/70 thresholds)'),
    ('rsi_mean_revert', 'rsi_25_75_mr', '{"rsi_period": 14, "oversold": 25, "overbought": 75}', 'Conservative RSI mean reversion (25/75 thresholds)'),

    -- ATR Breakout signals
    ('atr_breakout', 'atr_20_donchian', '{"atr_period": 14, "channel_period": 20, "atr_multiplier": 1.5}', 'Donchian channel breakout with ATR confirmation')
ON CONFLICT (signal_name) DO NOTHING;

COMMENT ON TABLE public.dim_signals IS
'Signal strategy configuration. Controls which trading signals are generated and their parameters.';

COMMENT ON COLUMN public.dim_signals.params IS
'JSON parameters specific to signal type:
- EMA crossover: {"fast_period": N, "slow_period": M, "direction": "long"|"short"}
- RSI mean revert: {"rsi_period": N, "oversold": X, "overbought": Y}
- ATR breakout: {"atr_period": N, "channel_period": M, "atr_multiplier": X}';
