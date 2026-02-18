WITH
snap AS (
  SELECT
    CASE tf
      WHEN '1M_CAL'  THEN '30D'
      WHEN '2M_CAL'  THEN '60D'
      WHEN '3M_CAL'  THEN '90D'
      WHEN '12M_CAL' THEN '360D'
      WHEN '1Y_CAL'  THEN '365D'
      ELSE tf
    END AS tf_norm,
    COUNT(*) AS n
  FROM public.cmc_price_bars_multi_tf_snapshot_20251213
  GROUP BY 1
),
cur AS (
  SELECT tf AS tf_norm, COUNT(*) AS n
  FROM public.cmc_price_bars_multi_tf
  GROUP BY 1
)
SELECT
  COALESCE(s.tf_norm, c.tf_norm) AS tf_norm,
  COALESCE(s.n, 0) AS snap_n,
  COALESCE(c.n, 0) AS cur_n,
  COALESCE(c.n, 0) - COALESCE(s.n, 0) AS delta
FROM snap s
FULL OUTER JOIN cur c USING (tf_norm)
ORDER BY delta DESC, tf_norm;
