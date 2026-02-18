WITH
snap AS (
  SELECT
    id,
    CASE tf
      WHEN '1M_CAL'  THEN '30D'
      WHEN '2M_CAL'  THEN '60D'
      WHEN '3M_CAL'  THEN '90D'
      WHEN '12M_CAL' THEN '360D'
      WHEN '1Y_CAL'  THEN '365D'
      ELSE tf
    END AS tf_norm,
    bar_seq,
    tf_days,
    time_open, time_close, time_high, time_low,
    open, high, low, close, volume, market_cap
  FROM public.cmc_price_bars_multi_tf_snapshot_20251213
),
cur AS (
  SELECT
    id,
    tf AS tf_norm,
    bar_seq,
    tf_days,
    time_open, time_close, time_high, time_low,
    open, high, low, close, volume, market_cap
  FROM public.cmc_price_bars_multi_tf
)
SELECT *
FROM snap

EXCEPT
SELECT *
FROM cur
LIMIT 100
UNION ALL
SELECT *
FROM cur
EXCEPT
SELECT *
FROM snap
LIMIT 100;
