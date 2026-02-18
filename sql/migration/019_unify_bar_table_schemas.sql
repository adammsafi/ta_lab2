-- 019_unify_bar_table_schemas.sql
--
-- Unifies all 6 bar tables to a single canonical schema:
--   PK = (id, tf, bar_seq, timestamp)
--   37 base columns + bar_anchor_offset on anchor tables
--
-- Run order: MUST run BEFORE deploying updated Python code.
-- Idempotent: uses IF NOT EXISTS / IF EXISTS throughout.
--
-- Tables affected:
--   1. cmc_price_bars_1d
--   2. cmc_price_bars_multi_tf
--   3. cmc_price_bars_multi_tf_cal_us
--   4. cmc_price_bars_multi_tf_cal_iso
--   5. cmc_price_bars_multi_tf_cal_anchor_us
--   6. cmc_price_bars_multi_tf_cal_anchor_iso

BEGIN;

-- ============================================================================
-- 1) cmc_price_bars_1d
-- ============================================================================

-- Add missing columns
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS tf_days INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS pos_in_bar INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS count_days INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS count_days_remaining INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS last_ts_half_open TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS count_missing_days INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS count_missing_days_start INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS count_missing_days_end INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS count_missing_days_interior INTEGER;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS missing_days_where TEXT;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS first_missing_day TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS last_missing_day TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS repaired_high BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS repaired_low BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS repaired_open BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS repaired_close BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS repaired_volume BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_1d ADD COLUMN IF NOT EXISTS repaired_market_cap BOOLEAN NOT NULL DEFAULT FALSE;

-- Change bar_seq from BIGINT to INTEGER
ALTER TABLE public.cmc_price_bars_1d ALTER COLUMN bar_seq TYPE INTEGER;

-- Backfill computed values for 1D
UPDATE public.cmc_price_bars_1d SET tf_days = 1 WHERE tf_days IS NULL;
UPDATE public.cmc_price_bars_1d SET pos_in_bar = 1 WHERE pos_in_bar IS NULL;
UPDATE public.cmc_price_bars_1d SET count_days = 1 WHERE count_days IS NULL;
UPDATE public.cmc_price_bars_1d SET count_days_remaining = 0 WHERE count_days_remaining IS NULL;
UPDATE public.cmc_price_bars_1d SET count_missing_days = 0 WHERE count_missing_days IS NULL;
UPDATE public.cmc_price_bars_1d SET count_missing_days_start = 0 WHERE count_missing_days_start IS NULL;
UPDATE public.cmc_price_bars_1d SET count_missing_days_end = 0 WHERE count_missing_days_end IS NULL;
UPDATE public.cmc_price_bars_1d SET count_missing_days_interior = 0 WHERE count_missing_days_interior IS NULL;

-- Drop old PK and create new one
ALTER TABLE public.cmc_price_bars_1d DROP CONSTRAINT IF EXISTS cmc_price_bars_1d_pkey;
ALTER TABLE public.cmc_price_bars_1d DROP CONSTRAINT IF EXISTS cmc_price_bars_1d_id_tf_bar_seq_uniq;
ALTER TABLE public.cmc_price_bars_1d ADD PRIMARY KEY (id, tf, bar_seq, "timestamp");

-- Create unified indexes
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_1d_id_tf_barseq
    ON public.cmc_price_bars_1d (id, tf, bar_seq);
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_1d_id_tf_timestamp
    ON public.cmc_price_bars_1d (id, tf, "timestamp");
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_1d_tf_timestamp
    ON public.cmc_price_bars_1d (tf, "timestamp");
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_1d__canon_timestamp
    ON public.cmc_price_bars_1d (id, tf, "timestamp")
    WHERE is_partial_end = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_1d_final_per_barseq
    ON public.cmc_price_bars_1d (id, tf, bar_seq)
    WHERE is_partial_end = FALSE;


-- ============================================================================
-- 2) cmc_price_bars_multi_tf
-- ============================================================================

-- Add missing columns
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS src_name TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS src_file TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS src_load_ts TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_timehigh BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_timelow BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_high BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_low BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_open BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_close BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_volume BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf ADD COLUMN IF NOT EXISTS repaired_market_cap BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill NULL timestamps from time_close
UPDATE public.cmc_price_bars_multi_tf
SET "timestamp" = time_close
WHERE "timestamp" IS NULL;

-- Make timestamp NOT NULL
ALTER TABLE public.cmc_price_bars_multi_tf ALTER COLUMN "timestamp" SET NOT NULL;

-- Drop old PK and constraints, create new PK
ALTER TABLE public.cmc_price_bars_multi_tf DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf ADD PRIMARY KEY (id, tf, bar_seq, "timestamp");

-- Recreate indexes with timestamp
DROP INDEX IF EXISTS ix_cmc_price_bars_multi_tf_tf_timeclose;
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_id_tf_timestamp
    ON public.cmc_price_bars_multi_tf (id, tf, "timestamp");
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_tf_timestamp
    ON public.cmc_price_bars_multi_tf (tf, "timestamp");

-- Recreate unique indexes
DROP INDEX IF EXISTS uq_cmc_price_bars_multi_tf__canon_close;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf__canon_timestamp
    ON public.cmc_price_bars_multi_tf (id, tf, "timestamp")
    WHERE is_partial_end = FALSE;


-- ============================================================================
-- 3) cmc_price_bars_multi_tf_cal_iso
-- ============================================================================

-- Add missing columns
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS count_missing_days_start INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS count_missing_days_end INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS count_missing_days_interior INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS missing_days_where TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS src_name TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS src_file TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS src_load_ts TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_timehigh BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_timelow BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_high BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_low BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_open BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_close BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_volume BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS repaired_market_cap BOOLEAN NOT NULL DEFAULT FALSE;

-- Change first/last_missing_day from DATE to TIMESTAMPTZ
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ALTER COLUMN first_missing_day TYPE TIMESTAMPTZ USING first_missing_day::TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ALTER COLUMN last_missing_day TYPE TIMESTAMPTZ USING last_missing_day::TIMESTAMPTZ;

-- Backfill NULL timestamps from time_close
UPDATE public.cmc_price_bars_multi_tf_cal_iso
SET "timestamp" = time_close
WHERE "timestamp" IS NULL;

-- Make timestamp NOT NULL
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ALTER COLUMN "timestamp" SET NOT NULL;

-- Drop old UNIQUE constraint (was PK in some cases), create new PK
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_iso_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_iso_uq;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso ADD PRIMARY KEY (id, tf, bar_seq, "timestamp");

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_iso_id_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_iso (id, tf, "timestamp");
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_iso_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_iso (tf, "timestamp");
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_iso__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_iso (id, tf, "timestamp")
    WHERE is_partial_end = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_iso_final_per_barseq
    ON public.cmc_price_bars_multi_tf_cal_iso (id, tf, bar_seq)
    WHERE is_partial_end = FALSE;


-- ============================================================================
-- 4) cmc_price_bars_multi_tf_cal_us
-- ============================================================================

-- Add missing columns
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS count_missing_days_start INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS count_missing_days_end INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS count_missing_days_interior INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS missing_days_where TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS src_name TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS src_file TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS src_load_ts TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_timehigh BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_timelow BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_high BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_low BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_open BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_close BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_volume BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS repaired_market_cap BOOLEAN NOT NULL DEFAULT FALSE;

-- Change first/last_missing_day from DATE to TIMESTAMPTZ
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ALTER COLUMN first_missing_day TYPE TIMESTAMPTZ USING first_missing_day::TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ALTER COLUMN last_missing_day TYPE TIMESTAMPTZ USING last_missing_day::TIMESTAMPTZ;

-- Backfill NULL timestamps from time_close
UPDATE public.cmc_price_bars_multi_tf_cal_us
SET "timestamp" = time_close
WHERE "timestamp" IS NULL;

-- Make timestamp NOT NULL
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ALTER COLUMN "timestamp" SET NOT NULL;

-- Drop old UNIQUE constraint, create new PK
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_us_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_us_uq;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us ADD PRIMARY KEY (id, tf, bar_seq, "timestamp");

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_us_id_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_us (id, tf, "timestamp");
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_us_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_us (tf, "timestamp");
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_us__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_us (id, tf, "timestamp")
    WHERE is_partial_end = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_us_final_per_barseq
    ON public.cmc_price_bars_multi_tf_cal_us (id, tf, bar_seq)
    WHERE is_partial_end = FALSE;


-- ============================================================================
-- 5) cmc_price_bars_multi_tf_cal_anchor_iso
-- ============================================================================

-- Add missing columns
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS count_missing_days_start INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS count_missing_days_end INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS count_missing_days_interior INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS missing_days_where TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS src_name TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS src_file TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS src_load_ts TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_timehigh BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_timelow BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_high BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_low BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_open BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_close BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_volume BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS repaired_market_cap BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS bar_anchor_offset INTEGER;

-- Change first/last_missing_day to TIMESTAMPTZ if they are DATE
-- (anchor tables already had TIMESTAMPTZ in some versions)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'cmc_price_bars_multi_tf_cal_anchor_iso'
      AND column_name = 'first_missing_day' AND data_type = 'date'
  ) THEN
    ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ALTER COLUMN first_missing_day TYPE TIMESTAMPTZ USING first_missing_day::TIMESTAMPTZ;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'cmc_price_bars_multi_tf_cal_anchor_iso'
      AND column_name = 'last_missing_day' AND data_type = 'date'
  ) THEN
    ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ALTER COLUMN last_missing_day TYPE TIMESTAMPTZ USING last_missing_day::TIMESTAMPTZ;
  END IF;
END $$;

-- Backfill NULL timestamps from time_close
UPDATE public.cmc_price_bars_multi_tf_cal_anchor_iso
SET "timestamp" = time_close
WHERE "timestamp" IS NULL;

-- Make timestamp NOT NULL
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ALTER COLUMN "timestamp" SET NOT NULL;

-- Drop old UNIQUE constraint, create new PK
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_anchor_iso_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_anchor_iso_uq;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso ADD PRIMARY KEY (id, tf, bar_seq, "timestamp");

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_anchor_iso_id_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_iso (id, tf, "timestamp");
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_anchor_iso_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_iso (tf, "timestamp");
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_iso__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_iso (id, tf, bar_anchor_offset, "timestamp")
    WHERE is_partial_end = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_iso_final_per_barseq
    ON public.cmc_price_bars_multi_tf_cal_anchor_iso (id, tf, bar_seq, bar_anchor_offset)
    WHERE is_partial_end = FALSE;


-- ============================================================================
-- 6) cmc_price_bars_multi_tf_cal_anchor_us
-- ============================================================================

-- Add missing columns
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS count_missing_days_start INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS count_missing_days_end INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS count_missing_days_interior INTEGER;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS missing_days_where TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS src_name TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS src_file TEXT;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS src_load_ts TIMESTAMPTZ;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_timehigh BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_timelow BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_high BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_low BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_open BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_close BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_volume BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS repaired_market_cap BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS bar_anchor_offset INTEGER;

-- Change first/last_missing_day to TIMESTAMPTZ if they are DATE
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'cmc_price_bars_multi_tf_cal_anchor_us'
      AND column_name = 'first_missing_day' AND data_type = 'date'
  ) THEN
    ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ALTER COLUMN first_missing_day TYPE TIMESTAMPTZ USING first_missing_day::TIMESTAMPTZ;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'cmc_price_bars_multi_tf_cal_anchor_us'
      AND column_name = 'last_missing_day' AND data_type = 'date'
  ) THEN
    ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ALTER COLUMN last_missing_day TYPE TIMESTAMPTZ USING last_missing_day::TIMESTAMPTZ;
  END IF;
END $$;

-- Backfill NULL timestamps from time_close
UPDATE public.cmc_price_bars_multi_tf_cal_anchor_us
SET "timestamp" = time_close
WHERE "timestamp" IS NULL;

-- Make timestamp NOT NULL
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ALTER COLUMN "timestamp" SET NOT NULL;

-- Drop old UNIQUE constraint, create new PK
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_anchor_us_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_anchor_us_uq;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us ADD PRIMARY KEY (id, tf, bar_seq, "timestamp");

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_anchor_us_id_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_us (id, tf, "timestamp");
CREATE INDEX IF NOT EXISTS ix_cmc_price_bars_multi_tf_cal_anchor_us_tf_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_us (tf, "timestamp");
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_us__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_us (id, tf, bar_anchor_offset, "timestamp")
    WHERE is_partial_end = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_us_final_per_barseq
    ON public.cmc_price_bars_multi_tf_cal_anchor_us (id, tf, bar_seq, bar_anchor_offset)
    WHERE is_partial_end = FALSE;

COMMIT;
