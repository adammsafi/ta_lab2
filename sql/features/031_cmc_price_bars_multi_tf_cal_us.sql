CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_cal_us (
  id          integer                     NOT NULL,
  tf          text                        NOT NULL,
  tf_days     integer                     NOT NULL,
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
  CONSTRAINT pk_cmc_price_bars_multi_tf_cal_us PRIMARY KEY (id, tf, bar_seq)
);

-- Optional helper index (common query pattern)
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_us_id_tf_timeclose
  ON public.cmc_price_bars_multi_tf_cal_us (id, tf, time_close);

SELECT *
FROM cmc_price_bars_multi_tf_cal_us
WHERE id=1 and tf ='1Y_CAL'
ORDER BY time_close
LIMIT 5
