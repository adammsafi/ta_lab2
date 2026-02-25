-- alternative_me_fear_greed_state: refresh watermark for Fear & Greed ingestion
-- Single-row table (singleton_key + CHECK constraint ensures exactly one row)

CREATE TABLE IF NOT EXISTS public.alternative_me_fear_greed_state (
    singleton_key   BOOLEAN         PRIMARY KEY DEFAULT TRUE,
    last_ts         DATE,               -- max(ts) successfully written
    last_run_ts     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    rows_written    INTEGER         NOT NULL DEFAULT 0,
    CONSTRAINT single_row CHECK (singleton_key = TRUE)
);

COMMENT ON TABLE public.alternative_me_fear_greed_state IS
'Single-row state table tracking last successful Fear & Greed refresh.';
