---Get a table's schema

SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'       -- change if needed
  AND table_name   = 'ema_multi_tf_stats'   -- <- put table name here
ORDER BY ordinal_position;