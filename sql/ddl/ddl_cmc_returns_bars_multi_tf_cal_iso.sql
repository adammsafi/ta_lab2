-- ============================
-- Returns on bar snapshots (time_close keyed)
-- Source bars: public.cmc_price_bars_multi_tf_cal_iso
-- ============================

CREATE TABLE IF NOT EXISTS public.cmc_returns_bars_multi_tf_cal_iso (
    id           integer NOT NULL,
    tf           text    NOT NULL,
    time_close   timestamptz NOT NULL,
    close        double precision,
    prev_close   double precision,
    gap_days     double precision,
    ret_arith    double precision,
    ret_log      double precision,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cmc_returns_bars_multi_tf_cal_iso_pk PRIMARY KEY (id, tf, time_close)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_bars_multi_tf_cal_iso_time_close
ON public.cmc_returns_bars_multi_tf_cal_iso (id, tf, time_close);

CREATE TABLE IF NOT EXISTS public.cmc_returns_bars_multi_tf_cal_iso_state (
    id              integer NOT NULL,
    tf              text    NOT NULL,
    last_time_close timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cmc_returns_bars_multi_tf_cal_iso_state_pk PRIMARY KEY (id, tf)
);
