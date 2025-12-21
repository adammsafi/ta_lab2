-- =============================================================================
-- File: sql/qa/20251213__qa_tf_presence_across_pipeline.sql
-- Purpose:
--   Verify timeframe (“tf”) coverage across the pipeline tables.
--
-- Core idea:
--   You have three “naming groups” that require normalization:
--
--   G1: No suffix normalization needed
--       - cmc_price_bars_multi_tf
--       - cmc_ema_multi_tf
--       - cmc_ema_multi_tf_v2
--
--   G2: Strip _CAL / _ISO suffix from bars-cal tables to compare to ema tf labels
--       - cmc_price_bars_multi_tf_cal_us  (tf like 1W_CAL)
--       - cmc_price_bars_multi_tf_cal_iso (tf like 1W_ISO)
--       - cmc_ema_multi_tf_cal            (tf typically like 1W, 1M, etc.)
--
--   G3: Strip _US_ANCHOR / _ISO_ANCHOR suffix from anchor bars
--       - cmc_price_bars_multi_tf_cal_anchor_us
--       - cmc_price_bars_multi_tf_cal_anchor_iso
--       - cmc_ema_multi_tf_cal_anchor
-- =============================================================================

WITH src AS (
    -- ================= GROUP 1 (no normalization) =================
    SELECT 'G1' AS grp, 'bars_multi_tf' AS src, tf::text AS tf_raw, tf::text AS tf_norm
    FROM public.cmc_price_bars_multi_tf
    GROUP BY tf
    UNION ALL
    SELECT 'G1', 'ema_multi_tf', tf::text, tf::text
    FROM public.cmc_ema_multi_tf
    GROUP BY tf
    UNION ALL
    SELECT 'G1', 'ema_multi_tf_v2', tf::text, tf::text
    FROM public.cmc_ema_multi_tf_v2
    GROUP BY tf

    -- ================= GROUP 2 (strip _CAL / _ISO) =================
    UNION ALL
    SELECT 'G2', 'bars_cal_us', tf::text, regexp_replace(tf::text, '(_CAL|_ISO)$', '')
    FROM public.cmc_price_bars_multi_tf_cal_us
    GROUP BY tf
    UNION ALL
    SELECT 'G2', 'bars_cal_iso', tf::text, regexp_replace(tf::text, '(_CAL|_ISO)$', '')
    FROM public.cmc_price_bars_multi_tf_cal_iso
    GROUP BY tf
    UNION ALL
    SELECT 'G2', 'ema_multi_tf_cal', tf::text, tf::text
    FROM public.cmc_ema_multi_tf_cal
    GROUP BY tf

    -- ================= GROUP 3 (strip _US_ANCHOR / _ISO_ANCHOR) =================
    UNION ALL
    SELECT 'G3', 'bars_cal_anchor_us', tf::text, regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ANCHOR)$', '')
    FROM public.cmc_price_bars_multi_tf_cal_anchor_us
    GROUP BY tf
    UNION ALL
    SELECT 'G3', 'bars_cal_anchor_iso', tf::text, regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ANCHOR)$', '')
    FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
    GROUP BY tf
    UNION ALL
    SELECT 'G3', 'ema_multi_tf_cal_anchor', tf::text, tf::text
    FROM public.cmc_ema_multi_tf_cal_anchor
    GROUP BY tf
),
all_tfs AS (
    SELECT DISTINCT grp, tf_norm
    FROM src
),
presence AS (
    SELECT
        a.grp,
        a.tf_norm,

        BOOL_OR(s.src = 'bars_multi_tf')           AS in_bars_multi_tf,
        BOOL_OR(s.src = 'ema_multi_tf')            AS in_ema_multi_tf,
        BOOL_OR(s.src = 'ema_multi_tf_v2')         AS in_ema_multi_tf_v2,

        BOOL_OR(s.src = 'bars_cal_us')             AS in_bars_cal_us,
        BOOL_OR(s.src = 'bars_cal_iso')            AS in_bars_cal_iso,
        BOOL_OR(s.src = 'ema_multi_tf_cal')        AS in_ema_multi_tf_cal,

        BOOL_OR(s.src = 'bars_cal_anchor_us')      AS in_bars_cal_anchor_us,
        BOOL_OR(s.src = 'bars_cal_anchor_iso')     AS in_bars_cal_anchor_iso,
        BOOL_OR(s.src = 'ema_multi_tf_cal_anchor') AS in_ema_multi_tf_cal_anchor

    FROM all_tfs a
    LEFT JOIN src s
      ON s.grp = a.grp
     AND s.tf_norm = a.tf_norm
    GROUP BY a.grp, a.tf_norm
)
SELECT
    grp,
    tf_norm AS tf,

    -- Group 1
    in_bars_multi_tf,
    in_ema_multi_tf,
    in_ema_multi_tf_v2,

    -- Group 2
    in_bars_cal_us,
    in_bars_cal_iso,
    in_ema_multi_tf_cal,

    -- Group 3
    in_bars_cal_anchor_us,
    in_bars_cal_anchor_iso,
    in_ema_multi_tf_cal_anchor
FROM presence
WHERE
    (grp = 'G1' AND NOT (in_bars_multi_tf AND in_ema_multi_tf AND in_ema_multi_tf_v2))
 OR (grp = 'G2' AND NOT (in_bars_cal_us AND in_bars_cal_iso AND in_ema_multi_tf_cal))
 OR (grp = 'G3' AND NOT (in_bars_cal_anchor_us AND in_bars_cal_anchor_iso AND in_ema_multi_tf_cal_anchor))
ORDER BY grp, tf;

-- -----------------------------------------------------------------------------
-- tf_days-based mismatch view for Group 1 (bars vs ema1 vs ema2) via dim_timeframe
-- -----------------------------------------------------------------------------
WITH g1_tfs AS (
  SELECT 'bars' AS src, tf::text AS tf
  FROM public.cmc_price_bars_multi_tf
  GROUP BY tf
  UNION ALL
  SELECT 'ema1' AS src, tf::text AS tf
  FROM public.cmc_ema_multi_tf
  GROUP BY tf
  UNION ALL
  SELECT 'ema2' AS src, tf::text AS tf
  FROM public.cmc_ema_multi_tf_v2
  GROUP BY tf
),
g1_with_days AS (
  SELECT
    t.src,
    t.tf,
    d.tf_days_min,
    d.tf_days_max
  FROM g1_tfs t
  LEFT JOIN public.dim_timeframe d
    ON d.tf = t.tf
),
canon AS (
  SELECT
    src,
    tf,
    CASE
      WHEN tf_days_min IS NOT NULL AND tf_days_max IS NOT NULL AND tf_days_min = tf_days_max
        THEN tf_days_min
      ELSE NULL
    END AS tf_days_fixed
  FROM g1_with_days
)
SELECT
  tf_days_fixed,
  ARRAY_AGG(tf ORDER BY tf) FILTER (WHERE src='bars') AS bars_tfs,
  ARRAY_AGG(tf ORDER BY tf) FILTER (WHERE src='ema1') AS ema1_tfs,
  ARRAY_AGG(tf ORDER BY tf) FILTER (WHERE src='ema2') AS ema2_tfs,
  BOOL_OR(src='bars') AS in_bars,
  BOOL_OR(src='ema1') AS in_ema1,
  BOOL_OR(src='ema2') AS in_ema2
FROM canon
GROUP BY tf_days_fixed
HAVING
  NOT (BOOL_OR(src='bars') AND BOOL_OR(src='ema1') AND BOOL_OR(src='ema2'))
ORDER BY tf_days_fixed NULLS LAST;

-- -----------------------------------------------------------------------------
-- Which EMA tf_days exist that do NOT exist in bars (duration-level gap)
-- -----------------------------------------------------------------------------
WITH tfs AS (
  SELECT 'bars' AS src, tf::text AS tf
  FROM public.cmc_price_bars_multi_tf
  GROUP BY tf
  UNION ALL
  SELECT 'ema1' AS src, tf::text AS tf
  FROM public.cmc_ema_multi_tf
  GROUP BY tf
  UNION ALL
  SELECT 'ema2' AS src, tf::text AS tf
  FROM public.cmc_ema_multi_tf_v2
  GROUP BY tf
),
days AS (
  SELECT
    tfs.src,
    tfs.tf,
    CASE
      WHEN d.tf_days_min = d.tf_days_max THEN d.tf_days_min
      ELSE NULL
    END AS tf_days
  FROM tfs
  JOIN public.dim_timeframe d
    ON d.tf = tfs.tf
),
bars_days AS (
  SELECT DISTINCT tf_days
  FROM days
  WHERE src = 'bars' AND tf_days IS NOT NULL
),
ema_days AS (
  SELECT DISTINCT tf_days
  FROM days
  WHERE src IN ('ema1','ema2') AND tf_days IS NOT NULL
)
SELECT e.tf_days AS ema_tf_days_missing_in_bars
FROM ema_days e
LEFT JOIN bars_days b
  ON b.tf_days = e.tf_days
WHERE b.tf_days IS NULL
ORDER BY e.tf_days;

-- -----------------------------------------------------------------------------
-- Example: list EMA TF labels that map to tf_days=56 (helps justify adding 56D)
-- -----------------------------------------------------------------------------
WITH tfs AS (
  SELECT 'ema1' AS src, tf::text AS tf
  FROM public.cmc_ema_multi_tf
  GROUP BY tf
  UNION ALL
  SELECT 'ema2' AS src, tf::text AS tf
  FROM public.cmc_ema_multi_tf_v2
  GROUP BY tf
),
days AS (
  SELECT
    tfs.src,
    tfs.tf,
    CASE WHEN d.tf_days_min = d.tf_days_max THEN d.tf_days_min END AS tf_days
  FROM tfs
  JOIN public.dim_timeframe d ON d.tf = tfs.tf
)
SELECT tf_days, ARRAY_AGG(DISTINCT tf ORDER BY tf) AS ema_tfs
FROM days
WHERE tf_days = 56
GROUP BY tf_days;

-- -----------------------------------------------------------------------------
-- ema_alpha_lookup introspection: what tf labels exist for each tf_days?
-- -----------------------------------------------------------------------------
SELECT DISTINCT
  tf,
  tf_days
FROM public.ema_alpha_lookup
ORDER BY tf_days, tf;

WITH tf_list AS (
  SELECT
    tf_days,
    MIN(tf) AS tf   -- deterministic label choice; adjust rule if you prefer
  FROM public.ema_alpha_lookup
  GROUP BY tf_days
)
SELECT *
FROM tf_list
ORDER BY tf_days;

WITH used_tfs AS (
  SELECT DISTINCT tf FROM public.cmc_ema_multi_tf
  UNION
  SELECT DISTINCT tf FROM public.cmc_ema_multi_tf_v2
),
tf_list AS (
  SELECT
    e.tf_days,
    MIN(e.tf) AS tf
  FROM public.ema_alpha_lookup e
  JOIN used_tfs u USING (tf)
  GROUP BY e.tf_days
)
SELECT *
FROM tf_list
ORDER BY tf_days;
