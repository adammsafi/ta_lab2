-- create_cmc_returns_ama_multi_tf_cal_anchor.sql
-- Creates calendar-anchor AMA returns tables:
--   public.cmc_returns_ama_multi_tf_cal_anchor_us       (US anchor alignment)
--   public.cmc_returns_ama_multi_tf_cal_anchor_us_state
--   public.cmc_returns_ama_multi_tf_cal_anchor_iso      (ISO anchor alignment)
--   public.cmc_returns_ama_multi_tf_cal_anchor_iso_state
--
-- Same column schema as cmc_returns_ama_multi_tf.
-- PK: (id, ts, tf, indicator, params_hash)

BEGIN;

-- ============================================================
-- CAL ANCHOR US returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf_cal_anchor_us (
    id              bigint       NOT NULL,
    ts              timestamptz  NOT NULL,
    tf              text         NOT NULL,
    tf_days         integer      NOT NULL,
    indicator       text         NOT NULL,
    params_hash     text         NOT NULL,
    roll            boolean      NOT NULL,

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

    ingested_at     timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf_cal_anchor_us_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    indicator   text        NOT NULL,
    params_hash text        NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ama_cal_anchor_us_key
ON public.cmc_returns_ama_multi_tf_cal_anchor_us (id, tf, indicator, params_hash, ts);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ama_cal_anchor_us_ingested
ON public.cmc_returns_ama_multi_tf_cal_anchor_us (ingested_at);


-- ============================================================
-- CAL ANCHOR ISO returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf_cal_anchor_iso (
    id              bigint       NOT NULL,
    ts              timestamptz  NOT NULL,
    tf              text         NOT NULL,
    tf_days         integer      NOT NULL,
    indicator       text         NOT NULL,
    params_hash     text         NOT NULL,
    roll            boolean      NOT NULL,

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

    ingested_at     timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf_cal_anchor_iso_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    indicator   text        NOT NULL,
    params_hash text        NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ama_cal_anchor_iso_key
ON public.cmc_returns_ama_multi_tf_cal_anchor_iso (id, tf, indicator, params_hash, ts);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ama_cal_anchor_iso_ingested
ON public.cmc_returns_ama_multi_tf_cal_anchor_iso (ingested_at);

COMMIT;
