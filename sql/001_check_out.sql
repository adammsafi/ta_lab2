WITH bounds AS (
    SELECT
        MIN("timestamp")::date AS min_date,
        MAX("timestamp")::date AS max_date
    FROM cmc_price_histories7
    WHERE id = 1975
),
calendar AS (
    SELECT generate_series(min_date, max_date, interval '1 day')::date AS d
    FROM bounds
)
SELECT c.d AS missing_date
FROM calendar c
LEFT JOIN cmc_price_histories7 p
  ON p.id = 1975
 AND p."timestamp"::date = c.d
WHERE p.id IS NULL
ORDER BY c.d;
