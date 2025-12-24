/* ============================================================
   Clean DDL extractor: table columns + constraints (no dupes)
   Change params.relname per table.
   ============================================================ */

WITH params AS (
  SELECT 'cmc_price_bars_multi_tf_cal_us'::text AS relname   -- <-- change me
),
t AS (
  SELECT c.oid, n.nspname, c.relname
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN params p ON p.relname = c.relname
  WHERE n.nspname = 'public'
),
cols AS (
  SELECT
    t.oid,
    string_agg(
      '  ' || a.attname || ' ' || pg_catalog.format_type(a.atttypid, a.atttypmod) ||
      CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END ||
      CASE
        WHEN ad.adbin IS NOT NULL THEN ' DEFAULT ' || pg_get_expr(ad.adbin, ad.adrelid)
        ELSE ''
      END,
      E',\n'
      ORDER BY a.attnum
    ) AS cols_ddl
  FROM t
  JOIN pg_attribute a ON a.attrelid = t.oid
  LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
  WHERE a.attnum > 0
    AND NOT a.attisdropped
  GROUP BY t.oid
),
cons AS (
  SELECT
    t.oid,
    COALESCE(
      string_agg(
        'ALTER TABLE public.' || t.relname || ' ADD CONSTRAINT ' || c.conname || ' ' ||
        pg_get_constraintdef(c.oid) || ';',
        E'\n'
        ORDER BY c.contype, c.conname
      ),
      ''
    ) AS cons_ddl
  FROM t
  LEFT JOIN pg_constraint c ON c.conrelid = t.oid
  WHERE c.contype IN ('p','u','c','f')
  GROUP BY t.oid, t.relname
)
SELECT
  'CREATE TABLE public.' || t.relname || ' (' || E'\n' ||
  cols.cols_ddl ||
  E'\n);\n\n' ||
  cons.cons_ddl AS ddl
FROM t
JOIN cols ON cols.oid = t.oid
LEFT JOIN cons ON cons.oid = t.oid;


/* ============================================================
   Index DDL extractor
   Change params.tablename per table.
   ============================================================ */

WITH params AS (
  SELECT 'cmc_price_bars_multi_tf_cal_us'::text AS tablename   -- <-- change me
)
SELECT indexdef || ';' AS ddl
FROM pg_indexes
JOIN params p ON p.tablename = pg_indexes.tablename
WHERE schemaname = 'public'
ORDER BY indexname;
