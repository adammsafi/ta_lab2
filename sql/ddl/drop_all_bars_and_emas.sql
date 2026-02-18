-- =====================================================
-- Drop All Bar and EMA Tables - Clean Slate Rebuild
-- =====================================================
-- WARNING: This will delete all bar and EMA data!
-- =====================================================

-- Drop Bar Tables (main + state + snapshots + backups)
DROP TABLE IF EXISTS public.cmc_price_bars_1d CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_1d_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_1d_rejects CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_1d_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_backup CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_iso CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_iso_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_iso_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_us CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_us_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_us_backup12 CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_us_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_iso CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_iso_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_us CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_us_state CASCADE;
DROP TABLE IF EXISTS public.cmc_price_bars_multi_tf_cal_anchor_us_snapshot_20260206_025653 CASCADE;

-- Drop EMA Tables (main + state + snapshots)
DROP TABLE IF EXISTS public.cmc_ema_daily CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_daily_20251124_snapshot CASCADE;

DROP TABLE IF EXISTS public.cmc_ema_multi_tf CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_state CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_20251124_snapshot CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_snapshot_20260206_025653 CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_20251124_snapshot CASCADE;

DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_iso CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_iso_state CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_iso_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_us CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_us_state CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_us_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_anchor_iso CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_anchor_iso_state CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_anchor_iso_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_anchor_us CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_anchor_us_state CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_cal_anchor_us_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_ema_multi_tf_v2 CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_v2_state CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_multi_tf_v2_snapshot_20260206_025653 CASCADE;

DROP TABLE IF EXISTS public.cmc_ema_multi_tf_u CASCADE;
DROP TABLE IF EXISTS public.cmc_ema_refresh_state CASCADE;

-- Drop EMA Stats Tables (stats + stats_state + snapshots)
DROP TABLE IF EXISTS public.ema_daily_stats CASCADE;
DROP TABLE IF EXISTS public.ema_daily_stats_20251124_snapshot CASCADE;

DROP TABLE IF EXISTS public.ema_multi_tf_stats CASCADE;
DROP TABLE IF EXISTS public.ema_multi_tf_stats_20251124_snapshot CASCADE;
DROP TABLE IF EXISTS public.ema_multi_tf_stats_state CASCADE;

DROP TABLE IF EXISTS public.ema_multi_tf_cal_stats CASCADE;
DROP TABLE IF EXISTS public.ema_multi_tf_cal_stats_state CASCADE;

DROP TABLE IF EXISTS public.ema_multi_tf_cal_anchor_stats CASCADE;
DROP TABLE IF EXISTS public.ema_multi_tf_cal_anchor_stats_state CASCADE;

DROP TABLE IF EXISTS public.ema_multi_tf_v2_stats CASCADE;
DROP TABLE IF EXISTS public.ema_multi_tf_v2_stats_state CASCADE;

-- Success message
SELECT 'All bar and EMA tables dropped successfully!' as status;
