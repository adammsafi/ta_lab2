WITH
snap AS (
  SELECT DISTINCT
    CASE tf
      WHEN '1M_CAL'  THEN '30D'
      WHEN '2M_CAL'  THEN '60D'
      WHEN '3M_CAL'  THEN '90D'
      WHEN '12M_CAL' THEN '360D'
      WHEN '1Y_CAL'  THEN '365D'
      ELSE tf
    END AS tf_norm
  FROM public.cmc_price_bars_multi_tf_snapshot_20251213
),
cur AS (
  SELECT DISTINCT tf AS tf_norm
  FROM public.cmc_price_bars_multi_tf
)
SELECT 'in_snap_not_cur' AS side, tf_norm FROM snap
EXCEPT
SELECT 'in_snap_not_cur', tf_norm FROM cur
UNION ALL
SELECT 'in_cur_not_snap' AS side, tf_norm FROM cur
EXCEPT
SELECT 'in_cur_not_snap', tf_norm FROM snap
ORDER BY side, tf_norm;
