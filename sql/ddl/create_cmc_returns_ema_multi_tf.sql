-- create_cmc_returns_ema_multi_tf.sql
-- Creates:
--   public.cmc_returns_ema_multi_tf       (unified timeline: _ema/_ema_bar + _roll pairs)
--   public.cmc_returns_ema_multi_tf_state
--
-- PK: (id, ts, tf, period) — roll is a regular boolean column.
-- Non-roll columns: populated only on roll=FALSE rows (canonical→canonical LAG).
-- Roll columns: populated on ALL rows (unified timeline LAG, incl. cross-roll transitions).

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf (
    id          bigint       NOT NULL,
    ts          timestamptz  NOT NULL,
    tf          text         NOT NULL,
    period      integer      NOT NULL,
    roll        boolean      NOT NULL,

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

    ingested_at timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ema_multi_tf_key
ON public.cmc_returns_ema_multi_tf (id, tf, period, ts);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ema_multi_tf_ingested_at
ON public.cmc_returns_ema_multi_tf (ingested_at);

COMMIT;
