-- create_ama_multi_tf_cal.sql
-- Creates calendar-aligned AMA value tables:
--   public.ama_multi_tf_cal_us       (US calendar alignment)
--   public.ama_multi_tf_cal_us_state
--   public.ama_multi_tf_cal_iso      (ISO calendar alignment)
--   public.ama_multi_tf_cal_iso_state
--
-- Same column schema as ama_multi_tf.
-- PK: (id, ts, tf, indicator, params_hash) -- no alignment_source here,
-- that lives on the _u unified table only.

BEGIN;

-- ============================================================
-- CAL US value table + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.ama_multi_tf_cal_us (
    id              integer      NOT NULL,
    ts              timestamptz  NOT NULL,
    tf              text         NOT NULL,
    indicator       text         NOT NULL,
    params_hash     text         NOT NULL,
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

    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);

CREATE TABLE IF NOT EXISTS public.ama_multi_tf_cal_us_state (
    id                   integer     NOT NULL,
    tf                   text        NOT NULL,
    indicator            text        NOT NULL,
    params_hash          text        NOT NULL,
    last_canonical_ts    timestamptz,
    updated_at           timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash)
);

CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_cal_us_indicator
ON public.ama_multi_tf_cal_us (indicator, params_hash, tf, ts);

CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_cal_us_roll_true
ON public.ama_multi_tf_cal_us (id, tf, indicator, params_hash, ts)
WHERE roll = TRUE;


-- ============================================================
-- CAL ISO value table + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.ama_multi_tf_cal_iso (
    id              integer      NOT NULL,
    ts              timestamptz  NOT NULL,
    tf              text         NOT NULL,
    indicator       text         NOT NULL,
    params_hash     text         NOT NULL,
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

    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);

CREATE TABLE IF NOT EXISTS public.ama_multi_tf_cal_iso_state (
    id                   integer     NOT NULL,
    tf                   text        NOT NULL,
    indicator            text        NOT NULL,
    params_hash          text        NOT NULL,
    last_canonical_ts    timestamptz,
    updated_at           timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash)
);

CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_cal_iso_indicator
ON public.ama_multi_tf_cal_iso (indicator, params_hash, tf, ts);

CREATE INDEX IF NOT EXISTS ix_ama_multi_tf_cal_iso_roll_true
ON public.ama_multi_tf_cal_iso (id, tf, indicator, params_hash, ts)
WHERE roll = TRUE;

COMMIT;
