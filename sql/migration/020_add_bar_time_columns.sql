-- 020_add_bar_time_columns.sql
--
-- Add time_open_bar and time_close_bar columns to all 6 bar tables.
--
-- Context:
--   time_close was changed from per-row (daily snapshot date) to bar-level
--   (scheduled end date) during the unified schema migration. This migration:
--   1. Adds time_open_bar = bar-level opening time (= current time_open)
--   2. Adds time_close_bar = bar-level scheduled end (= current time_close)
--   3. Reverts time_close to per-row = timestamp for multi-TF tables
--
-- Result: 6 time-boundary columns:
--   time_open      = bar-level opening time (UNCHANGED)
--   time_close     = per-row snapshot time = timestamp (REVERTED for multi-TF)
--   time_open_bar  = bar-level opening time (NEW, = time_open)
--   time_close_bar = bar-level scheduled end (NEW, = old time_close)

-- =============================================================================
-- 1) cmc_price_bars_1d  (1D: already per-row, backfill only)
-- =============================================================================
ALTER TABLE public.cmc_price_bars_1d
    ADD COLUMN IF NOT EXISTS time_open_bar  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS time_close_bar TIMESTAMPTZ;

UPDATE public.cmc_price_bars_1d
SET time_open_bar  = time_open,
    time_close_bar = time_close
WHERE time_open_bar IS NULL;

-- =============================================================================
-- 2) cmc_price_bars_multi_tf
-- =============================================================================
ALTER TABLE public.cmc_price_bars_multi_tf
    ADD COLUMN IF NOT EXISTS time_open_bar  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS time_close_bar TIMESTAMPTZ;

UPDATE public.cmc_price_bars_multi_tf
SET time_open_bar  = time_open,
    time_close_bar = time_close
WHERE time_open_bar IS NULL;

-- Revert time_close to per-row (= timestamp)
UPDATE public.cmc_price_bars_multi_tf
SET time_close = "timestamp"
WHERE time_close <> "timestamp";

-- =============================================================================
-- 3) cmc_price_bars_multi_tf_cal_us
-- =============================================================================
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us
    ADD COLUMN IF NOT EXISTS time_open_bar  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS time_close_bar TIMESTAMPTZ;

UPDATE public.cmc_price_bars_multi_tf_cal_us
SET time_open_bar  = time_open,
    time_close_bar = time_close
WHERE time_open_bar IS NULL;

-- Revert time_close to per-row (= timestamp)
UPDATE public.cmc_price_bars_multi_tf_cal_us
SET time_close = "timestamp"
WHERE time_close <> "timestamp";

-- =============================================================================
-- 4) cmc_price_bars_multi_tf_cal_iso
-- =============================================================================
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso
    ADD COLUMN IF NOT EXISTS time_open_bar  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS time_close_bar TIMESTAMPTZ;

UPDATE public.cmc_price_bars_multi_tf_cal_iso
SET time_open_bar  = time_open,
    time_close_bar = time_close
WHERE time_open_bar IS NULL;

-- Revert time_close to per-row (= timestamp)
UPDATE public.cmc_price_bars_multi_tf_cal_iso
SET time_close = "timestamp"
WHERE time_close <> "timestamp";

-- =============================================================================
-- 5) cmc_price_bars_multi_tf_cal_anchor_us
-- =============================================================================
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us
    ADD COLUMN IF NOT EXISTS time_open_bar  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS time_close_bar TIMESTAMPTZ;

UPDATE public.cmc_price_bars_multi_tf_cal_anchor_us
SET time_open_bar  = time_open,
    time_close_bar = time_close
WHERE time_open_bar IS NULL;

-- Revert time_close to per-row (= timestamp)
UPDATE public.cmc_price_bars_multi_tf_cal_anchor_us
SET time_close = "timestamp"
WHERE time_close <> "timestamp";

-- =============================================================================
-- 6) cmc_price_bars_multi_tf_cal_anchor_iso
-- =============================================================================
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso
    ADD COLUMN IF NOT EXISTS time_open_bar  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS time_close_bar TIMESTAMPTZ;

UPDATE public.cmc_price_bars_multi_tf_cal_anchor_iso
SET time_open_bar  = time_open,
    time_close_bar = time_close
WHERE time_open_bar IS NULL;

-- Revert time_close to per-row (= timestamp)
UPDATE public.cmc_price_bars_multi_tf_cal_anchor_iso
SET time_close = "timestamp"
WHERE time_close <> "timestamp";
