SELECT 'old_multi' AS src, COUNT(*) FROM cmc_ema_multi_tf
UNION ALL
SELECT 'old_cal'  AS src, COUNT(*) FROM cmc_ema_multi_tf_cal
UNION ALL
SELECT 'unified'  AS src, COUNT(*) FROM cmc_ema_multi_tf_u;

SELECT alignment_source, COUNT(*)
FROM cmc_ema_multi_tf_u
GROUP BY alignment_source
ORDER BY alignment_source;

select * fro
