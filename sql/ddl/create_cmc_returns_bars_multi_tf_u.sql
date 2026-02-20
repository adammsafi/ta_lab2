-- create_cmc_returns_bars_multi_tf_u.sql
--
-- Unified bar returns: union of all 5 alignment variants with alignment_source.
-- PK: (id, "timestamp", tf, alignment_source)

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_returns_bars_multi_tf_u (
    id                          integer       NOT NULL,
    "timestamp"                 timestamptz   NOT NULL,
    tf                          text          NOT NULL,
    alignment_source            text          NOT NULL,

    tf_days                     integer,
    bar_seq                     integer,
    pos_in_bar                  integer,
    count_days                  integer,
    count_days_remaining        integer,
    roll                        boolean       NOT NULL,
    time_close                  timestamptz,
    time_close_bar              timestamptz,
    time_open_bar               timestamptz,
    gap_bars                    integer,

    -- roll columns (ALL rows)
    delta1_roll                 double precision,
    delta2_roll                 double precision,
    ret_arith_roll              double precision,
    delta_ret_arith_roll        double precision,
    ret_log_roll                double precision,
    delta_ret_log_roll          double precision,
    range_roll                  double precision,
    range_pct_roll              double precision,
    true_range_roll             double precision,
    true_range_pct_roll         double precision,

    -- canonical columns (roll=FALSE only)
    delta1                      double precision,
    delta2                      double precision,
    ret_arith                   double precision,
    delta_ret_arith             double precision,
    ret_log                     double precision,
    delta_ret_log               double precision,
    "range"                     double precision,
    range_pct                   double precision,
    true_range                  double precision,
    true_range_pct              double precision,

    -- Z-scores: 30-day window (canonical, roll=FALSE only)
    ret_arith_zscore_30             double precision,
    delta_ret_arith_zscore_30       double precision,
    ret_log_zscore_30               double precision,
    delta_ret_log_zscore_30         double precision,
    -- Z-scores: 30-day window (roll, ALL rows)
    ret_arith_roll_zscore_30        double precision,
    delta_ret_arith_roll_zscore_30  double precision,
    ret_log_roll_zscore_30          double precision,
    delta_ret_log_roll_zscore_30    double precision,

    -- Z-scores: 90-day window (canonical, roll=FALSE only)
    ret_arith_zscore_90             double precision,
    delta_ret_arith_zscore_90       double precision,
    ret_log_zscore_90               double precision,
    delta_ret_log_zscore_90         double precision,
    -- Z-scores: 90-day window (roll, ALL rows)
    ret_arith_roll_zscore_90        double precision,
    delta_ret_arith_roll_zscore_90  double precision,
    ret_log_roll_zscore_90          double precision,
    delta_ret_log_roll_zscore_90    double precision,

    -- Z-scores: 365-day window (canonical, roll=FALSE only)
    ret_arith_zscore_365            double precision,
    delta_ret_arith_zscore_365      double precision,
    ret_log_zscore_365              double precision,
    delta_ret_log_zscore_365        double precision,
    -- Z-scores: 365-day window (roll, ALL rows)
    ret_arith_roll_zscore_365       double precision,
    delta_ret_arith_roll_zscore_365 double precision,
    ret_log_roll_zscore_365         double precision,
    delta_ret_log_roll_zscore_365   double precision,

    -- Outlier flag (TRUE if any |z-score| > 4 across all windows)
    is_outlier                  boolean,

    ingested_at                 timestamptz   NOT NULL DEFAULT now(),

    PRIMARY KEY (id, "timestamp", tf, alignment_source)
);

CREATE INDEX IF NOT EXISTS ix_returns_bars_u_alignment
ON public.cmc_returns_bars_multi_tf_u (alignment_source);

CREATE INDEX IF NOT EXISTS ix_returns_bars_u_id_tf_ts
ON public.cmc_returns_bars_multi_tf_u (id, tf, "timestamp");

CREATE INDEX IF NOT EXISTS ix_returns_bars_u_ingested
ON public.cmc_returns_bars_multi_tf_u (ingested_at);

COMMIT;
