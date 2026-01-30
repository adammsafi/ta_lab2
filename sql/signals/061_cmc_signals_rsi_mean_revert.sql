-- cmc_signals_rsi_mean_revert: RSI mean reversion trading signals
--
-- Stores RSI mean reversion signals with full position lifecycle tracking.
-- Each signal tracks entry, exit, and PnL with feature snapshot for reproducibility.

CREATE TABLE IF NOT EXISTS public.cmc_signals_rsi_mean_revert (
    -- Primary key
    id                      INTEGER         NOT NULL,
    ts                      TIMESTAMPTZ     NOT NULL,
    signal_id               INTEGER         NOT NULL,

    -- Signal details
    direction               TEXT            NOT NULL,  -- 'long' (from oversold), 'short' (from overbought)
    position_state          TEXT            NOT NULL,  -- 'open', 'closed'

    -- Position tracking
    entry_price             NUMERIC         NULL,
    entry_ts                TIMESTAMPTZ     NULL,
    exit_price              NUMERIC         NULL,
    exit_ts                 TIMESTAMPTZ     NULL,
    pnl_pct                 NUMERIC         NULL,      -- Computed on close: (exit - entry) / entry * 100

    -- RSI-specific fields for analysis
    rsi_at_entry            NUMERIC         NULL,      -- RSI value at entry signal
    rsi_at_exit             NUMERIC         NULL,      -- RSI value at exit signal

    -- Feature snapshot at entry (for reproducibility)
    feature_snapshot        JSONB           NULL,      -- {close, rsi, atr, vol}

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
CREATE INDEX IF NOT EXISTS idx_cmc_signals_rsi_mr_open_positions
    ON public.cmc_signals_rsi_mean_revert (id, signal_id, position_state)
    WHERE position_state = 'open';

-- Index for backtest queries (by signal_id, chronological)
CREATE INDEX IF NOT EXISTS idx_cmc_signals_rsi_mr_backtest
    ON public.cmc_signals_rsi_mean_revert (signal_id, ts);

-- Index for PnL analysis
CREATE INDEX IF NOT EXISTS idx_cmc_signals_rsi_mr_closed
    ON public.cmc_signals_rsi_mean_revert (signal_id, position_state)
    WHERE position_state = 'closed';

-- Index for RSI analysis (extreme readings)
CREATE INDEX IF NOT EXISTS idx_cmc_signals_rsi_mr_extreme
    ON public.cmc_signals_rsi_mean_revert (rsi_at_entry)
    WHERE position_state = 'closed' AND rsi_at_entry IS NOT NULL;

COMMENT ON TABLE public.cmc_signals_rsi_mean_revert IS
'RSI mean reversion trading signals with position lifecycle tracking. Stores entry/exit pairs with RSI snapshots for analysis.';

COMMENT ON COLUMN public.cmc_signals_rsi_mean_revert.rsi_at_entry IS
'RSI value at entry signal. Used to analyze relationship between entry RSI and PnL.';

COMMENT ON COLUMN public.cmc_signals_rsi_mean_revert.rsi_at_exit IS
'RSI value at exit signal. Used to analyze mean reversion completion.';
