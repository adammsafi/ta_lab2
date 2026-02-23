-- create_cmc_returns_ama_multi_tf_u.sql
-- Creates:
--   public.cmc_returns_ama_multi_tf_u       (unified AMA returns table)
--   public.cmc_returns_ama_multi_tf_u_state
--
-- Unified table syncs rows from all 5 alignment variants via sync_utils.py.
-- alignment_source distinguishes origin and is part of PK.
--
-- PK: (id, ts, tf, indicator, params_hash, alignment_source)
-- State keyed by: (id, tf, indicator, params_hash, alignment_source)

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf_u (
    id               bigint       NOT NULL,
    ts               timestamptz  NOT NULL,
    tf               text         NOT NULL,
    tf_days          integer      NOT NULL,
    indicator        text         NOT NULL,
    params_hash      text         NOT NULL,
    alignment_source text         NOT NULL DEFAULT 'multi_tf',
    roll             boolean      NOT NULL,

    gap_days              integer,
    gap_days_roll         integer,

    -- ama roll (unified timeline, ALL rows)
    delta1_ama_roll             double precision,
    delta2_ama_roll             double precision,
    ret_arith_ama_roll          double precision,
    delta_ret_arith_ama_roll    double precision,
    ret_log_ama_roll            double precision,
    delta_ret_log_ama_roll      double precision,

    -- ama canonical (roll=FALSE partition only)
    delta1_ama                  double precision,
    delta2_ama                  double precision,
    ret_arith_ama               double precision,
    delta_ret_arith_ama         double precision,
    ret_log_ama                 double precision,
    delta_ret_log_ama           double precision,

    -- Z-scores: 30-day window
    ret_arith_ama_zscore_30           double precision,
    ret_log_ama_zscore_30             double precision,
    ret_arith_ama_roll_zscore_30      double precision,
    ret_log_ama_roll_zscore_30        double precision,

    -- Z-scores: 90-day window
    ret_arith_ama_zscore_90           double precision,
    ret_log_ama_zscore_90             double precision,
    ret_arith_ama_roll_zscore_90      double precision,
    ret_log_ama_roll_zscore_90        double precision,

    -- Z-scores: 365-day window
    ret_arith_ama_zscore_365          double precision,
    ret_log_ama_zscore_365            double precision,
    ret_arith_ama_roll_zscore_365     double precision,
    ret_log_ama_roll_zscore_365       double precision,

    -- Outlier flag (TRUE if any |z-score| > 4 across all windows)
    is_outlier                    boolean,

    ingested_at      timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, indicator, params_hash, alignment_source)
);

CREATE INDEX IF NOT EXISTS ix_ret_ama_u_key_ts
ON public.cmc_returns_ama_multi_tf_u (id, tf, indicator, params_hash, alignment_source, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ama_u_indicator
ON public.cmc_returns_ama_multi_tf_u (indicator, params_hash, tf);

CREATE INDEX IF NOT EXISTS ix_ret_ama_u_alignment_source
ON public.cmc_returns_ama_multi_tf_u (alignment_source);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf_u_state (
    id               bigint      NOT NULL,
    tf               text        NOT NULL,
    indicator        text        NOT NULL,
    params_hash      text        NOT NULL,
    alignment_source text        NOT NULL,
    last_ts          timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash, alignment_source)
);

COMMIT;
