/* ============================================================
   Find duplicate indexes (same table, same keys, same uniqueness)
   Run this once; it will show duplicates to consider dropping.
   ============================================================ */

WITH idx AS (
  SELECT
    t.relname AS tablename,
    i.relname AS indexname,
    ix.indisunique,
    ix.indisprimary,
    pg_get_indexdef(ix.indexrelid) AS indexdef,
    -- normalized key signature: list of indexed columns/expressions
    (
      SELECT string_agg(pg_get_indexdef(ix.indexrelid, k + 1, true), ', ' ORDER BY k)
      FROM generate_subscripts(ix.indkey, 1) AS s(k)
    ) AS key_sig
  FROM pg_index ix
  JOIN pg_class i ON i.oid = ix.indexrelid
  JOIN pg_class t ON t.oid = ix.indrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  WHERE n.nspname = 'public'
    AND t.relname IN (
      'cmc_price_bars_multi_tf_cal_us',
      'cmc_price_bars_multi_tf_cal_iso',
      'cmc_price_bars_multi_tf_cal_anchor_us',
      'cmc_price_bars_multi_tf_cal_anchor_iso'
    )
)
SELECT
  tablename,
  key_sig,
  indisunique,
  COUNT(*) AS n_indexes,
  string_agg(indexname, ', ' ORDER BY indexname) AS indexes
FROM idx
GROUP BY tablename, key_sig, indisunique
HAVING COUNT(*) > 1
ORDER BY tablename, n_indexes DESC, key_sig;
