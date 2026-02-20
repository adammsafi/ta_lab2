-- ============================
-- Returns on bar snapshots (wide-column, dual-LAG)
-- Source bars: public.cmc_price_bars_multi_tf
-- PK: (id, "timestamp", tf)
-- ============================

DROP TABLE IF EXISTS public.cmc_returns_bars_multi_tf CASCADE;

CREATE TABLE public.cmc_returns_bars_multi_tf (
    id                      integer       NOT NULL,
    "timestamp"             timestamptz   NOT NULL,
    tf                      text          NOT NULL,

    -- Bar metadata (denormalized from source)
    tf_days                 integer,
    bar_seq                 integer,
    pos_in_bar              integer,
    count_days              integer,
    count_days_remaining    integer,

    -- Roll flag (TRUE = snapshot/rolling row, FALSE = bar boundary)
    roll                    boolean       NOT NULL,

    -- Time boundaries
    time_close              timestamptz,
    time_close_bar          timestamptz,
    time_open_bar           timestamptz,

    -- Gap (canonical partition only, NULL on roll=TRUE)
    gap_bars                integer,

    -- Roll columns (unified LAG, populated on ALL rows)
    delta1_roll             double precision,
    delta2_roll             double precision,
    ret_arith_roll          double precision,
    delta_ret_arith_roll    double precision,
    ret_log_roll            double precision,
    delta_ret_log_roll      double precision,
    range_roll              double precision,
    range_pct_roll          double precision,
    true_range_roll         double precision,
    true_range_pct_roll     double precision,

    -- Canonical columns (partitioned LAG, NULL on roll=TRUE)
    delta1                  double precision,
    delta2                  double precision,
    ret_arith               double precision,
    delta_ret_arith         double precision,
    ret_log                 double precision,
    delta_ret_log           double precision,
    range                   double precision,
    range_pct               double precision,
    true_range              double precision,
    true_range_pct          double precision,

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

    ingested_at             timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT cmc_returns_bars_multi_tf_pk PRIMARY KEY (id, "timestamp", tf)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_bars_multi_tf_id_tf_ts
ON public.cmc_returns_bars_multi_tf (id, tf, "timestamp");

-- State table: watermark per (id, tf)
DROP TABLE IF EXISTS public.cmc_returns_bars_multi_tf_state CASCADE;

CREATE TABLE public.cmc_returns_bars_multi_tf_state (
    id              integer       NOT NULL,
    tf              text          NOT NULL,
    last_timestamp  timestamptz,
    updated_at      timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT cmc_returns_bars_multi_tf_state_pk PRIMARY KEY (id, tf)
);
