-- 020_dim_timeframe_sanity.sql
--
-- Run this to sanity check dim_timeframe in one shot.
-- Returns a table of tests with PASS/FAIL and diagnostics.

WITH
-- Basic counts and aggregates
meta AS (
    SELECT
        COUNT(*) AS total_rows,
        COUNT(*) FILTER (WHERE alignment_type = 'tf_day')      AS tf_day_rows,
        COUNT(*) FILTER (WHERE alignment_type = 'calendar')    AS calendar_rows,
        COUNT(DISTINCT tf)                                     AS distinct_tf,
        COUNT(DISTINCT sort_order)                             AS distinct_sort_order,
        COUNT(*) FILTER (WHERE alignment_type = 'tf_day'
                         AND tf LIKE '%D')                     AS pure_daily_rows,
        COUNT(*) FILTER (WHERE alignment_type = 'tf_day'
                         AND tf LIKE '%W')                     AS weekly_tf_day_rows
    FROM dim_timeframe
),
dup_tf AS (
    SELECT
        COUNT(*) - COUNT(DISTINCT tf) AS dup_count
    FROM dim_timeframe
),
dup_sort AS (
    SELECT
        COUNT(*) - COUNT(DISTINCT sort_order) AS dup_count
    FROM dim_timeframe
),
bad_calendar_anchor_for_calendar AS (
    SELECT COUNT(*) AS bad_count
    FROM dim_timeframe
    WHERE alignment_type = 'calendar'
      AND calendar_anchor IS NULL
),
bad_calendar_anchor_for_tf_day AS (
    SELECT COUNT(*) AS bad_count
    FROM dim_timeframe
    WHERE alignment_type = 'tf_day'
      AND calendar_anchor IS NOT NULL
),
bad_roll_for_cal AS (
    SELECT COUNT(*) AS bad_count
    FROM dim_timeframe
    WHERE tf LIKE '%_CAL'
      AND roll_policy <> 'calendar_anchor'
),
bad_anchor_for_cal AS (
    SELECT COUNT(*) AS bad_count
    FROM dim_timeframe
    WHERE tf LIKE '%_CAL'
      AND calendar_anchor IS NULL
),
sort_monotonic_violations AS (
    SELECT COUNT(*) AS bad_count
    FROM (
        SELECT
            sort_order,
            LAG(sort_order) OVER (ORDER BY sort_order) AS prev_sort
        FROM dim_timeframe
    ) t
    WHERE prev_sort IS NOT NULL
      AND sort_order <= prev_sort
),
tests AS (
    -- 1. Total row count
    SELECT
        'total_rows'::text AS test_name,
        CASE WHEN m.total_rows = 138 THEN 'PASS' ELSE 'FAIL' END AS status,
        m.total_rows::text AS actual,
        'expected 138 rows in dim_timeframe'::text AS expected_or_note
    FROM meta m

    UNION ALL

    -- 2. Pure daily horizons (tf LIKE '%D'), should be 98
    SELECT
        'pure_daily_row_count' AS test_name,
        CASE WHEN m.pure_daily_rows = 98 THEN 'PASS' ELSE 'FAIL' END AS status,
        m.pure_daily_rows::text AS actual,
        'expected 98 pure daily horizons (tf LIKE ''%D'')' AS expected_or_note
    FROM meta m

    UNION ALL

    -- 3. Weekly tf_day aliases (1W,2W,3W,4W,6W,8W,10W), should be 7
    SELECT
        'weekly_tf_day_row_count' AS test_name,
        CASE WHEN m.weekly_tf_day_rows = 7 THEN 'PASS' ELSE 'FAIL' END AS status,
        m.weekly_tf_day_rows::text AS actual,
        'expected 7 weekly tf_day aliases (tf LIKE ''%W'')' AS expected_or_note
    FROM meta m

    UNION ALL

    -- 4. tf_day row count informational (pure_daily + weekly_tf_day)
    SELECT
        'tf_day_row_count' AS test_name,
        'PASS' AS status,
        m.tf_day_rows::text AS actual,
        'tf_day_rows (informational) = pure_daily_rows + weekly_tf_day_rows' AS expected_or_note
    FROM meta m

    UNION ALL

    -- 5. calendar row count informational
    SELECT
        'calendar_row_count' AS test_name,
        CASE WHEN m.calendar_rows = (m.total_rows - m.tf_day_rows) THEN 'PASS' ELSE 'WARN' END AS status,
        m.calendar_rows::text AS actual,
        'calendar_rows = total_rows - tf_day_rows (informational)' AS expected_or_note
    FROM meta m

    UNION ALL

    -- 6. no duplicate tf
    SELECT
        'distinct_tf' AS test_name,
        CASE WHEN m.total_rows = m.distinct_tf THEN 'PASS' ELSE 'FAIL' END AS status,
        m.distinct_tf::text AS actual,
        'distinct tf must equal total_rows (no duplicates)' AS expected_or_note
    FROM meta m

    UNION ALL

    -- 7. no duplicate sort_order
    SELECT
        'distinct_sort_order' AS test_name,
        CASE WHEN m.total_rows = m.distinct_sort_order THEN 'PASS' ELSE 'FAIL' END AS status,
        m.distinct_sort_order::text AS actual,
        'distinct sort_order must equal total_rows (no duplicates)' AS expected_or_note
    FROM meta m

    UNION ALL

    -- 8. duplicates in tf (should be 0)
    SELECT
        'duplicate_tf_count' AS test_name,
        CASE WHEN d.dup_count = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        d.dup_count::text AS actual,
        'number of duplicate tf rows (should be 0)' AS expected_or_note
    FROM dup_tf d

    UNION ALL

    -- 9. duplicates in sort_order (should be 0)
    SELECT
        'duplicate_sort_order_count' AS test_name,
        CASE WHEN d.dup_count = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        d.dup_count::text AS actual,
        'number of duplicate sort_order values (should be 0)' AS expected_or_note
    FROM dup_sort d

    UNION ALL

    -- 10. calendar frames must have non-null calendar_anchor
    SELECT
        'calendar_alignment_anchor_not_null' AS test_name,
        CASE WHEN b.bad_count = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        b.bad_count::text AS actual,
        'calendar rows with NULL calendar_anchor (should be 0)' AS expected_or_note
    FROM bad_calendar_anchor_for_calendar b

    UNION ALL

    -- 11. tf_day frames must have NULL calendar_anchor
    SELECT
        'tf_day_alignment_anchor_null' AS test_name,
        CASE WHEN b.bad_count = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        b.bad_count::text AS actual,
        'tf_day rows with non-NULL calendar_anchor (should be 0)' AS expected_or_note
    FROM bad_calendar_anchor_for_tf_day b

    UNION ALL

    -- 12. *_CAL frames must use roll_policy = calendar_anchor
    SELECT
        'cal_frames_roll_policy' AS test_name,
        CASE WHEN b.bad_count = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        b.bad_count::text AS actual,
        '*_CAL rows with roll_policy <> calendar_anchor (should be 0)' AS expected_or_note
    FROM bad_roll_for_cal b

    UNION ALL

    -- 13. *_CAL frames must have non-null calendar_anchor
    SELECT
        'cal_frames_anchor_not_null' AS test_name,
        CASE WHEN b.bad_count = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        b.bad_count::text AS actual,
        '*_CAL rows with NULL calendar_anchor (should be 0)' AS expected_or_note
    FROM bad_anchor_for_cal b

    UNION ALL

    -- 14. sort_order must be strictly increasing
    SELECT
        'sort_order_strictly_increasing' AS test_name,
        CASE WHEN s.bad_count = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
        s.bad_count::text AS actual,
        'rows where sort_order <= previous sort_order (should be 0)' AS expected_or_note
    FROM sort_monotonic_violations s
)

SELECT *
FROM tests
ORDER BY test_name;
