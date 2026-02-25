-- Migration: Add venue + venue_rank to multi-TF feature tables
-- Extends Phase 43 venue integration to cmc_vol, cmc_ta,
-- cmc_cycle_stats, and cmc_rolling_extremes.
--
-- Companion to: add_venue_to_downstream_tables.sql (which covers
-- returns, EMA, cmc_features, cmc_vol_daily, cmc_ta_daily)

ALTER TABLE public.cmc_vol
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

ALTER TABLE public.cmc_ta
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

ALTER TABLE public.cmc_cycle_stats
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;

ALTER TABLE public.cmc_rolling_extremes
  ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'CMC_AGG',
  ADD COLUMN IF NOT EXISTS venue_rank INTEGER NOT NULL DEFAULT 50;
