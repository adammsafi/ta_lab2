WITH j AS (
  SELECT
    c.id, c.tf, c.ts, c.period,
    c.ema, s.ema AS ema_snap,
    c.d1,  s.d1  AS d1_snap,
    c.d2,  s.d2  AS d2_snap,
    c.d1_roll, s.d1_roll AS d1_roll_snap,
    c.d2_roll, s.d2_roll AS d2_roll_snap,
    c.tf_days, s.tf_days AS tf_days_snap,
    c.roll,    s.roll    AS roll_snap
  FROM public.cmc_ema_multi_tf c
  JOIN public.cmc_ema_multi_tf_snapshot_20251214 s
    USING (id, tf, ts, period)
),
d AS (
  SELECT *,
    ABS(ema - ema_snap)         AS ema_abs_diff,
    ABS(d1 - d1_snap)           AS d1_abs_diff,
    ABS(d2 - d2_snap)           AS d2_abs_diff,
    ABS(d1_roll - d1_roll_snap) AS d1r_abs_diff,
    ABS(d2_roll - d2_roll_snap) AS d2r_abs_diff
  FROM j
)
SELECT
  COUNT(*) AS n_joined,
  SUM(CASE WHEN
      (ema      IS NOT DISTINCT FROM ema_snap) AND
      (tf_days  IS NOT DISTINCT FROM tf_days_snap) AND
      (roll     IS NOT DISTINCT FROM roll_snap) AND
      (d1       IS NOT DISTINCT FROM d1_snap) AND
      (d2       IS NOT DISTINCT FROM d2_snap) AND
      (d1_roll  IS NOT DISTINCT FROM d1_roll_snap) AND
      (d2_roll  IS NOT DISTINCT FROM d2_roll_snap)
    THEN 1 ELSE 0 END
  ) AS n_exact_match,
  SUM(CASE WHEN
      NOT (
        (ema      IS NOT DISTINCT FROM ema_snap) AND
        (tf_days  IS NOT DISTINCT FROM tf_days_snap) AND
        (roll     IS NOT DISTINCT FROM roll_snap) AND
        (d1       IS NOT DISTINCT FROM d1_snap) AND
        (d2       IS NOT DISTINCT FROM d2_snap) AND
        (d1_roll  IS NOT DISTINCT FROM d1_roll_snap) AND
        (d2_roll  IS NOT DISTINCT FROM d2_roll_snap)
      )
    THEN 1 ELSE 0 END
  ) AS n_any_diff
FROM j;

WITH j AS (
  SELECT
    c.id, c.tf, c.ts, c.period,
    c.ema, s.ema AS ema_snap,
    ABS(c.ema - s.ema) AS ema_abs_diff
  FROM public.cmc_ema_multi_tf c
  JOIN public.cmc_ema_multi_tf_snapshot_20251214 s
    USING (id, tf, ts, period)
  WHERE c.ema IS NOT NULL AND s.ema IS NOT NULL
)
SELECT *
FROM j
ORDER BY ema_abs_diff DESC
LIMIT 50;
