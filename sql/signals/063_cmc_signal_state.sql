-- cmc_signal_state: Position state tracking for stateful signals
--
-- Tracks last entry/exit timestamps and open position counts per (id, signal_type, signal_id).
-- Used for incremental signal generation and position lifecycle management.
-- Follows feature_state_manager pattern from Phase 7.

CREATE TABLE IF NOT EXISTS public.cmc_signal_state (
    -- Primary key
    id                      INTEGER         NOT NULL,
    signal_type             TEXT            NOT NULL,
    signal_id               INTEGER         NOT NULL,

    -- Position tracking
    last_entry_ts           TIMESTAMPTZ     NULL,
    last_exit_ts            TIMESTAMPTZ     NULL,
    open_position_count     INTEGER         DEFAULT 0,

    -- Metadata
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, signal_type, signal_id)
);

-- Create index for efficient queries
CREATE INDEX IF NOT EXISTS idx_cmc_signal_state_open_positions
    ON public.cmc_signal_state (signal_type, signal_id)
    WHERE open_position_count > 0;

COMMENT ON TABLE public.cmc_signal_state IS
'Position state tracking for signal generation. Enables incremental refresh and position lifecycle management.';

COMMENT ON COLUMN public.cmc_signal_state.last_entry_ts IS
'Timestamp of most recent signal entry for this asset/signal combination';

COMMENT ON COLUMN public.cmc_signal_state.last_exit_ts IS
'Timestamp of most recent position exit for this asset/signal combination';

COMMENT ON COLUMN public.cmc_signal_state.open_position_count IS
'Number of currently open positions for this asset/signal combination';
