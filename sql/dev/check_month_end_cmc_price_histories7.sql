SELECT *
FROM cmc_price_histories7
WHERE id = 1
  AND "timestamp"::date = (
    date_trunc('month', "timestamp")::date
    + INTERVAL '1 month - 1 day'
  )::date
ORDER BY "timestamp";

SELECT *
FROM cmc_price_histories7
WHERE id = 1
  -- start at first canonical 6M endpoint
  AND "timestamp"::date >= DATE '2011-12-31'
  -- ensure it's the last calendar day of its month
  AND "timestamp"::date = (
        date_trunc('month', "timestamp")::date
        + INTERVAL '1 month - 1 day'
      )::date
  -- restrict to June and December (6M cadence)
  AND EXTRACT(MONTH FROM "timestamp") IN (6, 12)
ORDER BY "timestamp";

select 