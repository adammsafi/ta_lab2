-- create_ama_multi_tf_u.sql
-- Creates:
--   public.ama_multi_tf_u       (unified AMA value table)
--   public.ama_multi_tf_u_state
--
-- Unified table syncs rows from all 5 alignment variants via sync_utils.py.
-- alignment_source distinguishes origin (multi_tf, multi_tf_cal_us, etc.)
-- and is part of PK to allow same (id, ts, tf, indicator, params_hash) to
-- appear from multiple alignment sources without conflict.
--
-- PK: (id, ts, tf, indicator, params_hash, alignment_source)
-- State keyed by: (id, tf, indicator, params_hash, alignment_source)

BEGIN;

CREATE TABLE IF NOT EXISTS public.ama_multi_tf_u (
    id              integer      NOT NULL,
    ts              timestamptz  NOT NULL,
    tf              text         NOT NULL,
    indicator       text         NOT NULL,
    params_hash     text         NOT NULL,
    alignment_source text        NOT NULL DEFAULT 'multi_tf',
    tf_days         integer,
    roll            boolean      NOT NULL DEFAULT FALSE,

    ama             double precision,
    d1              double precision,
    d2              double precision,
    d1_roll         double precision,
    d2_roll         double precision,

    er              double precision,

    is_partial_end  boolean,
    ingested_at     timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, indicator, params_hash, alignment_source)
);

CREATE TABLE IF NOT EXISTS public.ama_multi_tf_u_state (
    id               integer     NOT NULL,
    tf               text        NOT NULL,
    indicator        text        NOT NULL,
    params_hash      text        NOT NULL,
    alignment_source text        NOT NULL,
    last_canonical_ts timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash, alignment_source)
);

-- Cross-indicator queries (e.g. all KAMA rows for a given tf)
CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_u_indicator
ON public.ama_multi_tf_u (indicator, params_hash, tf, ts);

-- Filter by alignment source for sync deduplication
CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_u_alignment_source
ON public.ama_multi_tf_u (alignment_source, id, tf, ts);

-- Fast roll=TRUE filter
CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_u_roll_true
ON public.ama_multi_tf_u (id, tf, indicator, params_hash, ts)
WHERE roll = TRUE;

COMMIT;
