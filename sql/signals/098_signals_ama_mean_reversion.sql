-- signals_ama_mean_reversion: AMA mean-reversion signals
--
-- Stores AMA-based mean-reversion signals with full position lifecycle tracking.
-- Complements ama_momentum by trading the opposite: enters when price deviates
-- sharply from the AMA and reverts back, useful in choppy/ranging markets.
-- executor_processed_at enables replay guard: unprocessed signals have NULL.
--
-- Reference DDL -- actual migration is in alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py

CREATE TABLE IF NOT EXISTS public.signals_ama_mean_reversion (
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
    feature_snapshot        JSONB           NULL,      -- {close, ama_value, deviation_pct, er, ...}

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
CREATE INDEX IF NOT EXISTS idx_signals_ama_mr_open_positions
    ON public.signals_ama_mean_reversion (id, signal_id, position_state)
    WHERE position_state = 'open';

-- Index for backtest queries (by signal_id, chronological)
CREATE INDEX IF NOT EXISTS idx_signals_ama_mr_backtest
    ON public.signals_ama_mean_reversion (signal_id, ts);

-- Index for PnL analysis
CREATE INDEX IF NOT EXISTS idx_signals_ama_mr_closed
    ON public.signals_ama_mean_reversion (signal_id, position_state)
    WHERE position_state = 'closed';

COMMENT ON TABLE public.signals_ama_mean_reversion IS
'AMA mean-reversion signals. Enters on price deviation from Adaptive Moving Average and exits on reversion. Complements ama_momentum in ranging markets.';

COMMENT ON COLUMN public.signals_ama_mean_reversion.feature_snapshot IS
'JSON snapshot of features at signal generation: {close, ama_value, deviation_pct, efficiency_ratio, ...}';

COMMENT ON COLUMN public.signals_ama_mean_reversion.feature_version_hash IS
'SHA256 hash of feature data used for signal generation. Enables reproducibility validation.';

COMMENT ON COLUMN public.signals_ama_mean_reversion.executor_processed_at IS
'Timestamp when executor consumed this signal. NULL = not yet processed. Replay guard key column.';
