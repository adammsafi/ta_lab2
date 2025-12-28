WITH dates(d) AS (
  VALUES
    ('2025-01-15'::date),
    ('2025-03-07'::date),
    ('2025-03-10'::date),
    ('2025-07-15'::date),
    ('2025-10-31'::date),
    ('2025-11-03'::date)
)
SELECT
  d AS session_date,
  'America/New_York' AS tz,
  '09:30'::time AS open_local,
  (inst.open_utc AT TIME ZONE 'America/New_York')::time AS open_local_roundtrip,

  inst.open_utc AS open_ts_tz_display,

  -- Force a UTC "timestamp without tz" view:
  (inst.open_utc AT TIME ZONE 'UTC') AS open_utc_ts,

  -- Also show just the UTC time-of-day:
  (inst.open_utc AT TIME ZONE 'UTC')::time AS open_utc_time

FROM dates
CROSS JOIN LATERAL public.session_instants_for_date(
  d,
  'America/New_York',
  '09:30'::time,
  '16:00'::time,
  false
) inst
ORDER BY session_date;
