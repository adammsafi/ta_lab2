CREATE TABLE IF NOT EXISTS public.cmc_price_bars_1d_state (
  id integer PRIMARY KEY,
  last_src_ts timestamptz,          -- max(src."timestamp") processed for this id
  daily_min_seen timestamptz,       -- min(src."timestamp") ever seen for this id (for backfill detection)
  last_run_ts timestamptz NOT NULL DEFAULT now(),
  last_upserted integer NOT NULL DEFAULT 0,
  last_repaired_timehigh integer NOT NULL DEFAULT 0,
  last_repaired_timelow  integer NOT NULL DEFAULT 0,
  last_rejected integer NOT NULL DEFAULT 0
);

-- Migration: Add daily_min_seen column to existing table
ALTER TABLE public.cmc_price_bars_1d_state
ADD COLUMN IF NOT EXISTS daily_min_seen TIMESTAMPTZ;

-- Backfill existing rows: set daily_min_seen = last_src_ts for safety
-- (conservative: assumes no historical data before what we've processed)
UPDATE public.cmc_price_bars_1d_state
SET daily_min_seen = last_src_ts
WHERE daily_min_seen IS NULL;

-- Comment explaining purpose
COMMENT ON COLUMN public.cmc_price_bars_1d_state.daily_min_seen IS
'Earliest timestamp ever seen in price_histories7 for this ID.
Used for backfill detection: if MIN(timestamp) < daily_min_seen, historical data
was backfilled and full rebuild is required to maintain bar_seq integrity.';
