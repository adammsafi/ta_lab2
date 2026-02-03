-- 1) Where am I?
SELECT current_database() AS db, current_user AS role, current_schema() AS schema;
SHOW search_path;

-- 2) Do I have a foreign table named fred_series_values anywhere?
SELECT n.nspname AS schema_name, c.relname AS foreign_table_name
FROM pg_foreign_table ft
JOIN pg_class        c ON c.oid = ft.ftrelid
JOIN pg_namespace    n ON n.oid = c.relnamespace
WHERE c.relname = 'fred_series_values';

-- 3) List ALL foreign tables (to eyeball names/schemas)
SELECT n.nspname AS schema_name, c.relname AS foreign_table_name
FROM pg_foreign_table ft
JOIN pg_class        c ON c.oid = ft.ftrelid
JOIN pg_namespace    n ON n.oid = c.relnamespace
ORDER BY 1,2;

-- 4) Sanity check: does any regular (non-foreign) table with that name exist?
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name = 'fred_series_values';

-- 5) Do I have privileges to read it?
SELECT
  has_schema_privilege(current_user, 'public', 'USAGE') AS public_usage,
  has_table_privilege(current_user, 'public.fred_series_values', 'SELECT') AS can_select_public_fred_series_values;
