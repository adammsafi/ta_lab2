-- Migration: Add microstructure columns to features
-- Date: 2026-02-28
-- Purpose: Schema foundation for Phase 59 (Microstructural & Advanced Features)
--
-- Adds 9 columns to public.features for downstream feature computation:
--   MICRO-01 (Fractional Differencing): close_fracdiff, close_fracdiff_d
--   MICRO-02 (Market Microstructure Lambdas): kyle_lambda, amihud_lambda, hasbrouck_lambda
--   MICRO-03 (Structural Breaks / SADF): sadf_stat, sadf_is_explosive
--   MICRO-04 (Entropy Features): entropy_shannon, entropy_lz
--
-- Idempotent: safe to re-run (ADD COLUMN IF NOT EXISTS).
-- No UTF-8 box-drawing characters (Windows cp1252 safety).

-- ---------------------------------------------------------------
-- MICRO-01: Fractional Differencing
-- ---------------------------------------------------------------
ALTER TABLE public.features
    ADD COLUMN IF NOT EXISTS close_fracdiff   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS close_fracdiff_d DOUBLE PRECISION;

-- ---------------------------------------------------------------
-- MICRO-02: Market Microstructure Lambdas (Price Impact)
-- ---------------------------------------------------------------
ALTER TABLE public.features
    ADD COLUMN IF NOT EXISTS kyle_lambda      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS amihud_lambda    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hasbrouck_lambda DOUBLE PRECISION;

-- ---------------------------------------------------------------
-- MICRO-03: Structural Breaks (SADF)
-- ---------------------------------------------------------------
ALTER TABLE public.features
    ADD COLUMN IF NOT EXISTS sadf_stat         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS sadf_is_explosive BOOLEAN DEFAULT FALSE;

-- ---------------------------------------------------------------
-- MICRO-04: Entropy Features
-- ---------------------------------------------------------------
ALTER TABLE public.features
    ADD COLUMN IF NOT EXISTS entropy_shannon DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entropy_lz      DOUBLE PRECISION;
