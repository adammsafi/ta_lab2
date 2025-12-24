DO $$
DECLARE
  src         text;
  schema_name text;
  tbl         text;
  fq_src      text;

  cols        text[];
  align_src   text;

  e_ingested_at text;
  e_d1          text;
  e_d2          text;
  e_tf_days     text;
  e_roll        text;
  e_d1_roll     text;
  e_d2_roll     text;

  e_ema_bar     text;
  e_d1_bar      text;
  e_d2_bar      text;
  e_roll_bar    text;
  e_d1_roll_bar text;
  e_d2_roll_bar text;

  sel text;
BEGIN
  TRUNCATE TABLE public.cmc_ema_multi_tf_u;

  FOREACH src IN ARRAY ARRAY[
    'public.cmc_ema_multi_tf',
    'public.cmc_ema_multi_tf_v2',
    'public.cmc_ema_multi_tf_cal_us',
    'public.cmc_ema_multi_tf_cal_iso',
    'public.cmc_ema_multi_tf_cal_anchor_us',
    'public.cmc_ema_multi_tf_cal_anchor_iso'
  ]
  LOOP
    schema_name := split_part(src, '.', 1);
    tbl         := split_part(src, '.', 2);
    fq_src      := format('%I.%I', schema_name, tbl);
    align_src   := regexp_replace(tbl, '^cmc_ema_', '');

    SELECT array_agg(column_name::text ORDER BY ordinal_position)
      INTO cols
    FROM information_schema.columns
    WHERE table_schema = schema_name
      AND table_name   = tbl;

    IF cols IS NULL THEN
      RAISE NOTICE 'SKIP (missing table): %', src;
      CONTINUE;
    END IF;

    IF NOT ('id' = ANY(cols) AND 'ts' = ANY(cols) AND 'tf' = ANY(cols) AND 'period' = ANY(cols) AND 'ema' = ANY(cols)) THEN
      RAISE EXCEPTION 'Source table % missing required columns: id, ts, tf, period, ema', src;
    END IF;

    -- required/optional expressions (no aliases, order will be controlled later)
    e_ingested_at := CASE WHEN 'ingested_at' = ANY(cols) THEN 'ingested_at' ELSE 'now()' END;

    e_d1      := CASE WHEN 'd1'      = ANY(cols) THEN 'd1::double precision'      ELSE 'NULL::double precision' END;
    e_d2      := CASE WHEN 'd2'      = ANY(cols) THEN 'd2::double precision'      ELSE 'NULL::double precision' END;
    e_tf_days := CASE WHEN 'tf_days' = ANY(cols) THEN 'tf_days::int'              ELSE 'NULL::int' END;

    e_roll    := CASE WHEN 'roll'    = ANY(cols) THEN 'COALESCE(roll,false)::boolean' ELSE 'false::boolean' END;
    e_d1_roll := CASE WHEN 'd1_roll' = ANY(cols) THEN 'd1_roll::double precision' ELSE 'NULL::double precision' END;
    e_d2_roll := CASE WHEN 'd2_roll' = ANY(cols) THEN 'd2_roll::double precision' ELSE 'NULL::double precision' END;

    e_ema_bar     := CASE WHEN 'ema_bar'     = ANY(cols) THEN 'ema_bar::double precision'     ELSE 'NULL::double precision' END;
    e_d1_bar      := CASE WHEN 'd1_bar'      = ANY(cols) THEN 'd1_bar::double precision'      ELSE 'NULL::double precision' END;
    e_d2_bar      := CASE WHEN 'd2_bar'      = ANY(cols) THEN 'd2_bar::double precision'      ELSE 'NULL::double precision' END;
    e_roll_bar    := CASE WHEN 'roll_bar'    = ANY(cols) THEN 'roll_bar::boolean'              ELSE 'NULL::boolean' END;
    e_d1_roll_bar := CASE WHEN 'd1_roll_bar' = ANY(cols) THEN 'd1_roll_bar::double precision' ELSE 'NULL::double precision' END;
    e_d2_roll_bar := CASE WHEN 'd2_roll_bar' = ANY(cols) THEN 'd2_roll_bar::double precision' ELSE 'NULL::double precision' END;

    -- Build SELECT in the EXACT order of the INSERT target columns
    sel := format(
      'SELECT id::int, ts, tf::text, period::int, ema::double precision, %s, %s, %s, %s, %s, %s, %s, %L::text, %s, %s, %s, %s, %s, %s FROM %s',
      e_ingested_at,
      e_d1,
      e_d2,
      e_tf_days,
      e_roll,
      e_d1_roll,
      e_d2_roll,
      align_src,
      e_ema_bar,
      e_d1_bar,
      e_d2_bar,
      e_roll_bar,
      e_d1_roll_bar,
      e_d2_roll_bar,
      fq_src
    );

    EXECUTE
      'INSERT INTO public.cmc_ema_multi_tf_u (
        id, ts, tf, period,
        ema, ingested_at, d1, d2, tf_days, roll, d1_roll, d2_roll,
        alignment_source,
        ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar
      ) ' || sel;

    RAISE NOTICE 'Loaded % as alignment_source=%', src, align_src;
  END LOOP;

  RAISE NOTICE 'Done. Total rows in _u: %', (SELECT COUNT(*) FROM public.cmc_ema_multi_tf_u);
END
$$;
