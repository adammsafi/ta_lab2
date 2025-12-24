ALTER TABLE public.dim_timeframe
DROP CONSTRAINT IF EXISTS dim_timeframe_tf_naming_check;

ALTER TABLE public.dim_timeframe
ADD CONSTRAINT dim_timeframe_tf_naming_check
CHECK (
  -- tf_day: only D-form names
  (alignment_type = 'tf_day' AND tf ~ '^[0-9]+D$')

  OR
  -- calendar weeks: must declare scheme
  (alignment_type = 'calendar' AND base_unit = 'W'
    AND (
         tf ~ '^[0-9]+W_CAL_(US|ISO)$'
      OR tf ~ '^[0-9]+W_CAL_ANCHOR_(US|ISO)$'
    )
  )

  OR
  -- calendar months/quarters/years: scheme-agnostic
  (alignment_type = 'calendar' AND base_unit IN ('M','Q','Y')
    AND (
         tf ~ '^[0-9]+[MQY]_CAL$'
      OR tf ~ '^[0-9]+[MQY]_CAL_ANCHOR$'
    )
  )
);

ALTER TABLE public.dim_timeframe
DROP CONSTRAINT IF EXISTS dim_timeframe_calendar_scheme_consistency_check;

ALTER TABLE public.dim_timeframe
ADD CONSTRAINT dim_timeframe_calendar_scheme_consistency_check
CHECK (
  -- tf_day: never has scheme
  (alignment_type='tf_day' AND calendar_scheme IS NULL)

  OR
  -- calendar weeks: scheme required
  (alignment_type='calendar' AND base_unit='W' AND calendar_scheme IN ('US','ISO'))

  OR
  -- calendar M/Q/Y: scheme must be null (since month/quarter/year are universal)
  (alignment_type='calendar' AND base_unit IN ('M','Q','Y') AND calendar_scheme IS NULL)
);
