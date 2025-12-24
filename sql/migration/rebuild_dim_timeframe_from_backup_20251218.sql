DO $$
DECLARE
  b regclass;
BEGIN
  -- 1) Prefer an expected backup name if it exists
  b := to_regclass('public.dim_timeframe_backup_20251218');

  -- 2) Otherwise, pick the newest dim_timeframe_backup_% table
  IF b IS NULL THEN
    SELECT to_regclass(format('public.%I', tablename))
    INTO b
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename LIKE 'dim_timeframe_backup_%'
    ORDER BY tablename DESC
    LIMIT 1;
  END IF;

  IF b IS NULL THEN
    RAISE EXCEPTION 'No backup table found (expected public.dim_timeframe_backup_20251218 or public.dim_timeframe_backup_%%).';
  END IF;

  -- 3) Insert transformed rows
  EXECUTE format($SQL$
    INSERT INTO public.dim_timeframe (
      tf, label, base_unit, tf_qty, tf_days_nominal,
      alignment_type, calendar_anchor, roll_policy,
      has_roll_flag, is_intraday, sort_order, description,
      is_canonical, calendar_scheme,
      allow_partial_start, allow_partial_end,
      tf_days_min, tf_days_max
    )
    WITH src AS (
      SELECT *
      FROM %s
      WHERE NOT (
        alignment_type = 'tf_day'
        AND tf IN ('1W','2W','3W','4W','6W','8W','10W')
      )
    ),
    x AS (
      SELECT
        -- TF renames
        CASE
          WHEN tf IN ('1W_CAL','2W_CAL','3W_CAL','4W_CAL','6W_CAL','8W_CAL','10W_CAL')
            THEN replace(tf, '_CAL', '_CAL_US')

          WHEN tf ~ '^[0-9]+W_ISO$'
            THEN replace(tf, '_ISO', '_CAL_ISO')

          WHEN tf ~ '^[0-9]+W_US_ANCHOR$'
            THEN replace(tf, '_US_ANCHOR', '_CAL_ANCHOR_US')

          WHEN tf ~ '^[0-9]+W_ISO_ANCHOR$'
            THEN replace(tf, '_ISO_ANCHOR', '_CAL_ANCHOR_ISO')

          ELSE tf
        END AS tf,

        label,
        base_unit,
        tf_qty,
        tf_days_nominal,
        alignment_type,

        -- Anchor fix for legacy *_W_CAL rows (make them explicit US week end)
        CASE
          WHEN tf IN ('1W_CAL','2W_CAL','3W_CAL','4W_CAL','6W_CAL','8W_CAL','10W_CAL')
            THEN 'WEEK_END'
          ELSE calendar_anchor
        END AS calendar_anchor,

        roll_policy,
        has_roll_flag,
        is_intraday,
        sort_order,
        description,
        is_canonical,

        -- calendar_scheme normalization + explicit scheme for week variants
        CASE
          WHEN calendar_scheme = 'CAL' THEN NULL
          WHEN tf IN ('1W_CAL','2W_CAL','3W_CAL','4W_CAL','6W_CAL','8W_CAL','10W_CAL')
            THEN 'US'
          WHEN tf ~ '^[0-9]+W_ISO$'
            THEN 'ISO'
          WHEN tf ~ '^[0-9]+W_US_ANCHOR$'
            THEN 'US'
          WHEN tf ~ '^[0-9]+W_ISO_ANCHOR$'
            THEN 'ISO'
          ELSE calendar_scheme
        END AS calendar_scheme,

        -- anchored week rows: force partials + min/max
        CASE
          WHEN tf ~ '^[0-9]+W_(US|ISO)_ANCHOR$' THEN TRUE
          ELSE allow_partial_start
        END AS allow_partial_start,

        CASE
          WHEN tf ~ '^[0-9]+W_(US|ISO)_ANCHOR$' THEN TRUE
          ELSE allow_partial_end
        END AS allow_partial_end,

        CASE
          WHEN tf ~ '^[0-9]+W_(US|ISO)_ANCHOR$' THEN 1
          ELSE tf_days_min
        END AS tf_days_min,

        CASE
          WHEN tf ~ '^[0-9]+W_(US|ISO)_ANCHOR$' THEN tf_days_nominal
          ELSE tf_days_max
        END AS tf_days_max

      FROM src
    )
    SELECT
      tf, label, base_unit, tf_qty, tf_days_nominal,
      alignment_type, calendar_anchor, roll_policy,
      has_roll_flag, is_intraday, sort_order, description,
      is_canonical, calendar_scheme,
      allow_partial_start, allow_partial_end,
      tf_days_min, tf_days_max
    FROM x
    ;
  $SQL$, b);

  RAISE NOTICE 'Inserted into public.dim_timeframe from backup table: %', b;
END $$;
