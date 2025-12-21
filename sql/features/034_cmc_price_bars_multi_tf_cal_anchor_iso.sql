CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_cal_anchor_iso (
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
  CONSTRAINT pk_cmc_price_bars_multi_tf_cal_anchor_iso PRIMARY KEY (id, tf, bar_seq)
);

CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_anchor_iso_id_tf_timeclose
  ON public.cmc_price_bars_multi_tf_cal_anchor_iso (id, tf, time_close);

SELECT 
	DISTINCT(tf),
	tf_days
FROM cmc_price_bars_multi_tf_cal_anchor_iso
ORDER BY tf_days, tf

WHERE id = 1 and tf = '1Y_ISO'
ORDER BY time_close
LIMIT 10

SELECT *
FROM cmc_price_histories7
WHERE id = 1
ORDER BY cmc_price_histories7.timeopen
LIMIT 1

SELECT *
FROM dim_timeframe

SELECT *
FROM cmc_price_bars_multi_tf_cal_anchor_iso
WHERE id=1
ORDER BY time_close DESC
LIMIT 100