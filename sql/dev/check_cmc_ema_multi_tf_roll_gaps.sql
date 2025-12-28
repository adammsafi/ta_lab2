select * 
from cmc_ema_multi_tf
where id = 1 and tf = '1M'
LIMIT 10

WITH rolls AS (
    SELECT
        ts,
        ROW_NUMBER() OVER (ORDER BY ts) AS rn
    FROM cmc_ema_multi_tf
    WHERE id = 1
      AND tf = '1M'
      AND period = 10
      AND roll = false
    ORDER BY ts
)
SELECT
    r1.ts       AS ts_current,
    r2.ts       AS ts_next,
    r2.ts - r1.ts AS delta
FROM rolls r1
JOIN rolls r2
  ON r2.rn = r1.rn + 1
ORDER BY r1.ts
LIMIT 20;
