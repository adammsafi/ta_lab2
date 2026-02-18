WITH cur_close AS (
  SELECT *
  FROM public.cmc_ema_multi_tf
  WHERE roll = FALSE
),
snap_close AS (
  SELECT *
  FROM public.cmc_ema_multi_tf_snapshot_20251214
  WHERE roll = FALSE
),
cur_first AS (
  SELECT DISTINCT ON (id, tf, period) id, tf, period, ts, ema
  FROM cur_close
  ORDER BY id, tf, period, ts ASC
),
snap_first AS (
  SELECT DISTINCT ON (id, tf, period) id, tf, period, ts, ema
  FROM snap_close
  ORDER BY id, tf, period, ts ASC
),
cur_last AS (
  SELECT DISTINCT ON (id, tf, period) id, tf, period, ts, ema
  FROM cur_close
  ORDER BY id, tf, period, ts DESC
),
snap_last AS (
  SELECT DISTINCT ON (id, tf, period) id, tf, period, ts, ema
  FROM snap_close
  ORDER BY id, tf, period, ts DESC
)
SELECT
  'FIRST' AS which_bar,
  COUNT(*) FILTER (WHERE cf.ts = sf.ts AND cf.ema IS NOT DISTINCT FROM sf.ema) AS n_match,
  COUNT(*) AS n_total
FROM cur_first cf
JOIN snap_first sf USING (id, tf, period)

UNION ALL

SELECT
  'LAST' AS which_bar,
  COUNT(*) FILTER (WHERE cl.ts = sl.ts AND cl.ema IS NOT DISTINCT FROM sl.ema) AS n_match,
  COUNT(*) AS n_total
FROM cur_last cl
JOIN snap_last sl USING (id, tf, period);
