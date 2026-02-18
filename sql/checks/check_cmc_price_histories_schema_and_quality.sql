SELECT
  column_name,
  data_type,
  is_nullable,
  column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name   = 'cmc_price_histories7'
ORDER BY ordinal_position;

SELECT
  ordinal_position,
  column_name,
  data_type,
  udt_name,
  is_nullable,
  numeric_precision,
  numeric_scale,
  datetime_precision
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name   = 'cmc_price_histories7'
ORDER BY ordinal_position;

SELECT
  SUM((column_name = 'id')::int)        AS has_id,
  SUM((column_name = 'time_close')::int) AS has_time_close,
  SUM((column_name = 'close')::int)     AS has_close
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name   = 'cmc_price_histories7';

SELECT
  COUNT(*) AS n_rows,
  SUM((timeclose IS NULL)::int) AS n_timeclose_null,
  MIN(COALESCE(timeclose, "timestamp")) AS min_time_close,
  MAX(COALESCE(timeclose, "timestamp")) AS max_time_close
FROM public.cmc_price_histories7;
