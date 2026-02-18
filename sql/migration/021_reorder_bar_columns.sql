-- Migration 021: Reorder bar table columns
-- Strategy: DROP + recreate via builder auto-DDL (new column order in common_snapshot_contract.py)
-- Run builders with --full-rebuild after this migration.

-- Drop all 6 bar tables (data will be rebuilt)
DROP TABLE IF EXISTS public.cmc_price_bars_1d CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_us CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_iso CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_us CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_iso CASCADE;

-- Also drop state tables so builders start fresh
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_us_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_iso_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_us_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_iso_state CASCADE;
