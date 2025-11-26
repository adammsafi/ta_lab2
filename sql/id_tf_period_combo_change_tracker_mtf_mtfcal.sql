---Find which (id, tf, period) combos changed in cmc_ema_multi_tf
WITH current AS (
    SELECT id, tf, period, COUNT(*) AS n_rows
    FROM   cmc_ema_multi_tf
    GROUP  BY id, tf, period
),
snap AS (
    SELECT id, tf, period, COUNT(*) AS n_rows
    FROM   cmc_ema_multi_tf_20251124_snapshot
    GROUP  BY id, tf, period
)
SELECT
    COALESCE(c.id, s.id)      AS id,
    COALESCE(c.tf, s.tf)      AS tf,
    COALESCE(c.period, s.period) AS period,
    c.n_rows                  AS n_rows_current,
    s.n_rows                  AS n_rows_snapshot,
    (COALESCE(c.n_rows, 0) - COALESCE(s.n_rows, 0)) AS diff
FROM current c
FULL OUTER JOIN snap s
  ON c.id = s.id
 AND c.tf = s.tf
 AND c.period = s.period
WHERE
    COALESCE(c.n_rows, 0) <> COALESCE(s.n_rows, 0)
ORDER BY id, tf, period;

---Same for cmc_ema_multi_tf_cal
WITH current AS (
    SELECT id, tf, period, COUNT(*) AS n_rows
    FROM   cmc_ema_multi_tf_cal
    GROUP  BY id, tf, period
),
snap AS (
    SELECT id, tf, period, COUNT(*) AS n_rows
    FROM   cmc_ema_multi_tf_cal_20251124_snapshot
    GROUP  BY id, tf, period
)
SELECT
    COALESCE(c.id, s.id)      AS id,
    COALESCE(c.tf, s.tf)      AS tf,
    COALESCE(c.period, s.period) AS period,
    c.n_rows                  AS n_rows_current,
    s.n_rows                  AS n_rows_snapshot,
    (COALESCE(c.n_rows, 0) - COALESCE(s.n_rows, 0)) AS diff
FROM current c
FULL OUTER JOIN snap s
  ON c.id = s.id
 AND c.tf = s.tf
 AND c.period = s.period
WHERE
    COALESCE(c.n_rows, 0) <> COALESCE(s.n_rows, 0)
ORDER BY id, tf, period;
