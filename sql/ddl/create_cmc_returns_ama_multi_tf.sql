-- create_cmc_returns_ama_multi_tf.sql
-- Creates:
--   public.cmc_returns_ama_multi_tf       (main AMA returns table)
--   public.cmc_returns_ama_multi_tf_state (watermark state)
--
-- PK: (id, ts, tf, indicator, params_hash) -- roll is a regular boolean column.
-- Non-roll columns: populated only on roll=FALSE rows (canonical->canonical LAG).
-- Roll columns: populated on ALL rows (unified timeline LAG, incl. cross-roll transitions).
-- No _ema_bar columns -- AMA has no bar-space variant.
-- Z-scores: 4 base columns x 3 windows = 12 z-score columns.

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf (
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

    -- Z-scores: 30-day window (canonical, roll=FALSE only)
    ret_arith_ama_zscore_30           double precision,
    ret_log_ama_zscore_30             double precision,
    -- Z-scores: 30-day window (roll, ALL rows)
    ret_arith_ama_roll_zscore_30      double precision,
    ret_log_ama_roll_zscore_30        double precision,

    -- Z-scores: 90-day window (canonical, roll=FALSE only)
    ret_arith_ama_zscore_90           double precision,
    ret_log_ama_zscore_90             double precision,
    -- Z-scores: 90-day window (roll, ALL rows)
    ret_arith_ama_roll_zscore_90      double precision,
    ret_log_ama_roll_zscore_90        double precision,

    -- Z-scores: 365-day window (canonical, roll=FALSE only)
    ret_arith_ama_zscore_365          double precision,
    ret_log_ama_zscore_365            double precision,
    -- Z-scores: 365-day window (roll, ALL rows)
    ret_arith_ama_roll_zscore_365     double precision,
    ret_log_ama_roll_zscore_365       double precision,

    -- Outlier flag (TRUE if any |z-score| > 4 across all windows)
    is_outlier                    boolean,

    ingested_at     timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    indicator   text        NOT NULL,
    params_hash text        NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, indicator, params_hash)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ama_multi_tf_key
ON public.cmc_returns_ama_multi_tf (id, tf, indicator, params_hash, ts);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ama_multi_tf_ingested_at
ON public.cmc_returns_ama_multi_tf (ingested_at);

COMMIT;
