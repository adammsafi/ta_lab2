-- Purpose: Snapshot max(ts) and row counts per (id, table) for core CMC data tables.
-- Tables:  cmc_price_histories7, cmc_ema_multi_tf, cmc_ema_multi_tf_cal
-- Usage:   \i sql/metrics/healthchecks/max_ts_rowcount_by_id_by_table.sql
-- Notes:   Used to verify per-asset coverage and detect gaps or drift between
--          price history and feature tables for specific ids.

-- Price Histories by asset
SELECT
    id,
    MAX(timestamp)    AS max_ts,
    COUNT(*)     AS row_count
FROM cmc_price_histories7
GROUP BY id
ORDER BY id;

-- Multi-TF EMAs by asset (price-timestamp aligned)
SELECT
    id,
    MAX(ts)      AS max_ts,
    COUNT(*)     AS row_count
FROM cmc_ema_multi_tf
GROUP BY id
ORDER BY id;

-- Multi-TF EMAs by asset (calendar-aligned)
SELECT
    id,
    MAX(ts)      AS max_ts,
    COUNT(*)     AS row_count
FROM cmc_ema_multi_tf_cal
GROUP BY id
ORDER BY id;
