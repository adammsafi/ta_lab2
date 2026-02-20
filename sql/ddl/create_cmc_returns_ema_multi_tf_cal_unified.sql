-- create_cmc_returns_ema_multi_tf_cal_unified.sql
--
-- Unified timeline returns per scheme (US / ISO).
-- Non-roll columns populated on roll=FALSE; roll columns on ALL rows.
-- PK: (id, ts, tf, period) — roll is a regular boolean column.

BEGIN;

-- ============================================================
-- CAL US unified returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_us (
    id          bigint       NOT NULL,
    ts          timestamptz  NOT NULL,
    tf          text         NOT NULL,
    tf_days     integer      NOT NULL,
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

    -- Z-scores: 30-day window (canonical, roll=FALSE only)
    ret_arith_ema_zscore_30           double precision,
    ret_arith_ema_bar_zscore_30       double precision,
    ret_log_ema_zscore_30             double precision,
    ret_log_ema_bar_zscore_30         double precision,
    -- Z-scores: 30-day window (roll, ALL rows)
    ret_arith_ema_roll_zscore_30      double precision,
    ret_arith_ema_bar_roll_zscore_30  double precision,
    ret_log_ema_roll_zscore_30        double precision,
    ret_log_ema_bar_roll_zscore_30    double precision,

    -- Z-scores: 90-day window (canonical, roll=FALSE only)
    ret_arith_ema_zscore_90           double precision,
    ret_arith_ema_bar_zscore_90       double precision,
    ret_log_ema_zscore_90             double precision,
    ret_log_ema_bar_zscore_90         double precision,
    -- Z-scores: 90-day window (roll, ALL rows)
    ret_arith_ema_roll_zscore_90      double precision,
    ret_arith_ema_bar_roll_zscore_90  double precision,
    ret_log_ema_roll_zscore_90        double precision,
    ret_log_ema_bar_roll_zscore_90    double precision,

    -- Z-scores: 365-day window (canonical, roll=FALSE only)
    ret_arith_ema_zscore_365          double precision,
    ret_arith_ema_bar_zscore_365      double precision,
    ret_log_ema_zscore_365            double precision,
    ret_log_ema_bar_zscore_365        double precision,
    -- Z-scores: 365-day window (roll, ALL rows)
    ret_arith_ema_roll_zscore_365     double precision,
    ret_arith_ema_bar_roll_zscore_365 double precision,
    ret_log_ema_roll_zscore_365       double precision,
    ret_log_ema_bar_roll_zscore_365   double precision,

    -- Outlier flag (TRUE if any |z-score| > 4 across all windows)
    is_outlier                    boolean,

    ingested_at timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_us_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_us_key
ON public.cmc_returns_ema_multi_tf_cal_us (id, tf, period, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_us_ingested
ON public.cmc_returns_ema_multi_tf_cal_us (ingested_at);


-- ============================================================
-- CAL ISO unified returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_iso (
    id          bigint       NOT NULL,
    ts          timestamptz  NOT NULL,
    tf          text         NOT NULL,
    tf_days     integer      NOT NULL,
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

    -- Z-scores: 30-day window (canonical, roll=FALSE only)
    ret_arith_ema_zscore_30           double precision,
    ret_arith_ema_bar_zscore_30       double precision,
    ret_log_ema_zscore_30             double precision,
    ret_log_ema_bar_zscore_30         double precision,
    -- Z-scores: 30-day window (roll, ALL rows)
    ret_arith_ema_roll_zscore_30      double precision,
    ret_arith_ema_bar_roll_zscore_30  double precision,
    ret_log_ema_roll_zscore_30        double precision,
    ret_log_ema_bar_roll_zscore_30    double precision,

    -- Z-scores: 90-day window (canonical, roll=FALSE only)
    ret_arith_ema_zscore_90           double precision,
    ret_arith_ema_bar_zscore_90       double precision,
    ret_log_ema_zscore_90             double precision,
    ret_log_ema_bar_zscore_90         double precision,
    -- Z-scores: 90-day window (roll, ALL rows)
    ret_arith_ema_roll_zscore_90      double precision,
    ret_arith_ema_bar_roll_zscore_90  double precision,
    ret_log_ema_roll_zscore_90        double precision,
    ret_log_ema_bar_roll_zscore_90    double precision,

    -- Z-scores: 365-day window (canonical, roll=FALSE only)
    ret_arith_ema_zscore_365          double precision,
    ret_arith_ema_bar_zscore_365      double precision,
    ret_log_ema_zscore_365            double precision,
    ret_log_ema_bar_zscore_365        double precision,
    -- Z-scores: 365-day window (roll, ALL rows)
    ret_arith_ema_roll_zscore_365     double precision,
    ret_arith_ema_bar_roll_zscore_365 double precision,
    ret_log_ema_roll_zscore_365       double precision,
    ret_log_ema_bar_roll_zscore_365   double precision,

    -- Outlier flag (TRUE if any |z-score| > 4 across all windows)
    is_outlier                    boolean,

    ingested_at timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_iso_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_iso_key
ON public.cmc_returns_ema_multi_tf_cal_iso (id, tf, period, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_iso_ingested
ON public.cmc_returns_ema_multi_tf_cal_iso (ingested_at);

COMMIT;
