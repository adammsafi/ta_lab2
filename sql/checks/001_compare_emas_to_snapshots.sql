-- 1) Daily EMAs: current vs snapshot
SELECT 'cmc_ema_daily'                    AS table_name, COUNT(*) AS n_rows
FROM   cmc_ema_daily
UNION ALL
SELECT 'cmc_ema_daily_20251124_snapshot', COUNT(*) AS n_rows
FROM   cmc_ema_daily_20251124_snapshot;


-- 2) Multi-TF EMAs: current vs snapshot
SELECT 'cmc_ema_multi_tf'                    AS table_name, COUNT(*) AS n_rows
FROM   cmc_ema_multi_tf
UNION ALL
SELECT 'cmc_ema_multi_tf_20251124_snapshot', COUNT(*) AS n_rows
FROM   cmc_ema_multi_tf_20251124_snapshot;


-- 3) Calendar Multi-TF EMAs: current vs snapshot
SELECT 'cmc_ema_multi_tf_cal'                    AS table_name, COUNT(*) AS n_rows
FROM   cmc_ema_multi_tf_cal
UNION ALL
SELECT 'cmc_ema_multi_tf_cal_20251124_snapshot', COUNT(*) AS n_rows
FROM   cmc_ema_multi_tf_cal_20251124_snapshot;