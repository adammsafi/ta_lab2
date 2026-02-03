-- Any non-canonical tfs used in cmc_ema_multi_tf?
SELECT DISTINCT e.tf
FROM cmc_ema_multi_tf e
LEFT JOIN dim_timeframe d USING (tf)
WHERE d.is_canonical IS DISTINCT FROM TRUE
ORDER BY e.tf;

-- Any non-canonical tfs used in cmc_ema_multi_tf_v2?
SELECT DISTINCT e.tf
FROM cmc_ema_multi_tf_v2 e
LEFT JOIN dim_timeframe d USING (tf)
WHERE d.is_canonical IS DISTINCT FROM TRUE
ORDER BY e.tf;

-- Any non-canonical tfs used in cmc_ema_multi_tf_cal?
SELECT DISTINCT e.tf
FROM cmc_ema_multi_tf_cal e
LEFT JOIN dim_timeframe d USING (tf)
WHERE d.is_canonical IS DISTINCT FROM TRUE
ORDER BY e.tf;

-- If you have cmc_ema_multi_tf_anchor or others:
SELECT DISTINCT e.tf
FROM cmc_ema_multi_tf_cal_anchor e
LEFT JOIN dim_timeframe d USING (tf)
WHERE d.is_canonical IS DISTINCT FROM TRUE
ORDER BY e.tf;

UPDATE dim_timeframe
SET is_canonical = true
WHERE tf = '15D';
