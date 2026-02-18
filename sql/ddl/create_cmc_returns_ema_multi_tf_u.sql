-- create_cmc_returns_ema_multi_tf_u.sql
-- Unified EMA returns built from public.cmc_ema_multi_tf_u
--
-- Unified timeline: _ema/_ema_bar + _roll pairs.
-- Non-roll columns populated on roll=FALSE; roll columns on ALL rows.
--
-- PK: (id, ts, tf, period, alignment_source) — roll is a regular boolean column.
--
-- State keyed by:
--   (id, tf, period, alignment_source) -> last_ts

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_u (
    id               bigint NOT NULL,
    ts               timestamptz NOT NULL,
    tf               text NOT NULL,
    tf_days          integer NOT NULL,
    period           integer NOT NULL,
    alignment_source text NOT NULL,
    roll             boolean NOT NULL,

    gap_days              integer,
    gap_days_roll         integer,

    -- ema roll (unified timeline)
    delta1_ema_roll             double precision,
    delta2_ema_roll             double precision,
    ret_arith_ema_roll          double precision,
    delta_ret_arith_ema_roll    double precision,
    ret_log_ema_roll            double precision,
    delta_ret_log_ema_roll      double precision,

    -- ema canonical (roll=FALSE partition)
    delta1_ema                  double precision,
    delta2_ema                  double precision,
    ret_arith_ema               double precision,
    delta_ret_arith_ema         double precision,
    ret_log_ema                 double precision,
    delta_ret_log_ema           double precision,

    -- ema_bar roll (unified timeline)
    delta1_ema_bar_roll         double precision,
    delta2_ema_bar_roll         double precision,
    ret_arith_ema_bar_roll      double precision,
    delta_ret_arith_ema_bar_roll double precision,
    ret_log_ema_bar_roll        double precision,
    delta_ret_log_ema_bar_roll  double precision,

    -- ema_bar canonical (roll=FALSE partition)
    delta1_ema_bar              double precision,
    delta2_ema_bar              double precision,
    ret_arith_ema_bar           double precision,
    delta_ret_arith_ema_bar     double precision,
    ret_log_ema_bar             double precision,
    delta_ret_log_ema_bar       double precision,

    ingested_at      timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period, alignment_source)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_u_key_ts
ON public.cmc_returns_ema_multi_tf_u (id, tf, period, alignment_source, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_u_tf_period
ON public.cmc_returns_ema_multi_tf_u (tf, period);

CREATE INDEX IF NOT EXISTS ix_ret_ema_u_alignment_source
ON public.cmc_returns_ema_multi_tf_u (alignment_source);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_u_state (
    id               bigint NOT NULL,
    tf               text NOT NULL,
    period           integer NOT NULL,
    alignment_source text NOT NULL,
    last_ts          timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, tf, period, alignment_source)
);

COMMIT;
