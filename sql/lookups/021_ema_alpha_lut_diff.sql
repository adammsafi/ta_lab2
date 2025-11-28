-- 021_ema_alpha_lut_diff.sql
--
-- Compare ema_alpha_lut_old (original table) vs ema_alpha_lut (legacy view).
-- Use this after running:
--   018_migrate_ema_alpha_lut_to_view.sql
--   019_ema_alpha_lut_legacy_view.sql

-- 1. View and table existence
SELECT 'objects' AS section, table_type, table_name
FROM information_schema.tables
WHERE table_name LIKE 'ema_alpha_lut%'
ORDER BY table_type, table_name;

-- 2. Quick data sample
SELECT 'sample' AS section, *
FROM ema_alpha_lut
ORDER BY tf, period
LIMIT 10;

-- 3. Row counts
SELECT
  'row_counts' AS section,
  (SELECT COUNT(*) FROM ema_alpha_lut_old) AS old_rows,
  (SELECT COUNT(*) FROM ema_alpha_lut)     AS view_rows;

-- 4. Keys present in old but missing in view (should be 0)
SELECT
  'missing_in_view' AS section,
  o.*
FROM ema_alpha_lut_old o
LEFT JOIN ema_alpha_lut v
  ON v.tf = o.tf AND v.period = o.period
WHERE v.tf IS NULL;

-- 5. Numeric differences beyond tolerance (should be 0 rows ideally)
SELECT
  'diff_rows' AS section,
  o.tf,
  o.period,
  o.tf_days        AS old_tf_days,
  v.tf_days        AS new_tf_days,
  o.effective_days AS old_effective_days,
  v.effective_days AS new_effective_days,
  o.alpha_bar      AS old_alpha_bar,
  v.alpha_bar      AS new_alpha_bar,
  o.alpha_daily_eq AS old_alpha_daily_eq,
  v.alpha_daily_eq AS new_alpha_daily_eq
FROM ema_alpha_lut_old o
JOIN ema_alpha_lut v
  ON v.tf = o.tf AND v.period = o.period
WHERE
    o.tf_days        <> v.tf_days
 OR o.effective_days <> v.effective_days
 OR ABS(o.alpha_bar      - v.alpha_bar)      > 1e-12
 OR ABS(o.alpha_daily_eq - v.alpha_daily_eq) > 1e-12
LIMIT 25;
