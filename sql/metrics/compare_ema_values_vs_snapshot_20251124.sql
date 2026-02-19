--- Compare actual EMA values between current and snapshot for multi_tf

SELECT
    COUNT(*)                                   AS n_rows_compared,
    SUM( (d.ema IS DISTINCT FROM s.ema)::int ) AS n_mismatched,
    AVG(ABS(d.ema - s.ema))                    AS avg_abs_diff
FROM cmc_ema_multi_tf d
JOIN cmc_ema_multi_tf_20251124_snapshot s
  ON d.id = s.id
 AND d.ts = s.ts
 AND d.tf = s.tf
 AND d.period = s.period
WHERE d.id IN (1, 52, 1027, 1839, 1975, 5426, 32196);

--- Check max diff + distribution
SELECT
    MAX(ABS(d.ema - s.ema))      AS max_abs_diff,
    MIN(ABS(d.ema - s.ema))      AS min_abs_diff,
    AVG(ABS(d.ema - s.ema))      AS avg_abs_diff,
    COUNT(*)                     AS n_mismatched
FROM cmc_ema_multi_tf d
JOIN cmc_ema_multi_tf_20251124_snapshot s
  ON d.id = s.id
 AND d.ts = s.ts
 AND d.tf = s.tf
 AND d.period = s.period
WHERE d.ema IS DISTINCT FROM s.ema;

--- See where in time the mismatches happen
SELECT
    id,
    tf,
    period,
    MIN(ts) AS first_mismatch_ts,
    MAX(ts) AS last_mismatch_ts,
    COUNT(*) AS n_mismatched
FROM (
    SELECT
        d.id,
        d.tf,
        d.period,
        d.ts
    FROM cmc_ema_multi_tf d
    JOIN cmc_ema_multi_tf_20251124_snapshot s
      ON d.id = s.id
     AND d.ts = s.ts
     AND d.tf = s.tf
     AND d.period = s.period
    WHERE d.ema IS DISTINCT FROM s.ema
) AS x
GROUP BY id, tf, period
ORDER BY id, tf, period;
