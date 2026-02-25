-- ============================================================================
-- Table: cmc_cycle_stats
-- Purpose: ATH tracking, drawdown from ATH, and cycle high/low analysis
-- ============================================================================
-- Cumulative all-time high (ATH) and drawdown cycle metrics per bar.
-- ATH is the rolling cumulative max of close price.
-- Cycle low is the minimum close between consecutive ATHs.
--
-- Multi-TF: Each (id, tf) series tracks ATH independently.
-- days_since_ath is calendar days (comparable across TFs).
-- bars_since_ath is TF-native bar count.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.cmc_cycle_stats (
    -- Primary key
    id                  INTEGER NOT NULL,
    ts                  TIMESTAMPTZ NOT NULL,
    tf                  TEXT NOT NULL,
    alignment_source    TEXT NOT NULL,
    tf_days             INTEGER NOT NULL,

    -- Current bar context
    close               DOUBLE PRECISION,

    -- All-time high tracking
    ath                 DOUBLE PRECISION,       -- cummax(close)
    ath_ts              TIMESTAMPTZ,            -- timestamp when ATH was set
    dd_from_ath         DOUBLE PRECISION,       -- (close - ath) / ath, always <= 0
    bars_since_ath      INTEGER,                -- bar count since ATH (TF-native)
    days_since_ath      INTEGER,                -- calendar days since ATH

    -- Cycle low tracking (lowest close since last ATH)
    cycle_low           DOUBLE PRECISION,       -- min(close) since last ATH
    cycle_low_ts        TIMESTAMPTZ,            -- when cycle low occurred
    dd_ath_to_low       DOUBLE PRECISION,       -- (cycle_low - ath) / ath
    bars_ath_to_low     INTEGER,                -- bars from ATH to cycle low
    days_ath_to_low     INTEGER,                -- calendar days from ATH to cycle low

    -- Recovery tracking
    is_at_ath           BOOLEAN DEFAULT FALSE,  -- close == ath (new ATH this bar)
    cycle_number        INTEGER,                -- monotonically increasing cycle counter

    -- Metadata
    updated_at          TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts, tf, alignment_source)
);

-- Index for per-asset cycle queries
CREATE INDEX IF NOT EXISTS idx_cmc_cycle_stats_id_tf_as_ts
ON public.cmc_cycle_stats (id, tf, alignment_source, ts DESC);

-- Index for finding ATH events
CREATE INDEX IF NOT EXISTS idx_cmc_cycle_stats_ath_events
ON public.cmc_cycle_stats (id, tf, is_at_ath)
WHERE is_at_ath = TRUE;

COMMENT ON TABLE public.cmc_cycle_stats IS
'ATH tracking and drawdown cycle metrics per bar. ATH = cummax(close). days_since_ath is calendar days (cross-TF comparable). bars_since_ath is TF-native.';
