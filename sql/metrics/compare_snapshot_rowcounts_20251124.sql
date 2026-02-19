SELECT 'cmc_ema_multi_tf' AS table, COUNT(*) FROM cmc_ema_multi_tf
UNION ALL
SELECT 'cmc_ema_multi_tf_20251124_snapshot', COUNT(*) FROM cmc_ema_multi_tf_20251124_snapshot;

SELECT 'cmc_ema_multi_tf_cal' AS table, COUNT(*) FROM cmc_ema_multi_tf_cal
UNION ALL
SELECT 'cmc_ema_multi_tf_cal_20251124_snapshot', COUNT(*) FROM cmc_ema_multi_tf_cal_20251124_snapshot;


SELECT 'ema_multi_tf_stats' AS table, COUNT(*) FROM ema_multi_tf_stats
UNION ALL
SELECT 'ema_multi_tf_stats_20251124_snapshot', COUNT(*) FROM ema_multi_tf_stats_20251124_snapshot;


SELECT 'ema_multi_tf_cal_stats' AS table, COUNT(*) FROM ema_multi_tf_cal_stats
UNION ALL
SELECT 'ema_multi_tf_cal_stats_20251124_snapshot', COUNT(*) FROM ema_multi_tf_cal_stats_20251124_snapshot;
