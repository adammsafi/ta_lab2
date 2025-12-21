-- =============================================================================
-- File: sql/qa/20251213__qa_multi_tf_vs_snapshot_tf_norm.sql
-- Purpose:
--   Compare cmc_price_bars_multi_tf (current) vs snapshot_20251213 after applying
--   a TF normalization mapping on the snapshot side.
--
-- Why:
--   Historically, some TF labels were expressed as *_CAL in older logic.
--   This suite normalizes those snapshot TFs into tf_day labels (e.g., 1M_CAL -> 30D)
--   and then compares the full row content.
--
-- Mapping used (from your query):
--   1M_CAL  -> 30D
--   2M_CAL  -> 60D
--   3M_CAL  -> 90D
--   12M_CAL -> 360D
--   1Y_CAL  -> 365D
--   else unchanged
-- =============================================================================

-- Quick peek helpers (optional)
SELECT *
FROM public.cmc_price_bars_multi_tf
LIMIT 10;

SELECT *
FROM public.cmc_price_bars_multi_tf_snapshot_20251213
LIMIT 10;

-- -----------------------------------------------------------------------------
-- A) Basic row count comparison (after normalization, should still match if 1:1)
-- -----------------------------------------------------------------------------
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
SELECT
  (SELECT COUNT(*) FROM snap) AS snap_rows,
  (SELECT COUNT(*) FROM cur)  AS cur_rows;

-- -----------------------------------------------------------------------------
-- B) Full EXCEPT diffs both directions (sampled to 100 rows)
-- -----------------------------------------------------------------------------
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
(
  SELECT * FROM snap
  EXCEPT
  SELECT * FROM cur
  LIMIT 100
)
UNION ALL
(
  SELECT * FROM cur
  EXCEPT
  SELECT * FROM snap
  LIMIT 100
);

-- -----------------------------------------------------------------------------
-- C) TF coverage differences after normalization
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- D) Per-tf row count deltas (which TFs differ the most)
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- E) Row-level diff flag after join (pinpoints mismatched rows)
-- -----------------------------------------------------------------------------
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
),
joined AS (
  SELECT
    s.id, s.tf_norm, s.bar_seq,
    ROW(
      s.tf_days,
      s.time_open, s.time_close, s.time_high, s.time_low,
      s.open, s.high, s.low, s.close, s.volume, s.market_cap
    ) IS DISTINCT FROM
    ROW(
      c.tf_days,
      c.time_open, c.time_close, c.time_high, c.time_low,
      c.open, c.high, c.low, c.close, c.volume, c.market_cap
    ) AS row_diff
  FROM snap s
  JOIN cur  c
    ON c.id = s.id AND c.tf_norm = s.tf_norm AND c.bar_seq = s.bar_seq
)
SELECT *
FROM joined
WHERE row_diff
LIMIT 50;

-- -----------------------------------------------------------------------------
-- F) Column-by-column diff booleans (when you need “what changed?”)
-- -----------------------------------------------------------------------------
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
SELECT
  s.id, s.tf_norm, s.bar_seq,
  (s.tf_days     IS DISTINCT FROM c.tf_days)     AS diff_tf_days,
  (s.time_open   IS DISTINCT FROM c.time_open)   AS diff_time_open,
  (s.time_close  IS DISTINCT FROM c.time_close)  AS diff_time_close,
  (s.time_high   IS DISTINCT FROM c.time_high)   AS diff_time_high,
  (s.time_low    IS DISTINCT FROM c.time_low)    AS diff_time_low,
  (s.open        IS DISTINCT FROM c.open)        AS diff_open,
  (s.high        IS DISTINCT FROM c.high)        AS diff_high,
  (s.low         IS DISTINCT FROM c.low)         AS diff_low,
  (s.close       IS DISTINCT FROM c.close)       AS diff_close,
  (s.volume      IS DISTINCT FROM c.volume)      AS diff_volume,
  (s.market_cap  IS DISTINCT FROM c.market_cap)  AS diff_market_cap
FROM snap s
JOIN cur  c
  ON c.id = s.id AND c.tf_norm = s.tf_norm AND c.bar_seq = s.bar_seq
WHERE
  s.tf_days     IS DISTINCT FROM c.tf_days OR
  s.time_open   IS DISTINCT FROM c.time_open OR
  s.time_close  IS DISTINCT FROM c.time_close OR
  s.time_high   IS DISTINCT FROM c.time_high OR
  s.time_low    IS DISTINCT FROM c.time_low OR
  s.open        IS DISTINCT FROM c.open OR
  s.high        IS DISTINCT FROM c.high OR
  s.low         IS DISTINCT FROM c.low OR
  s.close       IS DISTINCT FROM c.close OR
  s.volume      IS DISTINCT FROM c.volume OR
  s.market_cap  IS DISTINCT FROM c.market_cap
LIMIT 50;

-- -----------------------------------------------------------------------------
-- G) FIRST/LAST bar check for one example (id=1, tf_norm='2D')
-- -----------------------------------------------------------------------------
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
),
bounds AS (
  SELECT
    MIN(bar_seq) AS first_seq,
    MAX(bar_seq) AS last_seq
  FROM cur
  WHERE id = 1 AND tf_norm = '2D'
),
pairs AS (
  SELECT 'FIRST' AS which, c.*, s.tf_days  AS s_tf_days,
                         s.time_open AS s_time_open, s.time_close AS s_time_close,
                         s.time_high AS s_time_high, s.time_low   AS s_time_low,
                         s.open      AS s_open,      s.high       AS s_high,
                         s.low       AS s_low,       s.close      AS s_close,
                         s.volume    AS s_volume,    s.market_cap AS s_market_cap
  FROM bounds b
  JOIN cur  c ON c.id=1 AND c.tf_norm='2D' AND c.bar_seq=b.first_seq
  LEFT JOIN snap s ON s.id=1 AND s.tf_norm='2D' AND s.bar_seq=b.first_seq

  UNION ALL

  SELECT 'LAST' AS which, c.*, s.tf_days  AS s_tf_days,
                        s.time_open AS s_time_open, s.time_close AS s_time_close,
                        s.time_high AS s_time_high, s.time_low   AS s_time_low,
                        s.open      AS s_open,      s.high       AS s_high,
                        s.low       AS s_low,       s.close      AS s_close,
                        s.volume    AS s_volume,    s.market_cap AS s_market_cap
  FROM bounds b
  JOIN cur  c ON c.id=1 AND c.tf_norm='2D' AND c.bar_seq=b.last_seq
  LEFT JOIN snap s ON s.id=1 AND s.tf_norm='2D' AND s.bar_seq=b.last_seq
)
SELECT
  which,
  bar_seq,
  (s_tf_days IS NOT NULL) AS exists_in_snapshot,

  ROW(tf_days, time_open, time_close, time_high, time_low, open, high, low, close, volume, market_cap)
  IS NOT DISTINCT FROM
  ROW(s_tf_days, s_time_open, s_time_close, s_time_high, s_time_low, s_open, s_high, s_low, s_close, s_volume, s_market_cap)
  AS matches,

  (tf_days    IS DISTINCT FROM s_tf_days)    AS diff_tf_days,
  (time_open  IS DISTINCT FROM s_time_open)  AS diff_time_open,
  (time_close IS DISTINCT FROM s_time_close) AS diff_time_close,
  (time_high  IS DISTINCT FROM s_time_high)  AS diff_time_high,
  (time_low   IS DISTINCT FROM s_time_low)   AS diff_time_low,
  (open       IS DISTINCT FROM s_open)       AS diff_open,
  (high       IS DISTINCT FROM s_high)       AS diff_high,
  (low        IS DISTINCT FROM s_low)        AS diff_low,
  (close      IS DISTINCT FROM s_close)      AS diff_close,
  (volume     IS DISTINCT FROM s_volume)     AS diff_volume,
  (market_cap IS DISTINCT FROM s_market_cap) AS diff_market_cap
FROM pairs
ORDER BY which;
