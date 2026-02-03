SELECT
    'current' AS version,
    id,
    period,
    COUNT(*) AS n_rows
FROM cmc_ema_daily
GROUP BY id, period

UNION ALL

SELECT
    'snapshot' AS version,
    id,
    period,
    COUNT(*) AS n_rows
FROM cmc_ema_daily_20251124_snapshot
GROUP BY id, period
ORDER BY id, period, version;
