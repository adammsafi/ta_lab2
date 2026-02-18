-- create_cmc_returns_ema_multi_tf_cal_anchor.sql
--
-- Unified timeline returns per scheme (US / ISO).
-- Non-roll columns populated on roll=FALSE; roll columns on ALL rows.
-- PK: (id, ts, tf, period) — roll is a regular boolean column.

BEGIN;

-- ============================================================
-- CAL ANCHOR US unified returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_anchor_us (
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

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_anchor_us_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_anchor_us_key
ON public.cmc_returns_ema_multi_tf_cal_anchor_us (id, tf, period, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_anchor_us_ingested
ON public.cmc_returns_ema_multi_tf_cal_anchor_us (ingested_at);


-- ============================================================
-- CAL ANCHOR ISO unified returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_anchor_iso (
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

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_anchor_iso_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_anchor_iso_key
ON public.cmc_returns_ema_multi_tf_cal_anchor_iso (id, tf, period, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_anchor_iso_ingested
ON public.cmc_returns_ema_multi_tf_cal_anchor_iso (ingested_at);

COMMIT;
