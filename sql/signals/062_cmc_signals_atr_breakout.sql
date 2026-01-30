-- cmc_signals_atr_breakout: ATR breakout trading signals
--
-- Stores ATR breakout signals with full position lifecycle tracking.
-- Each signal tracks entry, exit, and PnL with feature snapshot for reproducibility.

CREATE TABLE IF NOT EXISTS public.cmc_signals_atr_breakout (
    -- Primary key
    id                      INTEGER         NOT NULL,
    ts                      TIMESTAMPTZ     NOT NULL,
    signal_id               INTEGER         NOT NULL,

    -- Signal details
    direction               TEXT            NOT NULL,  -- 'long' (breakout up), 'short' (breakout down)
    position_state          TEXT            NOT NULL,  -- 'open', 'closed'

    -- Position tracking
    entry_price             NUMERIC         NULL,
    entry_ts                TIMESTAMPTZ     NULL,
    exit_price              NUMERIC         NULL,
    exit_ts                 TIMESTAMPTZ     NULL,
    pnl_pct                 NUMERIC         NULL,      -- Computed on close: (exit - entry) / entry * 100

    -- Breakout-specific fields for analysis
    breakout_type           TEXT            NULL,      -- 'channel_break', 'atr_expansion', 'both'

    -- Feature snapshot at entry (for reproducibility)
    feature_snapshot        JSONB           NULL,      -- {close, high, low, atr, channel_high, channel_low}

    -- Reproducibility metadata
    signal_version          TEXT            NULL,      -- Signal code version (e.g., 'v1.0')
    feature_version_hash    TEXT            NULL,      -- Hash of feature data used
    params_hash             TEXT            NULL,      -- Hash of signal params from dim_signals

    -- Metadata
    created_at              TIMESTAMPTZ     DEFAULT now(),

    PRIMARY KEY (id, ts, signal_id),
    FOREIGN KEY (signal_id) REFERENCES public.dim_signals(signal_id)
);

-- Index for open position queries
CREATE INDEX IF NOT EXISTS idx_cmc_signals_atr_bo_open_positions
    ON public.cmc_signals_atr_breakout (id, signal_id, position_state)
    WHERE position_state = 'open';

-- Index for backtest queries (by signal_id, chronological)
CREATE INDEX IF NOT EXISTS idx_cmc_signals_atr_bo_backtest
    ON public.cmc_signals_atr_breakout (signal_id, ts);

-- Index for PnL analysis
CREATE INDEX IF NOT EXISTS idx_cmc_signals_atr_bo_closed
    ON public.cmc_signals_atr_breakout (signal_id, position_state)
    WHERE position_state = 'closed';

-- Index for breakout type analysis
CREATE INDEX IF NOT EXISTS idx_cmc_signals_atr_bo_type
    ON public.cmc_signals_atr_breakout (breakout_type)
    WHERE position_state = 'closed' AND breakout_type IS NOT NULL;

COMMENT ON TABLE public.cmc_signals_atr_breakout IS
'ATR breakout trading signals with position lifecycle tracking. Stores entry/exit pairs with breakout context for analysis.';

COMMENT ON COLUMN public.cmc_signals_atr_breakout.breakout_type IS
'Type of breakout detected: channel_break (Donchian channel), atr_expansion (volatility spike), or both.';

COMMENT ON COLUMN public.cmc_signals_atr_breakout.feature_snapshot IS
'JSON snapshot of features at signal generation: {close, high, low, atr, channel_high, channel_low, ...}';
