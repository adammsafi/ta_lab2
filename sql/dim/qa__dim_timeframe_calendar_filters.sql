-- =============================================================================
-- File: sql/dim/qa__dim_timeframe_calendar_filters.sql
-- Purpose:
--   - Inspect / validate dim_timeframe content relevant to CAL/ISO schemes
--   - Provide the “56D” insertion + canonical toggle (derived from 7D template)
--
-- Notes:
--   - These are read-mostly queries plus one controlled insert + update.
--   - Keep “dim” changes here so they don’t get lost inside QA diffs.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Baseline: view the full dim_timeframe table (careful: may be wide/long).
-- -----------------------------------------------------------------------------
SELECT *
FROM public.dim_timeframe;

-- -----------------------------------------------------------------------------
-- Calendar-aligned, no-partial, weekly/monthly/yearly, with explicit scheme rules:
--   - Weeks must be ISO
--   - Months/Years must be CAL
-- -----------------------------------------------------------------------------
SELECT
  tf,
  base_unit,
  tf_qty,
  calendar_scheme,
  allow_partial_start,
  allow_partial_end,
  tf_days_min,
  tf_days_max,
  sort_order
FROM public.dim_timeframe
WHERE alignment_type = 'calendar'
  AND allow_partial_start = FALSE
  AND allow_partial_end   = FALSE
  AND base_unit IN ('W','M','Y')
  AND (
        (base_unit = 'W' AND calendar_scheme = 'ISO')
     OR (base_unit IN ('M','Y') AND calendar_scheme = 'CAL')
  )
ORDER BY sort_order, tf;

-- -----------------------------------------------------------------------------
-- Calendar-aligned week-only: “*_CAL” label pattern, sorted
-- -----------------------------------------------------------------------------
SELECT tf, base_unit, tf_qty, calendar_scheme, calendar_anchor, sort_order
FROM public.dim_timeframe
WHERE alignment_type='calendar'
  AND allow_partial_start=FALSE
  AND allow_partial_end=FALSE
  AND base_unit='W'
  AND tf LIKE '%_CAL'
ORDER BY sort_order, tf;

-- -----------------------------------------------------------------------------
-- Alternative filter variant:
--   Pulls 1W_CAL..10W_CAL by tf label, plus CAL months/years by calendar_scheme.
-- -----------------------------------------------------------------------------
SELECT
  tf,
  base_unit,
  tf_qty,
  sort_order
FROM public.dim_timeframe
WHERE alignment_type = 'calendar'
  AND allow_partial_start = FALSE
  AND allow_partial_end   = FALSE
  AND base_unit IN ('W','M','Y')
  AND (
        (base_unit = 'W' AND tf LIKE '%_CAL')              -- e.g. 1W_CAL..10W_CAL
     OR (base_unit IN ('M','Y') AND calendar_scheme = 'CAL')
  )
ORDER BY sort_order, tf;

-- -----------------------------------------------------------------------------
-- Quick lookup: days bounds for a few “tf-day vs week” comparisons.
-- -----------------------------------------------------------------------------
SELECT tf, tf_days_min, tf_days_max
FROM public.dim_timeframe
WHERE tf IN ('7D','1W','14D','2W','21D','3W','28D','4W','8W')
ORDER BY tf;

-- -----------------------------------------------------------------------------
-- Insert: add pure 56D timeframe (if missing), cloning most metadata from 7D.
-- Why:
--   - You observed EMA tables using tf_days=56 via ema_alpha_lookup
--   - This makes the mapping explicit and canonical if desired
-- -----------------------------------------------------------------------------
INSERT INTO public.dim_timeframe (
    tf,
    label,
    base_unit,
    tf_qty,
    tf_days_nominal,
    alignment_type,
    calendar_anchor,
    roll_policy,
    has_roll_flag,
    is_intraday,
    sort_order,
    description,
    is_canonical,
    calendar_scheme,
    allow_partial_start,
    allow_partial_end,
    tf_days_min,
    tf_days_max
)
SELECT
    '56D'::text                                    AS tf,
    '56 days'::text                                AS label,
    base_unit,
    56                                             AS tf_qty,
    56                                             AS tf_days_nominal,
    alignment_type,
    calendar_anchor,
    roll_policy,
    has_roll_flag,
    is_intraday,
    COALESCE(sort_order, 0) + 1000                 AS sort_order,
    'Pure 56-day tf_day horizon'::text             AS description,
    is_canonical,
    calendar_scheme,
    allow_partial_start,
    allow_partial_end,
    56                                             AS tf_days_min,
    56                                             AS tf_days_max
FROM public.dim_timeframe
WHERE tf = '7D'
  AND NOT EXISTS (SELECT 1 FROM public.dim_timeframe WHERE tf = '56D');

-- Optionally mark it canonical (do this only if you truly want 56D treated as first-class).
UPDATE public.dim_timeframe
SET is_canonical = true
WHERE tf = '56D';

-- Debug / confirm:
SELECT *
FROM public.dim_timeframe
WHERE tf = '56D';
