-- Migration: Add venue + is_primary_venue columns to all 7 bar tables
-- Purpose: Support multi-exchange price data (e.g., CPOOL on BYBIT/GATE/KRAKEN)
-- Default venue='CMC_AGG' for existing CMC aggregated data

BEGIN;

-- ============================================================================
-- 1. price_bars_1d
-- ============================================================================

ALTER TABLE public.price_bars_1d
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS is_primary_venue BOOLEAN NOT NULL DEFAULT TRUE;

-- Backfill existing TVC rows with actual venue
UPDATE public.price_bars_1d b
SET venue = dl.venue
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.is_primary = TRUE
  AND b.src_name = 'TradingView';

ALTER TABLE public.price_bars_1d DROP CONSTRAINT price_bars_1d_pkey;
ALTER TABLE public.price_bars_1d ADD PRIMARY KEY (id, tf, bar_seq, venue, "timestamp");

DROP INDEX IF EXISTS uq_price_bars_1d__canon_timestamp;
CREATE UNIQUE INDEX uq_price_bars_1d__canon_timestamp
    ON public.price_bars_1d (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

DROP INDEX IF EXISTS ix_price_bars_1d_id_tf_barseq;
CREATE INDEX ix_price_bars_1d_id_tf_barseq
    ON public.price_bars_1d (id, tf, venue, bar_seq);

DROP INDEX IF EXISTS ix_price_bars_1d_id_tf_timeclose;
CREATE INDEX ix_price_bars_1d_id_tf_timeclose
    ON public.price_bars_1d (id, tf, venue, time_close);

DROP INDEX IF EXISTS ix_price_bars_1d_id_tf_timestamp;
CREATE INDEX ix_price_bars_1d_id_tf_timestamp
    ON public.price_bars_1d (id, tf, venue, "timestamp");

DROP INDEX IF EXISTS ix_price_bars_1d_tf_timestamp;
CREATE INDEX ix_price_bars_1d_tf_timestamp
    ON public.price_bars_1d (tf, venue, "timestamp");


-- ============================================================================
-- 2. price_bars_multi_tf
-- ============================================================================

ALTER TABLE public.price_bars_multi_tf
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS is_primary_venue BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE public.price_bars_multi_tf b
SET venue = dl.venue
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.is_primary = TRUE
  AND b.src_name = 'TradingView';

ALTER TABLE public.price_bars_multi_tf DROP CONSTRAINT price_bars_multi_tf_pkey;
ALTER TABLE public.price_bars_multi_tf ADD PRIMARY KEY (id, tf, bar_seq, venue, "timestamp");

DROP INDEX IF EXISTS uq_price_bars_multi_tf__canon_timestamp;
CREATE UNIQUE INDEX uq_price_bars_multi_tf__canon_timestamp
    ON public.price_bars_multi_tf (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

DROP INDEX IF EXISTS ix_price_bars_multi_tf_id_tf_barseq;
CREATE INDEX ix_price_bars_multi_tf_id_tf_barseq
    ON public.price_bars_multi_tf (id, tf, venue, bar_seq);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_id_tf_timeclose;
CREATE INDEX ix_price_bars_multi_tf_id_tf_timeclose
    ON public.price_bars_multi_tf (id, tf, venue, time_close);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_id_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_id_tf_timestamp
    ON public.price_bars_multi_tf (id, tf, venue, "timestamp");

DROP INDEX IF EXISTS ix_price_bars_multi_tf_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_tf_timestamp
    ON public.price_bars_multi_tf (tf, venue, "timestamp");


-- ============================================================================
-- 3. price_bars_multi_tf_cal_us
-- ============================================================================

ALTER TABLE public.price_bars_multi_tf_cal_us
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS is_primary_venue BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE public.price_bars_multi_tf_cal_us b
SET venue = dl.venue
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.is_primary = TRUE
  AND b.src_name = 'TradingView';

ALTER TABLE public.price_bars_multi_tf_cal_us DROP CONSTRAINT price_bars_multi_tf_cal_us_pkey;
ALTER TABLE public.price_bars_multi_tf_cal_us ADD PRIMARY KEY (id, tf, bar_seq, venue, "timestamp");

DROP INDEX IF EXISTS uq_price_bars_multi_tf_cal_us__canon_timestamp;
CREATE UNIQUE INDEX uq_price_bars_multi_tf_cal_us__canon_timestamp
    ON public.price_bars_multi_tf_cal_us (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_us_id_tf_barseq;
CREATE INDEX ix_price_bars_multi_tf_cal_us_id_tf_barseq
    ON public.price_bars_multi_tf_cal_us (id, tf, venue, bar_seq);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_us_id_tf_timeclose;
CREATE INDEX ix_price_bars_multi_tf_cal_us_id_tf_timeclose
    ON public.price_bars_multi_tf_cal_us (id, tf, venue, time_close);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_us_id_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_us_id_tf_timestamp
    ON public.price_bars_multi_tf_cal_us (id, tf, venue, "timestamp");

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_us_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_us_tf_timestamp
    ON public.price_bars_multi_tf_cal_us (tf, venue, "timestamp");


-- ============================================================================
-- 4. price_bars_multi_tf_cal_iso
-- ============================================================================

ALTER TABLE public.price_bars_multi_tf_cal_iso
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS is_primary_venue BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE public.price_bars_multi_tf_cal_iso b
SET venue = dl.venue
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.is_primary = TRUE
  AND b.src_name = 'TradingView';

ALTER TABLE public.price_bars_multi_tf_cal_iso DROP CONSTRAINT price_bars_multi_tf_cal_iso_pkey;
ALTER TABLE public.price_bars_multi_tf_cal_iso ADD PRIMARY KEY (id, tf, bar_seq, venue, "timestamp");

DROP INDEX IF EXISTS uq_price_bars_multi_tf_cal_iso__canon_timestamp;
CREATE UNIQUE INDEX uq_price_bars_multi_tf_cal_iso__canon_timestamp
    ON public.price_bars_multi_tf_cal_iso (id, tf, venue, "timestamp")
    WHERE is_partial_end = FALSE;

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_iso_id_tf_barseq;
CREATE INDEX ix_price_bars_multi_tf_cal_iso_id_tf_barseq
    ON public.price_bars_multi_tf_cal_iso (id, tf, venue, bar_seq);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_iso_id_tf_timeclose;
CREATE INDEX ix_price_bars_multi_tf_cal_iso_id_tf_timeclose
    ON public.price_bars_multi_tf_cal_iso (id, tf, venue, time_close);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_iso_id_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_iso_id_tf_timestamp
    ON public.price_bars_multi_tf_cal_iso (id, tf, venue, "timestamp");

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_iso_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_iso_tf_timestamp
    ON public.price_bars_multi_tf_cal_iso (tf, venue, "timestamp");


-- ============================================================================
-- 5. price_bars_multi_tf_cal_anchor_us
-- ============================================================================

ALTER TABLE public.price_bars_multi_tf_cal_anchor_us
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS is_primary_venue BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE public.price_bars_multi_tf_cal_anchor_us b
SET venue = dl.venue
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.is_primary = TRUE
  AND b.src_name = 'TradingView';

ALTER TABLE public.price_bars_multi_tf_cal_anchor_us DROP CONSTRAINT price_bars_multi_tf_cal_anchor_us_pkey;
ALTER TABLE public.price_bars_multi_tf_cal_anchor_us ADD PRIMARY KEY (id, tf, bar_seq, venue, "timestamp");

DROP INDEX IF EXISTS uq_price_bars_multi_tf_cal_anchor_us__canon_timestamp;
CREATE UNIQUE INDEX uq_price_bars_multi_tf_cal_anchor_us__canon_timestamp
    ON public.price_bars_multi_tf_cal_anchor_us (id, tf, venue, bar_anchor_offset, "timestamp")
    WHERE is_partial_end = FALSE;

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_us_id_tf_barseq;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_us_id_tf_barseq
    ON public.price_bars_multi_tf_cal_anchor_us (id, tf, venue, bar_seq);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_us_id_tf_timeclose;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_us_id_tf_timeclose
    ON public.price_bars_multi_tf_cal_anchor_us (id, tf, venue, time_close);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_us_id_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_us_id_tf_timestamp
    ON public.price_bars_multi_tf_cal_anchor_us (id, tf, venue, "timestamp");

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_us_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_us_tf_timestamp
    ON public.price_bars_multi_tf_cal_anchor_us (tf, venue, "timestamp");


-- ============================================================================
-- 6. price_bars_multi_tf_cal_anchor_iso
-- ============================================================================

ALTER TABLE public.price_bars_multi_tf_cal_anchor_iso
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS is_primary_venue BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE public.price_bars_multi_tf_cal_anchor_iso b
SET venue = dl.venue
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.is_primary = TRUE
  AND b.src_name = 'TradingView';

ALTER TABLE public.price_bars_multi_tf_cal_anchor_iso DROP CONSTRAINT price_bars_multi_tf_cal_anchor_iso_pkey;
ALTER TABLE public.price_bars_multi_tf_cal_anchor_iso ADD PRIMARY KEY (id, tf, bar_seq, venue, "timestamp");

DROP INDEX IF EXISTS uq_price_bars_multi_tf_cal_anchor_iso__canon_timestamp;
CREATE UNIQUE INDEX uq_price_bars_multi_tf_cal_anchor_iso__canon_timestamp
    ON public.price_bars_multi_tf_cal_anchor_iso (id, tf, venue, bar_anchor_offset, "timestamp")
    WHERE is_partial_end = FALSE;

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_iso_id_tf_barseq;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_iso_id_tf_barseq
    ON public.price_bars_multi_tf_cal_anchor_iso (id, tf, venue, bar_seq);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_iso_id_tf_timeclose;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_iso_id_tf_timeclose
    ON public.price_bars_multi_tf_cal_anchor_iso (id, tf, venue, time_close);

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_iso_id_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_iso_id_tf_timestamp
    ON public.price_bars_multi_tf_cal_anchor_iso (id, tf, venue, "timestamp");

DROP INDEX IF EXISTS ix_price_bars_multi_tf_cal_anchor_iso_tf_timestamp;
CREATE INDEX ix_price_bars_multi_tf_cal_anchor_iso_tf_timestamp
    ON public.price_bars_multi_tf_cal_anchor_iso (tf, venue, "timestamp");


-- ============================================================================
-- 7. price_bars_multi_tf_u (unified)
-- ============================================================================

ALTER TABLE public.price_bars_multi_tf_u
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS is_primary_venue BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE public.price_bars_multi_tf_u b
SET venue = dl.venue
FROM public.dim_listings dl
WHERE dl.id = b.id AND dl.is_primary = TRUE
  AND b.src_name = 'TradingView';

ALTER TABLE public.price_bars_multi_tf_u DROP CONSTRAINT price_bars_multi_tf_u_pkey;
ALTER TABLE public.price_bars_multi_tf_u ADD PRIMARY KEY (id, tf, bar_seq, venue, "timestamp", alignment_source);

DROP INDEX IF EXISTS ix_price_bars_u_id_tf_ts;
CREATE INDEX ix_price_bars_u_id_tf_ts
    ON public.price_bars_multi_tf_u (id, tf, venue, "timestamp");


COMMIT;
