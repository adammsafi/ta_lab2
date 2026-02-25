-- Migration: Replace is_primary_venue (BOOLEAN) with venue_rank (INTEGER) on all bar tables
-- and replace is_primary (BOOLEAN) with venue_rank (INTEGER) on dim_listings.
--
-- venue_rank is informational metadata (lower = better).
-- It is NEVER used for filtering -- all venues flow through the pipeline.
-- Populated from row-count proxy in tvc_price_histories.

BEGIN;

-- ============================================================================
-- 0. dim_listings: add venue_rank, populate, drop is_primary
-- ============================================================================

ALTER TABLE public.dim_listings
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

-- Populate from row count in tvc_price_histories as volume proxy
UPDATE public.dim_listings dl SET venue_rank = sub.rank_val
FROM (
  SELECT id, venue,
    (PERCENT_RANK() OVER (PARTITION BY id ORDER BY count(*) DESC) * 100)::integer AS rank_val
  FROM public.tvc_price_histories
  GROUP BY id, venue
) sub
WHERE dl.id = sub.id AND dl.venue = sub.venue;

ALTER TABLE public.dim_listings DROP COLUMN IF EXISTS is_primary;

-- ============================================================================
-- 1. cmc_price_bars_1d
-- ============================================================================

ALTER TABLE public.cmc_price_bars_1d
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

UPDATE public.cmc_price_bars_1d b SET venue_rank = COALESCE(dl.venue_rank, 50)
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.venue = b.venue;

ALTER TABLE public.cmc_price_bars_1d DROP COLUMN IF EXISTS is_primary_venue;

DROP INDEX IF EXISTS uq_cmc_price_bars_1d__canon_timestamp;
CREATE UNIQUE INDEX uq_cmc_price_bars_1d__canon_timestamp
    ON public.cmc_price_bars_1d (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

-- ============================================================================
-- 2. cmc_price_bars_multi_tf
-- ============================================================================

ALTER TABLE public.cmc_price_bars_multi_tf
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

UPDATE public.cmc_price_bars_multi_tf b SET venue_rank = COALESCE(dl.venue_rank, 50)
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.venue = b.venue;

ALTER TABLE public.cmc_price_bars_multi_tf DROP COLUMN IF EXISTS is_primary_venue;

DROP INDEX IF EXISTS uq_cmc_price_bars_multi_tf__canon_timestamp;
CREATE UNIQUE INDEX uq_cmc_price_bars_multi_tf__canon_timestamp
    ON public.cmc_price_bars_multi_tf (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

-- ============================================================================
-- 3. cmc_price_bars_multi_tf_cal_us
-- ============================================================================

ALTER TABLE public.cmc_price_bars_multi_tf_cal_us
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

UPDATE public.cmc_price_bars_multi_tf_cal_us b SET venue_rank = COALESCE(dl.venue_rank, 50)
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.venue = b.venue;

ALTER TABLE public.cmc_price_bars_multi_tf_cal_us DROP COLUMN IF EXISTS is_primary_venue;

DROP INDEX IF EXISTS uq_cmc_price_bars_multi_tf_cal_us__canon_timestamp;
CREATE UNIQUE INDEX uq_cmc_price_bars_multi_tf_cal_us__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_us (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

-- ============================================================================
-- 4. cmc_price_bars_multi_tf_cal_iso
-- ============================================================================

ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

UPDATE public.cmc_price_bars_multi_tf_cal_iso b SET venue_rank = COALESCE(dl.venue_rank, 50)
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.venue = b.venue;

ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso DROP COLUMN IF EXISTS is_primary_venue;

DROP INDEX IF EXISTS uq_cmc_price_bars_multi_tf_cal_iso__canon_timestamp;
CREATE UNIQUE INDEX uq_cmc_price_bars_multi_tf_cal_iso__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_iso (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

-- ============================================================================
-- 5. cmc_price_bars_multi_tf_cal_anchor_us
-- ============================================================================

ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

UPDATE public.cmc_price_bars_multi_tf_cal_anchor_us b SET venue_rank = COALESCE(dl.venue_rank, 50)
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.venue = b.venue;

ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us DROP COLUMN IF EXISTS is_primary_venue;

DROP INDEX IF EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_us__canon_timestamp;
CREATE UNIQUE INDEX uq_cmc_price_bars_multi_tf_cal_anchor_us__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_us (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

-- ============================================================================
-- 6. cmc_price_bars_multi_tf_cal_anchor_iso
-- ============================================================================

ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

UPDATE public.cmc_price_bars_multi_tf_cal_anchor_iso b SET venue_rank = COALESCE(dl.venue_rank, 50)
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.venue = b.venue;

ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso DROP COLUMN IF EXISTS is_primary_venue;

DROP INDEX IF EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_iso__canon_timestamp;
CREATE UNIQUE INDEX uq_cmc_price_bars_multi_tf_cal_anchor_iso__canon_timestamp
    ON public.cmc_price_bars_multi_tf_cal_anchor_iso (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

-- ============================================================================
-- 7. cmc_price_bars_multi_tf_u (unified)
-- ============================================================================

ALTER TABLE public.cmc_price_bars_multi_tf_u
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

UPDATE public.cmc_price_bars_multi_tf_u b SET venue_rank = COALESCE(dl.venue_rank, 50)
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.venue = b.venue;

ALTER TABLE public.cmc_price_bars_multi_tf_u DROP COLUMN IF EXISTS is_primary_venue;

DROP INDEX IF EXISTS uq_cmc_price_bars_multi_tf_u__canon_timestamp;
CREATE UNIQUE INDEX uq_cmc_price_bars_multi_tf_u__canon_timestamp
    ON public.cmc_price_bars_multi_tf_u (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

-- ============================================================================
-- 8. Add venue to bar state tables (PK becomes (id, tf, venue))
-- ============================================================================

-- cmc_price_bars_multi_tf_state
ALTER TABLE public.cmc_price_bars_multi_tf_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.cmc_price_bars_multi_tf_state
  DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_state_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_state
  ADD PRIMARY KEY (id, tf, venue);

-- cmc_price_bars_multi_tf_cal_us_state
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us_state
  DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_us_state_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_us_state
  ADD PRIMARY KEY (id, tf, venue);

-- cmc_price_bars_multi_tf_cal_iso_state
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso_state
  DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_iso_state_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_iso_state
  ADD PRIMARY KEY (id, tf, venue);

-- cmc_price_bars_multi_tf_cal_anchor_us_state
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us_state
  DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_anchor_us_state_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us_state
  ADD PRIMARY KEY (id, tf, venue);

-- cmc_price_bars_multi_tf_cal_anchor_iso_state
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso_state
  DROP CONSTRAINT IF EXISTS cmc_price_bars_multi_tf_cal_anchor_iso_state_pkey;
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso_state
  ADD PRIMARY KEY (id, tf, venue);

COMMIT;
