-- create_ama_multi_tf.sql
-- Creates:
--   public.ama_multi_tf       (main AMA value table)
--   public.ama_multi_tf_state (watermark state)
--
-- PK: (id, ts, tf, indicator, params_hash)
-- indicator distinguishes KAMA/DEMA/TEMA/HMA in a single table.
-- params_hash maps to dim_ama_params for human-readable parameter values.
-- er column stores KAMA Efficiency Ratio (NULL for non-KAMA indicators).
-- No 'period' column -- period is embedded in params_hash lookup.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ama_multi_tf (
    id              integer      NOT NULL,
    ts              timestamptz  NOT NULL,
    tf              text         NOT NULL,
    indicator       text         NOT NULL,
    params_hash     text         NOT NULL,
    tf_days         integer,
    roll            boolean      NOT NULL DEFAULT FALSE,

    -- AMA value and derivatives
    ama             double precision,
    d1              double precision,
    d2              double precision,
    d1_roll         double precision,
    d2_roll         double precision,

    -- Efficiency Ratio (KAMA only, NULL for DEMA/TEMA/HMA)
    er              double precision,

    is_partial_end  boolean,
    ingested_at     timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);

CREATE TABLE IF NOT EXISTS public.ama_multi_tf_state (
    id                   integer     NOT NULL,
    tf                   text        NOT NULL,
    indicator            text        NOT NULL,
    params_hash          text        NOT NULL,
    last_canonical_ts    timestamptz,
    updated_at           timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash)
);

-- Lookup by indicator+params for cross-asset queries
CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_indicator
ON public.ama_multi_tf (indicator, params_hash, tf, ts);

-- Fast filter for roll=TRUE rows (roll-space lookback queries)
CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_roll_true
ON public.ama_multi_tf (id, tf, indicator, params_hash, ts)
WHERE roll = TRUE;

COMMIT;
