-- Migration: Redesign cmc_features as bar-level feature store
-- Removes EMA columns, adds full vol/TA/returns columns, renames legacy columns
-- Run once on live DB, then do a full refresh.

-- ═══════════════════════════════════════════════════════════════
-- 1. Drop removed EMA columns
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ema_9;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ema_10;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ema_21;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ema_50;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ema_200;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ema_9_d1;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ema_21_d1;

-- ═══════════════════════════════════════════════════════════════
-- 2. Drop renamed/removed legacy return columns
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ret_1_pct;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ret_1_log;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ret_1_pct_zscore;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ret_7_pct;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS ret_30_pct;
ALTER TABLE public.cmc_features DROP COLUMN IF EXISTS gap_days;

-- ═══════════════════════════════════════════════════════════════
-- 3. Add bar returns columns (46 columns)
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS gap_bars INTEGER;

-- Canonical columns
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta1 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta2 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS "range" DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS range_pct DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS true_range DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS true_range_pct DOUBLE PRECISION;

-- Roll columns
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta1_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta2_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS range_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS range_pct_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS true_range_roll DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS true_range_pct_roll DOUBLE PRECISION;

-- Z-scores: canonical, 30-day window
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith_zscore_30 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_30 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log_zscore_30 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_30 DOUBLE PRECISION;
-- Z-scores: roll, 30-day window
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_30 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_30 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_30 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_30 DOUBLE PRECISION;

-- Z-scores: canonical, 90-day window
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith_zscore_90 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_90 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log_zscore_90 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_90 DOUBLE PRECISION;
-- Z-scores: roll, 90-day window
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_90 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_90 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_90 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_90 DOUBLE PRECISION;

-- Z-scores: canonical, 365-day window
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith_zscore_365 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_365 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log_zscore_365 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_365 DOUBLE PRECISION;
-- Z-scores: roll, 365-day window
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_365 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_365 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_365 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_365 DOUBLE PRECISION;

-- Returns outlier flag
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ret_is_outlier BOOLEAN;

-- ═══════════════════════════════════════════════════════════════
-- 4. Add missing vol columns (existing: vol_parkinson_20, vol_gk_20,
--    vol_parkinson_20_zscore, atr_14)
-- ═══════════════════════════════════════════════════════════════

-- Parkinson 63, 126
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_parkinson_63 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_parkinson_126 DOUBLE PRECISION;

-- GK 63, 126
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_63 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_126 DOUBLE PRECISION;

-- RS 20, 63, 126
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_20 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_63 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_126 DOUBLE PRECISION;

-- Log roll 20, 63, 126
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_log_roll_20 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_log_roll_63 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_log_roll_126 DOUBLE PRECISION;

-- Vol z-scores (parkinson 63/126, gk all, rs all)
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_parkinson_63_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_parkinson_126_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_20_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_63_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_126_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_20_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_63_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_126_zscore DOUBLE PRECISION;

-- Vol outlier flags (all)
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_parkinson_20_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_parkinson_63_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_parkinson_126_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_20_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_63_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_gk_126_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_20_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_63_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_rs_126_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_log_roll_20_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_log_roll_63_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS vol_log_roll_126_is_outlier BOOLEAN DEFAULT FALSE;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS atr_14_is_outlier BOOLEAN DEFAULT FALSE;

-- ═══════════════════════════════════════════════════════════════
-- 5. Add missing TA columns
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS macd_8_17 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS macd_signal_9_fast DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS macd_hist_8_17_9 DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS rsi_14_zscore DOUBLE PRECISION;
ALTER TABLE public.cmc_features ADD COLUMN IF NOT EXISTS ta_is_outlier BOOLEAN DEFAULT FALSE;

-- ═══════════════════════════════════════════════════════════════
-- 6. Truncate existing data (will be fully refreshed)
-- ═══════════════════════════════════════════════════════════════
TRUNCATE TABLE public.cmc_features;
