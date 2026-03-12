-- Migration: Add venue + venue_rank to multi-TF feature tables
-- Extends Phase 43 venue integration to vol, ta,
-- cycle_stats, and rolling_extremes.
--
-- Companion to: add_venue_to_downstream_tables.sql (which covers
-- returns, EMA, features, vol_daily, ta_daily)

ALTER TABLE public.vol
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

ALTER TABLE public.ta
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

ALTER TABLE public.cycle_stats
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

ALTER TABLE public.rolling_extremes
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
