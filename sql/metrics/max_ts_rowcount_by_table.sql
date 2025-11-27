-- Purpose: Snapshot max(ts) and total row counts per table for core CMC data tables.
-- Tables:  cmc_price_histories7, cmc_ema_daily, cmc_ema_multi_tf, cmc_ema_multi_tf_cal
-- Usage:   \i sql/metrics/healthchecks/max_ts_rowcount_by_table.sql
-- Notes:   Used to confirm that all feature tables are in sync with price history
--          at a coarse, whole-table level.

-- 1) Raw price history (master)
SELECT
    'cmc_price_histories7' AS table_name,
    MAX("timestamp")       AS max_ts,
    COUNT(*)               AS row_count
FROM cmc_price_histories7

UNION ALL

-- 2) Daily EMAs
SELECT
    'cmc_ema_daily'        AS table_name,
    MAX(ts)                AS max_ts,
    COUNT(*)               AS row_count
FROM cmc_ema_daily

UNION ALL

-- 3) Multi-TF EMAs (price-timestamp aligned)
SELECT
    'cmc_ema_multi_tf'     AS table_name,
    MAX(ts)                AS max_ts,
    COUNT(*)               AS row_count
FROM cmc_ema_multi_tf

UNION ALL

-- 4) Multi-TF EMAs (calendar-aligned)
SELECT
    'cmc_ema_multi_tf_cal' AS table_name,
    MAX(ts)                AS max_ts,
    COUNT(*)               AS row_count
FROM cmc_ema_multi_tf_cal;
