-- ============================
-- Returns on bar snapshots (wide-column, dual-LAG)
-- Source bars: public.cmc_price_bars_multi_tf_cal_iso
-- PK: (id, "timestamp", tf)
-- ============================

DROP TABLE IF EXISTS public.cmc_returns_bars_multi_tf_cal_iso CASCADE;

CREATE TABLE public.cmc_returns_bars_multi_tf_cal_iso (
    id                      integer       NOT NULL,
    "timestamp"             timestamptz   NOT NULL,
    tf                      text          NOT NULL,

    tf_days                 integer,
    bar_seq                 integer,
    pos_in_bar              integer,
    count_days              integer,
    count_days_remaining    integer,

    roll                    boolean       NOT NULL,

    time_close              timestamptz,
    time_close_bar          timestamptz,
    time_open_bar           timestamptz,

    gap_bars                integer,

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

    ingested_at             timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT cmc_returns_bars_multi_tf_cal_iso_pk PRIMARY KEY (id, "timestamp", tf)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_bars_multi_tf_cal_iso_id_tf_ts
ON public.cmc_returns_bars_multi_tf_cal_iso (id, tf, "timestamp");

DROP TABLE IF EXISTS public.cmc_returns_bars_multi_tf_cal_iso_state CASCADE;

CREATE TABLE public.cmc_returns_bars_multi_tf_cal_iso_state (
    id              integer       NOT NULL,
    tf              text          NOT NULL,
    last_timestamp  timestamptz,
    updated_at      timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT cmc_returns_bars_multi_tf_cal_iso_state_pk PRIMARY KEY (id, tf)
);
