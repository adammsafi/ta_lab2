-- signals_macd_crossover: MACD crossover trading signals
--
-- Stores MACD crossover signals with full position lifecycle tracking.
-- Each signal tracks entry, exit, and PnL with feature snapshot for reproducibility.
-- executor_processed_at enables replay guard: unprocessed signals have NULL.
--
-- Reference DDL -- actual migration is in alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py

CREATE TABLE IF NOT EXISTS public.signals_macd_crossover (
    -- Primary key
    id                      INTEGER         NOT NULL,
    ts                      TIMESTAMPTZ     NOT NULL,
    signal_id               INTEGER         NOT NULL,

    -- Signal details
    direction               TEXT            NOT NULL,  -- 'long', 'short'
    position_state          TEXT            NOT NULL,  -- 'open', 'closed'

    -- Position tracking
    entry_price             NUMERIC         NULL,
    entry_ts                TIMESTAMPTZ     NULL,
    exit_price              NUMERIC         NULL,
    exit_ts                 TIMESTAMPTZ     NULL,
    pnl_pct                 NUMERIC         NULL,      -- Computed on close: (exit - entry) / entry * 100

    -- Feature snapshot at entry (for reproducibility)
    feature_snapshot        JSONB           NULL,      -- {close, macd_line, signal_line, histogram, ...}

    -- Reproducibility metadata
    signal_version          TEXT            NULL,      -- Signal code version (e.g., 'v1.0')
    feature_version_hash    TEXT            NULL,      -- Hash of feature data used
    params_hash             TEXT            NULL,      -- Hash of signal params from dim_signals

    -- Replay guard: NULL = not yet processed by executor
    executor_processed_at   TIMESTAMPTZ     NULL,

    -- Metadata
    created_at              TIMESTAMPTZ     DEFAULT now(),

    PRIMARY KEY (id, ts, signal_id),
    FOREIGN KEY (signal_id) REFERENCES public.dim_signals(signal_id)
);

-- Index for open position queries
CREATE INDEX IF NOT EXISTS idx_signals_macd_xo_open_positions
    ON public.signals_macd_crossover (id, signal_id, position_state)
    WHERE position_state = 'open';

-- Index for backtest queries (by signal_id, chronological)
CREATE INDEX IF NOT EXISTS idx_signals_macd_xo_backtest
    ON public.signals_macd_crossover (signal_id, ts);

-- Index for PnL analysis
CREATE INDEX IF NOT EXISTS idx_signals_macd_xo_closed
    ON public.signals_macd_crossover (signal_id, position_state)
    WHERE position_state = 'closed';

COMMENT ON TABLE public.signals_macd_crossover IS
'MACD crossover trading signals with position lifecycle tracking. Stores entry/exit pairs with feature snapshots for reproducibility.';

COMMENT ON COLUMN public.signals_macd_crossover.feature_snapshot IS
'JSON snapshot of features at signal generation: {close, macd_line, signal_line, histogram, ...}';

COMMENT ON COLUMN public.signals_macd_crossover.feature_version_hash IS
'SHA256 hash of feature data used for signal generation. Enables reproducibility validation.';

COMMENT ON COLUMN public.signals_macd_crossover.executor_processed_at IS
'Timestamp when executor consumed this signal. NULL = not yet processed. Replay guard key column.';
