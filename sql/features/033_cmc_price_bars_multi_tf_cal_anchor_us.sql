CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_cal_anchor_us (
  id          integer                     NOT NULL,
  tf          text                        NOT NULL,
  tf_days     integer                     NOT NULL,  -- ACTUAL number of daily rows in the bar (partial bars vary)
  bar_seq     integer                     NOT NULL,
  time_open   timestamptz                 NOT NULL,
  time_close  timestamptz                 NOT NULL,
  time_high   timestamptz                 NOT NULL,
  time_low    timestamptz                 NOT NULL,
  open        double precision            NOT NULL,
  high        double precision            NOT NULL,
  low         double precision            NOT NULL,
  close       double precision            NOT NULL,
  volume      double precision            NOT NULL,
  market_cap  double precision            NOT NULL,
  ingested_at timestamptz                 NOT NULL DEFAULT now(),
  CONSTRAINT pk_cmc_price_bars_multi_tf_cal_anchor_us PRIMARY KEY (id, tf, bar_seq)
);

CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_anchor_us_id_tf_timeclose
  ON public.cmc_price_bars_multi_tf_cal_anchor_us (id, tf, time_close);
