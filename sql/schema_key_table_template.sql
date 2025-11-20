SELECT
    c.column_name,
    c.data_type,
    c.is_nullable,
    c.column_default,
    CASE
        WHEN tc.constraint_type = 'PRIMARY KEY' THEN 'YES'
        ELSE 'NO'
    END AS is_primary_key
FROM information_schema.columns AS c
LEFT JOIN information_schema.key_column_usage AS k
    ON  c.table_name = k.table_name
    AND c.table_schema = k.table_schema
    AND c.column_name = k.column_name
LEFT JOIN information_schema.table_constraints AS tc
    ON  tc.constraint_name = k.constraint_name
    AND tc.table_schema   = k.table_schema
    AND tc.table_name     = k.table_name
    AND tc.constraint_type = 'PRIMARY KEY'
WHERE
    c.table_schema = 'public'
    AND c.table_name  = 'cmc_ema_daily'
ORDER BY
    c.ordinal_position;
