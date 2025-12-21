-- =============================================================================
-- File: sql/qa/20251213__qa_cal_tables_vs_snapshots.sql
-- Purpose:
--   Compare “current” tables vs their 2025-12-13 snapshots.
--
-- Strategy:
--   (A) Row counts + distinct key integrity
--   (B) TF coverage diffs (what TFs are missing/present)
--   (C) Per-(id,tf) row-count diffs (cheap mismatch detector)
--   (D) Full row equality check ignoring ingested_at (expensive but definitive)
--   (E) Spot-check FIRST/LAST bar for a chosen (id, tf) ignoring ingested_at
--
-- Notes:
--   - For tables without snapshot PKs, these still work but run slower.
--   - Full row equality uses JSONB minus ingested_at to ignore ingestion timestamp.
-- =============================================================================

-- =============================================================================
-- SECTION 1: cmc_price_bars_multi_tf_cal_us vs snapshot
-- =============================================================================

-- 0) Row counts
SELECT 'current'  AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_us
UNION ALL
SELECT 'snapshot' AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213;

-- Distinct keys: should match COUNT(*) if (id, tf, bar_seq) is unique
SELECT 'current' AS which,
       COUNT(*) AS n_rows,
       COUNT(DISTINCT (id, tf, bar_seq)) AS n_distinct_keys
FROM public.cmc_price_bars_multi_tf_cal_us
UNION ALL
SELECT 'snapshot' AS which,
       COUNT(*) AS n_rows,
       COUNT(DISTINCT (id, tf, bar_seq)) AS n_distinct_keys
FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213;

-- ID counts
SELECT 'current' AS which, COUNT(DISTINCT id) AS n_ids
FROM public.cmc_price_bars_multi_tf_cal_us
UNION ALL
SELECT 'snapshot' AS which, COUNT(DISTINCT id) AS n_ids
FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213;

-- TF counts
SELECT 'current' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_us
UNION ALL
SELECT 'snapshot' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213;

-- TFs present in snapshot but missing in current
SELECT s.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213) s
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_us) c
  ON c.tf = s.tf
WHERE c.tf IS NULL
ORDER BY s.tf;

-- TFs present in current but missing in snapshot
SELECT c.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_us) c
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213) s
  ON s.tf = c.tf
WHERE s.tf IS NULL
ORDER BY c.tf;

-- Per-(id,tf) row count mismatches (fast “diff detector”)
WITH cur AS (
  SELECT id, tf, COUNT(*) AS n
  FROM public.cmc_price_bars_multi_tf_cal_us
  GROUP BY 1,2
),
snap AS (
  SELECT id, tf, COUNT(*) AS n
  FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213
  GROUP BY 1,2
)
SELECT COALESCE(cur.id, snap.id) AS id,
       COALESCE(cur.tf, snap.tf) AS tf,
       cur.n  AS n_current,
       snap.n AS n_snapshot
FROM cur
FULL OUTER JOIN snap
  ON cur.id = snap.id AND cur.tf = snap.tf
WHERE cur.n IS DISTINCT FROM snap.n
ORDER BY tf, id;

-- Full row-by-row equality check (ignoring ingested_at)
WITH cur AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_us t
),
snap AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213 t
)
SELECT 'only_in_current' AS which, COUNT(*) AS n
FROM (SELECT j FROM cur EXCEPT ALL SELECT j FROM snap) x
UNION ALL
SELECT 'only_in_snapshot' AS which, COUNT(*) AS n
FROM (SELECT j FROM snap EXCEPT ALL SELECT j FROM cur) y;

-- First/Last bar compare for one (id, tf), ignoring ingested_at
WITH cur_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_us t
  WHERE id = 1 AND tf = '1W_CAL'
  ORDER BY bar_seq ASC
  LIMIT 1
),
snap_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_CAL'
  ORDER BY bar_seq ASC
  LIMIT 1
),
cur_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_us t
  WHERE id = 1 AND tf = '1W_CAL'
  ORDER BY bar_seq DESC
  LIMIT 1
),
snap_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_us_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_CAL'
  ORDER BY bar_seq DESC
  LIMIT 1
)
SELECT 'FIRST' AS which_bar, (cur_first.j = snap_first.j) AS matches
FROM cur_first, snap_first
UNION ALL
SELECT 'LAST'  AS which_bar, (cur_last.j  = snap_last.j)  AS matches
FROM cur_last, snap_last;

-- =============================================================================
-- SECTION 2: cmc_price_bars_multi_tf_cal_iso vs snapshot
-- =============================================================================

-- 0) Row counts
SELECT 'current'  AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_iso
UNION ALL
SELECT 'snapshot' AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_iso_snapshot_20251213;

-- 1) TF counts
SELECT 'current' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_iso
UNION ALL
SELECT 'snapshot' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_iso_snapshot_20251213;

-- 2) TFs present in snapshot but missing in current
SELECT s.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_iso_snapshot_20251213) s
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_iso) c
  ON c.tf = s.tf
WHERE c.tf IS NULL
ORDER BY s.tf;

-- 3) TFs present in current but missing in snapshot
SELECT c.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_iso) c
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_iso_snapshot_20251213) s
  ON s.tf = c.tf
WHERE s.tf IS NULL
ORDER BY c.tf;

-- 4) Full row-by-row equality check (ignoring ingested_at)
WITH cur AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_iso t
),
snap AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_iso_snapshot_20251213 t
)
SELECT 'only_in_current' AS which, COUNT(*) AS n
FROM (SELECT j FROM cur EXCEPT ALL SELECT j FROM snap) x
UNION ALL
SELECT 'only_in_snapshot' AS which, COUNT(*) AS n
FROM (SELECT j FROM snap EXCEPT ALL SELECT j FROM cur) y;

-- 5) First/Last bar compare for one (id, tf), ignoring ingested_at
WITH cur_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_iso t
  WHERE id = 1 AND tf = '1W_ISO'
  ORDER BY bar_seq ASC
  LIMIT 1
),
snap_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_iso_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_ISO'
  ORDER BY bar_seq ASC
  LIMIT 1
),
cur_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_iso t
  WHERE id = 1 AND tf = '1W_ISO'
  ORDER BY bar_seq DESC
  LIMIT 1
),
snap_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_iso_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_ISO'
  ORDER BY bar_seq DESC
  LIMIT 1
)
SELECT 'FIRST' AS which_bar, (cur_first.j = snap_first.j) AS matches
FROM cur_first, snap_first
UNION ALL
SELECT 'LAST'  AS which_bar, (cur_last.j  = snap_last.j)  AS matches
FROM cur_last, snap_last;

-- =============================================================================
-- SECTION 3: cmc_price_bars_multi_tf_cal_anchor_us vs snapshot
-- =============================================================================

-- 0) Row counts
SELECT 'current'  AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_anchor_us
UNION ALL
SELECT 'snapshot' AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20251213;

-- 1) TF counts
SELECT 'current' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_anchor_us
UNION ALL
SELECT 'snapshot' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20251213;

-- 2) TFs present in snapshot but missing in current
SELECT s.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20251213) s
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_us) c
  ON c.tf = s.tf
WHERE c.tf IS NULL
ORDER BY s.tf;

-- 3) TFs present in current but missing in snapshot
SELECT c.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_us) c
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20251213) s
  ON s.tf = c.tf
WHERE s.tf IS NULL
ORDER BY c.tf;

-- 4) Full row-by-row equality check (ignoring ingested_at)
WITH cur AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us t
),
snap AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20251213 t
)
SELECT 'only_in_current' AS which, COUNT(*) AS n
FROM (SELECT j FROM cur EXCEPT ALL SELECT j FROM snap) x
UNION ALL
SELECT 'only_in_snapshot' AS which, COUNT(*) AS n
FROM (SELECT j FROM snap EXCEPT ALL SELECT j FROM cur) y;

-- 5) First/Last bar compare for one (id, tf), ignoring ingested_at
WITH cur_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us t
  WHERE id = 1 AND tf = '1W_US_ANCHOR'
  ORDER BY bar_seq ASC
  LIMIT 1
),
snap_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_US_ANCHOR'
  ORDER BY bar_seq ASC
  LIMIT 1
),
cur_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us t
  WHERE id = 1 AND tf = '1W_US_ANCHOR'
  ORDER BY bar_seq DESC
  LIMIT 1
),
snap_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_US_ANCHOR'
  ORDER BY bar_seq DESC
  LIMIT 1
)
SELECT 'FIRST' AS which_bar, (cur_first.j = snap_first.j) AS matches
FROM cur_first, snap_first
UNION ALL
SELECT 'LAST'  AS which_bar, (cur_last.j  = snap_last.j)  AS matches
FROM cur_last, snap_last;

-- Quick smoke: inspect one row (helps confirm table is populated / shape looks right)
SELECT *
FROM public.cmc_price_bars_multi_tf_cal_anchor_us
LIMIT 1;

-- =============================================================================
-- SECTION 4: cmc_price_bars_multi_tf_cal_anchor_iso vs snapshot
-- =============================================================================

-- 0) Row counts
SELECT 'current'  AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
UNION ALL
SELECT 'snapshot' AS which, COUNT(*) AS n_rows FROM public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213;

-- 1) TF counts
SELECT 'current' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
UNION ALL
SELECT 'snapshot' AS which, COUNT(DISTINCT tf) AS n_tfs
FROM public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213;

-- 2) TFs present in snapshot but missing in current
SELECT s.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213) s
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_iso) c
  ON c.tf = s.tf
WHERE c.tf IS NULL
ORDER BY s.tf;

-- 3) TFs present in current but missing in snapshot
SELECT c.tf
FROM (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_iso) c
LEFT JOIN (SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213) s
  ON s.tf = c.tf
WHERE s.tf IS NULL
ORDER BY c.tf;

-- 4) Full row-by-row equality check (ignoring ingested_at)
WITH cur AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso t
),
snap AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213 t
)
SELECT 'only_in_current' AS which, COUNT(*) AS n
FROM (SELECT j FROM cur EXCEPT ALL SELECT j FROM snap) x
UNION ALL
SELECT 'only_in_snapshot' AS which, COUNT(*) AS n
FROM (SELECT j FROM snap EXCEPT ALL SELECT j FROM cur) y;

-- 5) First/Last bar compare for one (id, tf), ignoring ingested_at
WITH cur_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso t
  WHERE id = 1 AND tf = '1W_ISO_ANCHOR'
  ORDER BY bar_seq ASC
  LIMIT 1
),
snap_first AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_ISO_ANCHOR'
  ORDER BY bar_seq ASC
  LIMIT 1
),
cur_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso t
  WHERE id = 1 AND tf = '1W_ISO_ANCHOR'
  ORDER BY bar_seq DESC
  LIMIT 1
),
snap_last AS (
  SELECT to_jsonb(t) - 'ingested_at' AS j
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213 t
  WHERE id = 1 AND tf = '1W_ISO_ANCHOR'
  ORDER BY bar_seq DESC
  LIMIT 1
)
SELECT 'FIRST' AS which_bar, (cur_first.j = snap_first.j) AS matches
FROM cur_first, snap_first
UNION ALL
SELECT 'LAST'  AS which_bar, (cur_last.j  = snap_last.j)  AS matches
FROM cur_last, snap_last;
