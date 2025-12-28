---Next (if you care about the actual EMA values)
---If you want to confirm that the EMA numbers also match (not just counts), run:

SELECT
    COUNT(*)                                   AS n_rows_compared,
    SUM( (d.ema IS DISTINCT FROM s.ema)::int ) AS n_mismatched,
    AVG(ABS(d.ema - s.ema))                    AS avg_abs_diff
FROM cmc_ema_daily d
JOIN cmc_ema_daily_20251124_snapshot s
  ON d.id = s.id
 AND d.ts = s.ts
 AND d.period = s.period
WHERE d.id IN (1, 52, 1027, 1839, 1975, 5426, 32196);

---If you want to dig one level deeper
---If you’re curious where those 3,670 mismatches are concentrated, run:
---(a) Check max diff + distribution
SELECT
    MAX(ABS(d.ema - s.ema))      AS max_abs_diff,
    MIN(ABS(d.ema - s.ema))      AS min_abs_diff,
    AVG(ABS(d.ema - s.ema))      AS avg_abs_diff,
    COUNT(*)                     AS n_mismatched
FROM cmc_ema_daily d
JOIN cmc_ema_daily_20251124_snapshot s
  ON d.id = s.id
 AND d.ts = s.ts
 AND d.period = s.period
WHERE d.ema IS DISTINCT FROM s.ema;

---See where in time the mismatches happen
SELECT
    id,
    period,
    MIN(ts) AS first_mismatch_ts,
    MAX(ts) AS last_mismatch_ts,
    COUNT(*) AS n_mismatched
FROM (
    SELECT
        d.id,
        d.period,
        d.ts
    FROM cmc_ema_daily d
    JOIN cmc_ema_daily_20251124_snapshot s
      ON d.id = s.id
     AND d.ts = s.ts
     AND d.period = s.period
    WHERE d.ema IS DISTINCT FROM s.ema
) AS x
GROUP BY id, period
ORDER BY id, period;


