WITH bars_us AS (
  SELECT DISTINCT regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ANCHOR)$', '') AS tf
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us
),
bars_iso AS (
  SELECT DISTINCT regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ANCHOR)$', '') AS tf
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
),
ema AS (
  SELECT DISTINCT tf::text AS tf
  FROM public.cmc_ema_multi_tf_cal_anchor
)
SELECT
  e.tf AS ema_tf_missing_in_anchor_bars,
  EXISTS (SELECT 1 FROM bars_us  b WHERE b.tf = e.tf) AS in_bars_anchor_us,
  EXISTS (SELECT 1 FROM bars_iso b WHERE b.tf = e.tf) AS in_bars_anchor_iso
FROM ema e
WHERE
  NOT EXISTS (SELECT 1 FROM bars_us  b WHERE b.tf = e.tf)
   OR
  NOT EXISTS (SELECT 1 FROM bars_iso b WHERE b.tf = e.tf)
ORDER BY e.tf;

WITH bars_us AS (
  SELECT DISTINCT regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ANCHOR)$', '') AS tf
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us
),
bars_iso AS (
  SELECT DISTINCT regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ISO_ANCHOR)$', '') AS tf
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
),
ema_calendar_only AS (
  SELECT DISTINCT e.tf::text AS tf
  FROM public.cmc_ema_multi_tf_cal_anchor e
  JOIN public.dim_timeframe d
    ON d.tf = e.tf
  WHERE d.alignment_type = 'calendar'
)
SELECT
  e.tf AS ema_calendar_tf_missing_in_anchor_bars,
  EXISTS (SELECT 1 FROM bars_us  b WHERE b.tf = e.tf) AS in_bars_anchor_us,
  EXISTS (SELECT 1 FROM bars_iso b WHERE b.tf = e.tf) AS in_bars_anchor_iso
FROM ema_calendar_only e
WHERE
  NOT EXISTS (SELECT 1 FROM bars_us  b WHERE b.tf = e.tf)
   OR
  NOT EXISTS (SELECT 1 FROM bars_iso b WHERE b.tf = e.tf)
ORDER BY e.tf;

WITH bars_all AS (
  SELECT DISTINCT regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ANCHOR)$', '') AS tf
  FROM public.cmc_price_bars_multi_tf_cal_anchor_us
  UNION
  SELECT DISTINCT regexp_replace(tf::text, '(_US_ANCHOR|_ISO_ANCHOR)$', '') AS tf
  FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
),
ema AS (
  SELECT DISTINCT tf::text AS tf
  FROM public.cmc_ema_multi_tf_cal_anchor
)
SELECT b.tf AS anchor_bar_tf_missing_in_anchor_ema
FROM bars_all b
LEFT JOIN ema e ON e.tf = b.tf
WHERE e.tf IS NULL
ORDER BY b.tf;
