/* ============================================================
   TA_LAB2 "GATE" — Canonical integrity checks (single query)
   - Returns ONLY failures. 0 rows == PASS.
   - n_bad = total duplicate rows beyond first (sum(cnt-1))
   ============================================================ */

WITH
/* --------------------------
   BARS: canonical duplicates
   canonical := is_partial_end = FALSE
   key := (id, tf, time_close)
   -------------------------- */
bars_canon_dupes AS (
  SELECT
      x.table_name,
      'bars_canonical_duplicate_close' AS test_name,
      SUM(x.cnt - 1)::bigint AS n_bad,
      MIN(x.example_key) AS example_key
  FROM (
      SELECT
          t.table_name,
          (t.id::text || '|' || t.tf || '|' || t.time_close::text) AS example_key,
          COUNT(*)::bigint AS cnt
      FROM (
          SELECT 'public.cmc_price_bars_multi_tf' AS table_name, id, tf, time_close
          FROM public.cmc_price_bars_multi_tf
          WHERE is_partial_end = FALSE

          UNION ALL
          SELECT 'public.cmc_price_bars_multi_tf_cal_us', id, tf, time_close
          FROM public.cmc_price_bars_multi_tf_cal_us
          WHERE is_partial_end = FALSE

          UNION ALL
          SELECT 'public.cmc_price_bars_multi_tf_cal_iso', id, tf, time_close
          FROM public.cmc_price_bars_multi_tf_cal_iso
          WHERE is_partial_end = FALSE

          UNION ALL
          SELECT 'public.cmc_price_bars_multi_tf_cal_anchor_us', id, tf, time_close
          FROM public.cmc_price_bars_multi_tf_cal_anchor_us
          WHERE is_partial_end = FALSE

          UNION ALL
          SELECT 'public.cmc_price_bars_multi_tf_cal_anchor_iso', id, tf, time_close
          FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
          WHERE is_partial_end = FALSE
      ) t
      GROUP BY t.table_name, t.id, t.tf, t.time_close
      HAVING COUNT(*) > 1
  ) x
  GROUP BY x.table_name
),

bars_canon_null_close AS (
  SELECT
      t.table_name,
      'bars_canonical_null_time_close' AS test_name,
      COUNT(*)::bigint AS n_bad,
      MIN((t.id::text || '|' || t.tf)) AS example_key
  FROM (
      SELECT 'public.cmc_price_bars_multi_tf' AS table_name, id, tf, time_close
      FROM public.cmc_price_bars_multi_tf
      WHERE is_partial_end = FALSE

      UNION ALL
      SELECT 'public.cmc_price_bars_multi_tf_cal_us', id, tf, time_close
      FROM public.cmc_price_bars_multi_tf_cal_us
      WHERE is_partial_end = FALSE

      UNION ALL
      SELECT 'public.cmc_price_bars_multi_tf_cal_iso', id, tf, time_close
      FROM public.cmc_price_bars_multi_tf_cal_iso
      WHERE is_partial_end = FALSE

      UNION ALL
      SELECT 'public.cmc_price_bars_multi_tf_cal_anchor_us', id, tf, time_close
      FROM public.cmc_price_bars_multi_tf_cal_anchor_us
      WHERE is_partial_end = FALSE

      UNION ALL
      SELECT 'public.cmc_price_bars_multi_tf_cal_anchor_iso', id, tf, time_close
      FROM public.cmc_price_bars_multi_tf_cal_anchor_iso
      WHERE is_partial_end = FALSE
  ) t
  WHERE t.time_close IS NULL
  GROUP BY t.table_name
),

/* --------------------------
   EMA tables: canonical duplicates
   canonical := roll = FALSE
   key (non-u) := (id, tf, period, ts)
   key (u)     := (id, tf, period, ts, alignment_source)
   -------------------------- */
ema_canon_dupes_non_u AS (
  SELECT
      x.table_name,
      'ema_canonical_duplicate_ts' AS test_name,
      SUM(x.cnt - 1)::bigint AS n_bad,
      MIN(x.example_key) AS example_key
  FROM (
      SELECT
          t.table_name,
          (t.id::text || '|' || t.tf || '|' || t.period::text || '|' || t.ts::text) AS example_key,
          COUNT(*)::bigint AS cnt
      FROM (
          SELECT 'public.cmc_ema_multi_tf' AS table_name, id, tf, period, ts
          FROM public.cmc_ema_multi_tf
          WHERE roll = FALSE

          UNION ALL
          SELECT 'public.cmc_ema_multi_tf_v2', id, tf, period, ts
          FROM public.cmc_ema_multi_tf_v2
          WHERE roll = FALSE

          UNION ALL
          SELECT 'public.cmc_ema_multi_tf_cal_us', id, tf, period, ts
          FROM public.cmc_ema_multi_tf_cal_us
          WHERE roll = FALSE

          UNION ALL
          SELECT 'public.cmc_ema_multi_tf_cal_iso', id, tf, period, ts
          FROM public.cmc_ema_multi_tf_cal_iso
          WHERE roll = FALSE

          UNION ALL
          SELECT 'public.cmc_ema_multi_tf_cal_anchor_us', id, tf, period, ts
          FROM public.cmc_ema_multi_tf_cal_anchor_us
          WHERE roll = FALSE

          UNION ALL
          SELECT 'public.cmc_ema_multi_tf_cal_anchor_iso', id, tf, period, ts
          FROM public.cmc_ema_multi_tf_cal_anchor_iso
          WHERE roll = FALSE
      ) t
      GROUP BY t.table_name, t.id, t.tf, t.period, t.ts
      HAVING COUNT(*) > 1
  ) x
  GROUP BY x.table_name
),

ema_canon_dupes_u AS (
  SELECT
      x.table_name,
      'ema_u_canonical_duplicate_ts' AS test_name,
      SUM(x.cnt - 1)::bigint AS n_bad,
      MIN(x.example_key) AS example_key
  FROM (
      SELECT
          'public.cmc_ema_multi_tf_u' AS table_name,
          (id::text || '|' || tf || '|' || period::text || '|' || ts::text || '|' || alignment_source) AS example_key,
          COUNT(*)::bigint AS cnt
      FROM public.cmc_ema_multi_tf_u
      WHERE roll = FALSE
      GROUP BY id, tf, period, ts, alignment_source
      HAVING COUNT(*) > 1
  ) x
  GROUP BY x.table_name
),

/* --------------------------
   RETURNS (bars): duplicates
   key := (id, tf, time_close)
   -------------------------- */
ret_bars_dupes AS (
  SELECT
      x.table_name,
      'returns_bars_duplicate_time_close' AS test_name,
      SUM(x.cnt - 1)::bigint AS n_bad,
      MIN(x.example_key) AS example_key
  FROM (
      SELECT
          t.table_name,
          (t.id::text || '|' || t.tf || '|' || t.time_close::text) AS example_key,
          COUNT(*)::bigint AS cnt
      FROM (
          SELECT 'public.cmc_returns_bars_multi_tf' AS table_name, id, tf, time_close
          FROM public.cmc_returns_bars_multi_tf

          UNION ALL
          SELECT 'public.cmc_returns_bars_multi_tf_cal_us', id, tf, time_close
          FROM public.cmc_returns_bars_multi_tf_cal_us

          UNION ALL
          SELECT 'public.cmc_returns_bars_multi_tf_cal_iso', id, tf, time_close
          FROM public.cmc_returns_bars_multi_tf_cal_iso

          UNION ALL
          SELECT 'public.cmc_returns_bars_multi_tf_cal_anchor_us', id, tf, time_close
          FROM public.cmc_returns_bars_multi_tf_cal_anchor_us

          UNION ALL
          SELECT 'public.cmc_returns_bars_multi_tf_cal_anchor_iso', id, tf, time_close
          FROM public.cmc_returns_bars_multi_tf_cal_anchor_iso
      ) t
      GROUP BY t.table_name, t.id, t.tf, t.time_close
      HAVING COUNT(*) > 1
  ) x
  GROUP BY x.table_name
),

/* --------------------------
   RETURNS (ema) — NO series tables
   key := (id, tf, period, roll, ts)
   -------------------------- */
ret_ema_dupes_no_series AS (
  SELECT
      x.table_name,
      'returns_ema_duplicate_key' AS test_name,
      SUM(x.cnt - 1)::bigint AS n_bad,
      MIN(x.example_key) AS example_key
  FROM (
      SELECT
          t.table_name,
          (t.id::text || '|' || t.tf || '|' || t.period::text || '|' || t.roll::text || '|' || t.ts::text) AS example_key,
          COUNT(*)::bigint AS cnt
      FROM (
          SELECT 'public.cmc_returns_ema_multi_tf' AS table_name, id, tf, period, roll, ts
          FROM public.cmc_returns_ema_multi_tf

          UNION ALL
          SELECT 'public.cmc_returns_ema_multi_tf_v2', id, tf, period, roll, ts
          FROM public.cmc_returns_ema_multi_tf_v2
      ) t
      GROUP BY t.table_name, t.id, t.tf, t.period, t.roll, t.ts
      HAVING COUNT(*) > 1
  ) x
  GROUP BY x.table_name
),

/* --------------------------
   RETURNS (ema) — WITH series tables
   key := (id, tf, period, roll, ts, series)
   -------------------------- */
ret_ema_dupes_with_series AS (
  SELECT
      x.table_name,
      'returns_ema_duplicate_key' AS test_name,
      SUM(x.cnt - 1)::bigint AS n_bad,
      MIN(x.example_key) AS example_key
  FROM (
      SELECT
          t.table_name,
          (t.id::text || '|' || t.tf || '|' || t.period::text || '|' || t.roll::text || '|' || t.ts::text || '|' || t.series) AS example_key,
          COUNT(*)::bigint AS cnt
      FROM (
          SELECT 'public.cmc_returns_ema_multi_tf_cal_us' AS table_name, id, tf, period, roll, ts, series
          FROM public.cmc_returns_ema_multi_tf_cal_us

          UNION ALL
          SELECT 'public.cmc_returns_ema_multi_tf_cal_iso', id, tf, period, roll, ts, series
          FROM public.cmc_returns_ema_multi_tf_cal_iso

          UNION ALL
          SELECT 'public.cmc_returns_ema_multi_tf_cal_anchor_us', id, tf, period, roll, ts, series
          FROM public.cmc_returns_ema_multi_tf_cal_anchor_us

          UNION ALL
          SELECT 'public.cmc_returns_ema_multi_tf_cal_anchor_iso', id, tf, period, roll, ts, series
          FROM public.cmc_returns_ema_multi_tf_cal_anchor_iso
      ) t
      GROUP BY t.table_name, t.id, t.tf, t.period, t.roll, t.ts, t.series
      HAVING COUNT(*) > 1
  ) x
  GROUP BY x.table_name
),

/* --------------------------
   RETURNS (ema_u): duplicates
   key := (id, tf, period, alignment_source, series, roll, ts)
   -------------------------- */
ret_ema_u_dupes AS (
  SELECT
      x.table_name,
      'returns_ema_u_duplicate_key' AS test_name,
      SUM(x.cnt - 1)::bigint AS n_bad,
      MIN(x.example_key) AS example_key
  FROM (
      SELECT
          'public.cmc_returns_ema_multi_tf_u' AS table_name,
          (id::text || '|' || tf || '|' || period::text || '|' || alignment_source || '|' || series || '|' || roll::text || '|' || ts::text) AS example_key,
          COUNT(*)::bigint AS cnt
      FROM public.cmc_returns_ema_multi_tf_u
      GROUP BY id, tf, period, alignment_source, series, roll, ts
      HAVING COUNT(*) > 1
  ) x
  GROUP BY x.table_name
)

SELECT table_name, test_name, n_bad, example_key
FROM (
    SELECT * FROM bars_canon_dupes
    UNION ALL
    SELECT * FROM bars_canon_null_close
    UNION ALL
    SELECT * FROM ema_canon_dupes_non_u
    UNION ALL
    SELECT * FROM ema_canon_dupes_u
    UNION ALL
    SELECT * FROM ret_bars_dupes
    UNION ALL
    SELECT * FROM ret_ema_dupes_no_series
    UNION ALL
    SELECT * FROM ret_ema_dupes_with_series
    UNION ALL
    SELECT * FROM ret_ema_u_dupes
) failures
WHERE n_bad > 0
ORDER BY table_name, test_name;
