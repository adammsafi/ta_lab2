-- Get a view's "schema" (its columns)
SELECT
    c.column_name,
    c.data_type,
    c.is_nullable,
    c.column_default
FROM information_schema.columns AS c
JOIN information_schema.views AS v
  ON  c.table_schema = v.table_schema
  AND c.table_name   = v.table_name
WHERE c.table_schema = 'public'        -- change if needed
  AND c.table_name   = 'all_emas'  -- put your view name here
ORDER BY c.ordinal_position;
