/* ============================================================================
0016_dim_timeframe_partial_bounds_and_calendar_families.sql

Goal
----
Make dim_timeframe capable of supporting:
  - Variable realized tf_days for calendar windows (e.g., 1M_CAL = 28..31)
  - Partial-period behavior for anchored calendars (min can be 1 day at dataset edges)
  - ISO-week calendar TF labels used by cmc_price_bars_multi_tf_cal_iso
  - US + ISO anchored calendar TF labels used by *_cal_anchor_* tables

Design Notes
------------
- tf_days_nominal remains the "semantic" / representative size for a TF.
- tf_days_min / tf_days_max become QA bounds for realized bars.tf_days.
- allow_partial_start/end flags document "partial bars allowed at dataset edges".
- calendar_scheme documents "US vs ISO vs generic CAL" where useful.

Re-runnable
-----------
- Uses IF NOT EXISTS for schema changes.
- Uses ON CONFLICT (tf) DO UPDATE for seed data.
- Backfills are idempotent (COALESCE only).
============================================================================ */

BEGIN;

-- ============================================================================
-- 1) Schema update: add metadata + QA bound columns to dim_timeframe
-- ============================================================================

/*
We add:
  - calendar_scheme: text label such as 'US', 'ISO', or 'CAL' (optional taxonomy)
  - allow_partial_start / allow_partial_end: documents partial bar allowance
  - tf_days_min / tf_days_max: realized bar day-count bounds for QA joins
*/
ALTER TABLE public.dim_timeframe
  ADD COLUMN IF NOT EXISTS calendar_scheme text,
  ADD COLUMN IF NOT EXISTS allow_partial_start boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS allow_partial_end   boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS tf_days_min integer,
  ADD COLUMN IF NOT EXISTS tf_days_max integer;

-- Add a defensive constraint: if both bounds are present, min must be <= max.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'dim_timeframe_tf_days_min_le_max'
  ) THEN
    ALTER TABLE public.dim_timeframe
      ADD CONSTRAINT dim_timeframe_tf_days_min_le_max
      CHECK (
        tf_days_min IS NULL
        OR tf_days_max IS NULL
        OR tf_days_min <= tf_days_max
      );
  END IF;
END$$;

-- ============================================================================
-- 1B) Ensure calendar_anchor check constraint supports WEEK_END + ISO-WEEK + EOM/EOQ/EOY
-- ============================================================================

/*
Your current constraint is:
  CHECK (calendar_anchor IS NULL OR calendar_anchor IN ('EOM','EOQ','EOY','WEEK_END','ISO-WEEK'))

If different environments exist (dev vs prod), this block makes it consistent.
If you never want the migration to touch constraints, you can remove this block.
*/
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.dim_timeframe'::regclass
      AND conname = 'dim_timeframe_calendar_anchor_check'
  ) THEN
    -- Drop and recreate to guarantee allowed set matches what the code expects.
    ALTER TABLE public.dim_timeframe
      DROP CONSTRAINT dim_timeframe_calendar_anchor_check;
  END IF;

  ALTER TABLE public.dim_timeframe
    ADD CONSTRAINT dim_timeframe_calendar_anchor_check
    CHECK (
      calendar_anchor IS NULL
      OR calendar_anchor = ANY (
        ARRAY[
          'EOM'::text,
          'EOQ'::text,
          'EOY'::text,
          'WEEK_END'::text,
          'ISO-WEEK'::text
        ]
      )
    );
END$$;

-- ============================================================================
-- 1C) Backfill / initialize tf_days_min/max for existing rows
-- ============================================================================

/*
Default behavior:
  If a row has a nominal day count but no explicit min/max yet,
  set min=max=nominal. This makes dt immediately usable for QA joins.

This is intentionally conservative.
We then override a handful of CAL rows where real life varies.
*/
UPDATE public.dim_timeframe
SET
  tf_days_min = COALESCE(tf_days_min, tf_days_nominal),
  tf_days_max = COALESCE(tf_days_max, tf_days_nominal)
WHERE tf_days_nominal IS NOT NULL;

-- Calendar month/year windows vary; set sensible ranges for CAL family.
UPDATE public.dim_timeframe
SET
  tf_days_min = 28,
  tf_days_max = 31,
  calendar_scheme = COALESCE(calendar_scheme, 'CAL')
WHERE tf = '1M_CAL';

UPDATE public.dim_timeframe
SET
  tf_days_min = 59,
  tf_days_max = 62,
  calendar_scheme = COALESCE(calendar_scheme, 'CAL')
WHERE tf = '2M_CAL';

UPDATE public.dim_timeframe
SET
  tf_days_min = 89,
  tf_days_max = 92,
  calendar_scheme = COALESCE(calendar_scheme, 'CAL')
WHERE tf = '3M_CAL';

UPDATE public.dim_timeframe
SET
  tf_days_min = 181,
  tf_days_max = 184,
  calendar_scheme = COALESCE(calendar_scheme, 'CAL')
WHERE tf = '6M_CAL';

UPDATE public.dim_timeframe
SET
  tf_days_min = 365,
  tf_days_max = 366,
  calendar_scheme = COALESCE(calendar_scheme, 'CAL')
WHERE tf IN ('12M_CAL', '1Y_CAL');

-- ============================================================================
-- 2) Seed missing TF rows
-- ============================================================================

/*
We seed:
  2A) ISO calendar-week TFs used by cmc_price_bars_multi_tf_cal_iso
  2B) Calendar-anchored families (partial allowed) for US + ISO
*/

-- ----------------------------------------------------------------------------
-- 2A) Calendar ISO week TFs (NOT anchored; full periods only)
-- ----------------------------------------------------------------------------
INSERT INTO public.dim_timeframe (
  tf, label, base_unit, tf_qty, tf_days_nominal,
  alignment_type, calendar_anchor, roll_policy,
  has_roll_flag, is_intraday, sort_order, description, is_canonical,
  calendar_scheme, allow_partial_start, allow_partial_end, tf_days_min, tf_days_max
)
VALUES
  ('1W_ISO',  '1 week (ISO week end)',  'W', 1,  7,  'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7001,
   'Calendar-aligned ISO week (Mon–Sun). Full periods only (no partial seeding).', true,
   'ISO', false, false, 7, 7),

  ('2W_ISO',  '2 weeks (ISO week end)', 'W', 2, 14,  'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7002,
   '2-week ISO calendar window aggregated to every 2nd ISO week end. Full periods only.', true,
   'ISO', false, false, 14, 14),

  ('3W_ISO',  '3 weeks (ISO week end)', 'W', 3, 21,  'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7003,
   '3-week ISO calendar window aggregated to every 3rd ISO week end. Full periods only.', true,
   'ISO', false, false, 21, 21),

  ('4W_ISO',  '4 weeks (ISO week end)', 'W', 4, 28,  'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7004,
   '4-week ISO calendar window aggregated to every 4th ISO week end. Full periods only.', true,
   'ISO', false, false, 28, 28),

  ('6W_ISO',  '6 weeks (ISO week end)', 'W', 6, 42,  'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7006,
   '6-week ISO calendar window aggregated to every 6th ISO week end. Full periods only.', true,
   'ISO', false, false, 42, 42),

  ('8W_ISO',  '8 weeks (ISO week end)', 'W', 8, 56,  'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7008,
   '8-week ISO calendar window aggregated to every 8th ISO week end. Full periods only.', true,
   'ISO', false, false, 56, 56),

  ('10W_ISO', '10 weeks (ISO week end)', 'W',10, 70, 'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7010,
   '10-week ISO calendar window aggregated to every 10th ISO week end. Full periods only.', true,
   'ISO', false, false, 70, 70)
ON CONFLICT (tf) DO UPDATE SET
  label               = EXCLUDED.label,
  base_unit            = EXCLUDED.base_unit,
  tf_qty               = EXCLUDED.tf_qty,
  tf_days_nominal      = EXCLUDED.tf_days_nominal,
  alignment_type       = EXCLUDED.alignment_type,
  calendar_anchor      = EXCLUDED.calendar_anchor,
  roll_policy          = EXCLUDED.roll_policy,
  has_roll_flag        = EXCLUDED.has_roll_flag,
  is_intraday          = EXCLUDED.is_intraday,
  sort_order           = EXCLUDED.sort_order,
  description          = EXCLUDED.description,
  is_canonical         = EXCLUDED.is_canonical,
  calendar_scheme      = EXCLUDED.calendar_scheme,
  allow_partial_start  = EXCLUDED.allow_partial_start,
  allow_partial_end    = EXCLUDED.allow_partial_end,
  tf_days_min          = EXCLUDED.tf_days_min,
  tf_days_max          = EXCLUDED.tf_days_max;

-- ----------------------------------------------------------------------------
-- 2B) Calendar-anchored TFs (partial allowed at dataset edges)
-- ----------------------------------------------------------------------------
INSERT INTO public.dim_timeframe (
  tf, label, base_unit, tf_qty, tf_days_nominal,
  alignment_type, calendar_anchor, roll_policy,
  has_roll_flag, is_intraday, sort_order, description, is_canonical,
  calendar_scheme, allow_partial_start, allow_partial_end, tf_days_min, tf_days_max
)
VALUES
  -- ======================
  -- US anchored weeks (use calendar_anchor='WEEK_END' to satisfy constraint)
  -- ======================
  ('1W_US_ANCHOR',  '1 week (US anchored)',  'W', 1,  7,  'calendar', 'WEEK_END', 'calendar_anchor', true, false, 7101,
   'US anchored week grid (market week end). Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 7),

  ('2W_US_ANCHOR',  '2 weeks (US anchored)', 'W', 2, 14, 'calendar', 'WEEK_END', 'calendar_anchor', true, false, 7102,
   'US anchored 2-week grid. Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 14),

  ('3W_US_ANCHOR',  '3 weeks (US anchored)', 'W', 3, 21, 'calendar', 'WEEK_END', 'calendar_anchor', true, false, 7103,
   'US anchored 3-week grid. Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 21),

  ('4W_US_ANCHOR',  '4 weeks (US anchored)', 'W', 4, 28, 'calendar', 'WEEK_END', 'calendar_anchor', true, false, 7104,
   'US anchored 4-week grid. Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 28),

  ('6W_US_ANCHOR',  '6 weeks (US anchored)', 'W', 6, 42, 'calendar', 'WEEK_END', 'calendar_anchor', true, false, 7106,
   'US anchored 6-week grid. Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 42),

  ('8W_US_ANCHOR',  '8 weeks (US anchored)', 'W', 8, 56, 'calendar', 'WEEK_END', 'calendar_anchor', true, false, 7108,
   'US anchored 8-week grid. Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 56),

  ('10W_US_ANCHOR', '10 weeks (US anchored)','W',10, 70, 'calendar', 'WEEK_END', 'calendar_anchor', true, false, 7110,
   'US anchored 10-week grid. Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 70),

  -- ======================
  -- US anchored months/years
  -- ======================
  ('1M_US_ANCHOR',  '1 month (US anchored)', 'M', 1, 30, 'calendar', 'EOM', 'calendar_anchor', true, false, 7201,
   'US anchored month grid (EOM). Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 31),

  ('2M_US_ANCHOR',  '2 months (US anchored)','M', 2, 60, 'calendar', 'EOM', 'calendar_anchor', true, false, 7202,
   'US anchored 2-month grid (EOM). Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 62),

  ('3M_US_ANCHOR',  '3 months (US anchored)','M', 3, 90, 'calendar', 'EOQ', 'calendar_anchor', true, false, 7203,
   'US anchored quarter grid (EOQ). Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 92),

  ('6M_US_ANCHOR',  '6 months (US anchored)','M', 6,180, 'calendar', 'EOQ', 'calendar_anchor', true, false, 7206,
   'US anchored semi-annual grid (EOQ). Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 184),

  ('12M_US_ANCHOR', '12 months (US anchored)','M',12,360, 'calendar', 'EOY', 'calendar_anchor', true, false, 7212,
   'US anchored 12-month grid (EOY). Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 366),

  ('1Y_US_ANCHOR',  '1 year (US anchored)',  'Y', 1,365, 'calendar', 'EOY', 'calendar_anchor', true, false, 7301,
   'US anchored yearly grid (EOY). Partial bars allowed at dataset edges.', true,
   'US', true, true, 1, 366),

  -- ======================
  -- ISO anchored weeks
  -- ======================
  ('1W_ISO_ANCHOR',  '1 week (ISO anchored)',  'W', 1,  7, 'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7401,
   'ISO anchored week grid (Mon–Sun). Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 7),

  ('2W_ISO_ANCHOR',  '2 weeks (ISO anchored)', 'W', 2, 14,'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7402,
   'ISO anchored 2-week grid. Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 14),

  ('3W_ISO_ANCHOR',  '3 weeks (ISO anchored)', 'W', 3, 21,'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7403,
   'ISO anchored 3-week grid. Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 21),

  ('4W_ISO_ANCHOR',  '4 weeks (ISO anchored)', 'W', 4, 28,'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7404,
   'ISO anchored 4-week grid. Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 28),

  ('6W_ISO_ANCHOR',  '6 weeks (ISO anchored)', 'W', 6, 42,'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7406,
   'ISO anchored 6-week grid. Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 42),

  ('8W_ISO_ANCHOR',  '8 weeks (ISO anchored)', 'W', 8, 56,'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7408,
   'ISO anchored 8-week grid. Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 56),

  ('10W_ISO_ANCHOR', '10 weeks (ISO anchored)','W',10,70,'calendar', 'ISO-WEEK', 'calendar_anchor', true, false, 7410,
   'ISO anchored 10-week grid. Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 70),

  -- ======================
  -- ISO anchored months/years
  -- ======================
  ('1M_ISO_ANCHOR',  '1 month (ISO anchored)', 'M', 1, 30,'calendar', 'EOM', 'calendar_anchor', true, false, 7501,
   'ISO anchored month grid (EOM). Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 31),

  ('2M_ISO_ANCHOR',  '2 months (ISO anchored)','M', 2, 60,'calendar', 'EOM', 'calendar_anchor', true, false, 7502,
   'ISO anchored 2-month grid (EOM). Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 62),

  ('3M_ISO_ANCHOR',  '3 months (ISO anchored)','M', 3, 90,'calendar', 'EOQ', 'calendar_anchor', true, false, 7503,
   'ISO anchored quarter grid (EOQ). Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 92),

  ('6M_ISO_ANCHOR',  '6 months (ISO anchored)','M', 6,180,'calendar', 'EOQ', 'calendar_anchor', true, false, 7506,
   'ISO anchored semi-annual grid (EOQ). Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 184),

  ('12M_ISO_ANCHOR', '12 months (ISO anchored)','M',12,360,'calendar', 'EOY', 'calendar_anchor', true, false, 7512,
   'ISO anchored 12-month grid (EOY). Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 366),

  ('1Y_ISO_ANCHOR',  '1 year (ISO anchored)',  'Y', 1,365,'calendar', 'EOY', 'calendar_anchor', true, false, 7601,
   'ISO anchored yearly grid (EOY). Partial bars allowed at dataset edges.', true,
   'ISO', true, true, 1, 366)
ON CONFLICT (tf) DO UPDATE SET
  label               = EXCLUDED.label,
  base_unit            = EXCLUDED.base_unit,
  tf_qty               = EXCLUDED.tf_qty,
  tf_days_nominal      = EXCLUDED.tf_days_nominal,
  alignment_type       = EXCLUDED.alignment_type,
  calendar_anchor      = EXCLUDED.calendar_anchor,
  roll_policy          = EXCLUDED.roll_policy,
  has_roll_flag        = EXCLUDED.has_roll_flag,
  is_intraday          = EXCLUDED.is_intraday,
  sort_order           = EXCLUDED.sort_order,
  description          = EXCLUDED.description,
  is_canonical         = EXCLUDED.is_canonical,
  calendar_scheme      = EXCLUDED.calendar_scheme,
  allow_partial_start  = EXCLUDED.allow_partial_start,
  allow_partial_end    = EXCLUDED.allow_partial_end,
  tf_days_min          = EXCLUDED.tf_days_min,
  tf_days_max          = EXCLUDED.tf_days_max;

COMMIT;

-- ============================================================================
-- 3) QA QUERIES (DO NOT RUN AUTOMATICALLY IN PROD MIGRATIONS)
-- ----------------------------------------------------------------------------
-- Copy/paste these manually after the migration if you want validation.
-- ============================================================================

/*
-- A) TFs present in bars tables but missing from dim_timeframe
SELECT DISTINCT b.tf
FROM public.cmc_price_bars_multi_tf b
LEFT JOIN public.dim_timeframe dt ON dt.tf = b.tf
WHERE dt.tf IS NULL
ORDER BY b.tf;

SELECT DISTINCT b.tf
FROM public.cmc_price_bars_multi_tf_cal_us b
LEFT JOIN public.dim_timeframe dt ON dt.tf = b.tf
WHERE dt.tf IS NULL
ORDER BY b.tf;

SELECT DISTINCT b.tf
FROM public.cmc_price_bars_multi_tf_cal_iso b
LEFT JOIN public.dim_timeframe dt ON dt.tf = b.tf
WHERE dt.tf IS NULL
ORDER BY b.tf;

SELECT DISTINCT b.tf
FROM public.cmc_price_bars_multi_tf_cal_anchor_us b
LEFT JOIN public.dim_timeframe dt ON dt.tf = b.tf
WHERE dt.tf IS NULL
ORDER BY b.tf;

SELECT DISTINCT b.tf
FROM public.cmc_price_bars_multi_tf_cal_anchor_iso b
LEFT JOIN public.dim_timeframe dt ON dt.tf = b.tf
WHERE dt.tf IS NULL
ORDER BY b.tf;

-- B) Realized tf_days outside bounds
SELECT b.tf, b.tf_days, COUNT(*) AS n
FROM public.cmc_price_bars_multi_tf b
JOIN public.dim_timeframe dt ON dt.tf = b.tf
WHERE b.tf_days < dt.tf_days_min
   OR b.tf_days > dt.tf_days_max
GROUP BY b.tf, b.tf_days
ORDER BY b.tf, b.tf_days;
*/
