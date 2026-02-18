SELECT 'current'  AS which, COUNT(*) AS n_rows FROM public.cmc_ema_multi_tf
UNION ALL
SELECT 'snapshot' AS which, COUNT(*) AS n_rows FROM public.cmc_ema_multi_tf_snapshot_20251214;

WITH cur AS (
  SELECT id, tf, ts, period
  FROM public.cmc_ema_multi_tf
),
snap AS (
  SELECT id, tf, ts, period
  FROM public.cmc_ema_multi_tf_snapshot_20251214
)
SELECT 'only_in_current' AS which, COUNT(*) AS n
FROM cur
LEFT JOIN snap USING (id, tf, period)
WHERE snap.id IS NULL
UNION ALL
SELECT 'only_in_snapshot' AS which, COUNT(*) AS n
FROM snap
LEFT JOIN cur USING (id, tf, period)
WHERE cur.id IS NULL;
