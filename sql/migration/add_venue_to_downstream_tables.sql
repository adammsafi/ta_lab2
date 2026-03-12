-- Migration: Add venue to all downstream table PKs
-- Adds venue TEXT NOT NULL DEFAULT 'CMC_AGG' and venue_rank INTEGER NOT NULL DEFAULT 50
-- to returns, EMA, and feature tables.

BEGIN;

-- ============================================================================
-- A. BAR RETURNS TABLES (5 base + 1 unified = 6)
-- ============================================================================

-- 1. returns_bars_multi_tf: PK (id, "timestamp", tf) -> (id, "timestamp", tf, venue)
ALTER TABLE public.returns_bars_multi_tf
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_bars_multi_tf DROP CONSTRAINT returns_bars_multi_tf_pkey;
ALTER TABLE public.returns_bars_multi_tf ADD PRIMARY KEY (id, "timestamp", tf, venue);

-- 2. returns_bars_multi_tf_cal_us
ALTER TABLE public.returns_bars_multi_tf_cal_us
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_bars_multi_tf_cal_us DROP CONSTRAINT returns_bars_multi_tf_cal_us_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_us ADD PRIMARY KEY (id, "timestamp", tf, venue);

-- 3. returns_bars_multi_tf_cal_iso
ALTER TABLE public.returns_bars_multi_tf_cal_iso
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_bars_multi_tf_cal_iso DROP CONSTRAINT returns_bars_multi_tf_cal_iso_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_iso ADD PRIMARY KEY (id, "timestamp", tf, venue);

-- 4. returns_bars_multi_tf_cal_anchor_us
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_us
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_us DROP CONSTRAINT returns_bars_multi_tf_cal_anchor_us_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_us ADD PRIMARY KEY (id, "timestamp", tf, venue);

-- 5. returns_bars_multi_tf_cal_anchor_iso
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_iso
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_iso DROP CONSTRAINT returns_bars_multi_tf_cal_anchor_iso_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_iso ADD PRIMARY KEY (id, "timestamp", tf, venue);

-- 6. returns_bars_multi_tf_u (unified): PK adds venue before alignment_source
ALTER TABLE public.returns_bars_multi_tf_u
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_bars_multi_tf_u DROP CONSTRAINT returns_bars_multi_tf_u_pkey;
ALTER TABLE public.returns_bars_multi_tf_u ADD PRIMARY KEY (id, "timestamp", tf, venue, alignment_source);

-- ============================================================================
-- B. BAR RETURNS STATE TABLES (5 base + 1 unified = 6)
-- ============================================================================

ALTER TABLE public.returns_bars_multi_tf_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.returns_bars_multi_tf_state DROP CONSTRAINT IF EXISTS returns_bars_multi_tf_state_pkey;
ALTER TABLE public.returns_bars_multi_tf_state ADD PRIMARY KEY (id, tf, venue);

ALTER TABLE public.returns_bars_multi_tf_cal_us_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.returns_bars_multi_tf_cal_us_state DROP CONSTRAINT IF EXISTS returns_bars_multi_tf_cal_us_state_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_us_state ADD PRIMARY KEY (id, tf, venue);

ALTER TABLE public.returns_bars_multi_tf_cal_iso_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.returns_bars_multi_tf_cal_iso_state DROP CONSTRAINT IF EXISTS returns_bars_multi_tf_cal_iso_state_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_iso_state ADD PRIMARY KEY (id, tf, venue);

ALTER TABLE public.returns_bars_multi_tf_cal_anchor_us_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_us_state DROP CONSTRAINT IF EXISTS returns_bars_multi_tf_cal_anchor_us_state_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_us_state ADD PRIMARY KEY (id, tf, venue);

ALTER TABLE public.returns_bars_multi_tf_cal_anchor_iso_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_iso_state DROP CONSTRAINT IF EXISTS returns_bars_multi_tf_cal_anchor_iso_state_pkey;
ALTER TABLE public.returns_bars_multi_tf_cal_anchor_iso_state ADD PRIMARY KEY (id, tf, venue);

-- ============================================================================
-- C. EMA RETURNS TABLES (5 base + 1 unified = 6)
-- ============================================================================

-- returns_ema_multi_tf: PK (id, ts, tf, period) -> (id, ts, tf, period, venue)
ALTER TABLE public.returns_ema_multi_tf
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_ema_multi_tf DROP CONSTRAINT returns_ema_multi_tf_pkey;
ALTER TABLE public.returns_ema_multi_tf ADD PRIMARY KEY (id, ts, tf, period, venue);

-- returns_ema_multi_tf_cal_us
ALTER TABLE public.returns_ema_multi_tf_cal_us
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_ema_multi_tf_cal_us DROP CONSTRAINT returns_ema_multi_tf_cal_us_pkey;
ALTER TABLE public.returns_ema_multi_tf_cal_us ADD PRIMARY KEY (id, ts, tf, period, venue);

-- returns_ema_multi_tf_cal_iso
ALTER TABLE public.returns_ema_multi_tf_cal_iso
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_ema_multi_tf_cal_iso DROP CONSTRAINT returns_ema_multi_tf_cal_iso_pkey;
ALTER TABLE public.returns_ema_multi_tf_cal_iso ADD PRIMARY KEY (id, ts, tf, period, venue);

-- returns_ema_multi_tf_cal_anchor_us
ALTER TABLE public.returns_ema_multi_tf_cal_anchor_us
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_ema_multi_tf_cal_anchor_us DROP CONSTRAINT returns_ema_multi_tf_cal_anchor_us_pkey;
ALTER TABLE public.returns_ema_multi_tf_cal_anchor_us ADD PRIMARY KEY (id, ts, tf, period, venue);

-- returns_ema_multi_tf_cal_anchor_iso
ALTER TABLE public.returns_ema_multi_tf_cal_anchor_iso
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_ema_multi_tf_cal_anchor_iso DROP CONSTRAINT returns_ema_multi_tf_cal_anchor_iso_pkey;
ALTER TABLE public.returns_ema_multi_tf_cal_anchor_iso ADD PRIMARY KEY (id, ts, tf, period, venue);

-- returns_ema_multi_tf_u (unified)
ALTER TABLE public.returns_ema_multi_tf_u
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.returns_ema_multi_tf_u DROP CONSTRAINT returns_ema_multi_tf_u_pkey;
ALTER TABLE public.returns_ema_multi_tf_u ADD PRIMARY KEY (id, ts, tf, period, venue, alignment_source);

-- EMA RETURNS STATE TABLES
ALTER TABLE public.returns_ema_multi_tf_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.returns_ema_multi_tf_state DROP CONSTRAINT IF EXISTS returns_ema_multi_tf_state_pkey;
ALTER TABLE public.returns_ema_multi_tf_state ADD PRIMARY KEY (id, tf, period, venue);

-- ============================================================================
-- D. EMA VALUE TABLES (1 unified + 2 calendar)
-- ============================================================================

-- ema_multi_tf_u: PK (id, ts, tf, period) -> (id, ts, tf, period, venue)
ALTER TABLE public.ema_multi_tf_u
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.ema_multi_tf_u DROP CONSTRAINT ema_multi_tf_u_pkey;
ALTER TABLE public.ema_multi_tf_u ADD PRIMARY KEY (id, ts, tf, period, venue);

-- ema_multi_tf_cal_us
ALTER TABLE public.ema_multi_tf_cal_us
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.ema_multi_tf_cal_us DROP CONSTRAINT ema_multi_tf_cal_us_pkey;
ALTER TABLE public.ema_multi_tf_cal_us ADD PRIMARY KEY (id, tf, ts, period, venue);

-- ema_multi_tf_cal_iso
ALTER TABLE public.ema_multi_tf_cal_iso
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.ema_multi_tf_cal_iso DROP CONSTRAINT ema_multi_tf_cal_iso_pkey;
ALTER TABLE public.ema_multi_tf_cal_iso ADD PRIMARY KEY (id, tf, ts, period, venue);

-- EMA REFRESH STATE
ALTER TABLE public.cmc_ema_refresh_state
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG';
ALTER TABLE public.cmc_ema_refresh_state DROP CONSTRAINT IF EXISTS cmc_ema_refresh_state_pkey;
ALTER TABLE public.cmc_ema_refresh_state ADD PRIMARY KEY (id, tf, period, venue);

-- ============================================================================
-- E. FEATURE TABLES
-- ============================================================================

-- features: PK (id, ts, tf, alignment_source) -> (id, ts, tf, venue, alignment_source)
ALTER TABLE public.features
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.features DROP CONSTRAINT features_pkey;
ALTER TABLE public.features ADD PRIMARY KEY (id, ts, tf, venue, alignment_source);

-- vol_daily: PK (id, ts) -> (id, ts, venue)
ALTER TABLE public.vol_daily
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.vol_daily DROP CONSTRAINT vol_daily_pkey;
ALTER TABLE public.vol_daily ADD PRIMARY KEY (id, ts, venue);

-- ta_daily: PK (id, ts) -> (id, ts, venue)
ALTER TABLE public.ta_daily
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
ALTER TABLE public.ta_daily DROP CONSTRAINT ta_daily_pkey;
ALTER TABLE public.ta_daily ADD PRIMARY KEY (id, ts, venue);

COMMIT;
