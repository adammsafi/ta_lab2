SELECT tf
FROM (
    SELECT DISTINCT m.tf
    FROM cmc_ema_multi_tf AS m
    WHERE NOT EXISTS (
        SELECT 1 FROM dim_timeframe d WHERE d.tf = m.tf
    )

    UNION

    SELECT DISTINCT c.tf
    FROM cmc_ema_multi_tf_cal AS c
    WHERE NOT EXISTS (
        SELECT 1 FROM dim_timeframe d WHERE d.tf = c.tf
    )

    UNION

    SELECT DISTINCT a.tf
    FROM cmc_ema_multi_tf_cal_anchor AS a
    WHERE NOT EXISTS (
        SELECT 1 FROM dim_timeframe d WHERE d.tf = a.tf
    )
) AS missing_tfs
ORDER BY tf;
