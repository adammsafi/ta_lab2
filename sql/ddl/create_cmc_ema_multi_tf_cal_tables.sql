-- ==========================================================
-- Output tables for refresh_cmc_ema_multi_tf_cal_from_bars.py
-- ==========================================================

CREATE TABLE IF NOT EXISTS public.cmc_ema_multi_tf_cal_us (
  id            integer NOT NULL,
  tf            text    NOT NULL,
  ts            timestamptz NOT NULL,
  period        integer NOT NULL,
  tf_days       integer NOT NULL,

  roll          boolean NOT NULL,
  ema           double precision,
  d1            double precision,
  d2            double precision,
  d1_roll       double precision,
  d2_roll       double precision,

  ema_bar       double precision,
  d1_bar        double precision,
  d2_bar        double precision,
  roll_bar      boolean NOT NULL,
  d1_roll_bar   double precision,
  d2_roll_bar   double precision,

  ingested_at   timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT cmc_ema_multi_tf_cal_us_pk PRIMARY KEY (id, tf, ts, period)
);

CREATE INDEX IF NOT EXISTS cmc_ema_multi_tf_cal_us_id_ts_idx
  ON public.cmc_ema_multi_tf_cal_us (id, ts);

CREATE INDEX IF NOT EXISTS cmc_ema_multi_tf_cal_us_tf_ts_idx
  ON public.cmc_ema_multi_tf_cal_us (tf, ts);


CREATE TABLE IF NOT EXISTS public.cmc_ema_multi_tf_cal_iso (
  id            integer NOT NULL,
  tf            text    NOT NULL,
  ts            timestamptz NOT NULL,
  period        integer NOT NULL,
  tf_days       integer NOT NULL,

  roll          boolean NOT NULL,
  ema           double precision,
  d1            double precision,
  d2            double precision,
  d1_roll       double precision,
  d2_roll       double precision,

  ema_bar       double precision,
  d1_bar        double precision,
  d2_bar        double precision,
  roll_bar      boolean NOT NULL,
  d1_roll_bar   double precision,
  d2_roll_bar   double precision,

  ingested_at   timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT cmc_ema_multi_tf_cal_iso_pk PRIMARY KEY (id, tf, ts, period)
);

CREATE INDEX IF NOT EXISTS cmc_ema_multi_tf_cal_iso_id_ts_idx
  ON public.cmc_ema_multi_tf_cal_iso (id, ts);

CREATE INDEX IF NOT EXISTS cmc_ema_multi_tf_cal_iso_tf_ts_idx
  ON public.cmc_ema_multi_tf_cal_iso (tf, ts);
