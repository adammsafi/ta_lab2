TRUNCATE TABLE cmc_ema_multi_tf_u;

ALTER TABLE cmc_ema_multi_tf_u
    DROP CONSTRAINT IF EXISTS cmc_ema_multi_tf_u_pkey;

ALTER TABLE cmc_ema_multi_tf_u
    ADD PRIMARY KEY (id, ts, tf, period, alignment_source);
BEGIN;

-- 1) calendar (_cal)
INSERT INTO cmc_ema_multi_tf_u (
    id,
    ts,
    tf,
    period,
    ema,
    ingested_at,
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    alignment_source,
    ema_bar,
    d1_bar,
    d2_bar,
    roll_bar,
    d1_roll_bar,
    d2_roll_bar
)
SELECT
    id,
    ts,
    tf,
    period,
    ema,
    ingested_at,
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    'calendar'::text AS alignment_source,
    ema_bar,
    d1_bar,
    d2_bar,
    roll_bar,
    d1_roll_bar,
    d2_roll_bar
FROM cmc_ema_multi_tf_cal
ON CONFLICT (id, ts, tf, period, alignment_source) DO NOTHING;


-- 2) calendar_anchor (_cal_anchor)
INSERT INTO cmc_ema_multi_tf_u (
    id,
    ts,
    tf,
    period,
    ema,
    ingested_at,
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    alignment_source,
    ema_bar,
    d1_bar,
    d2_bar,
    roll_bar,
    d1_roll_bar,
    d2_roll_bar
)
SELECT
    id,
    ts,
    tf,
    period,
    ema,
    ingested_at,
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    'calendar_anchor'::text AS alignment_source,
    ema_bar,
    d1_bar,
    d2_bar,
    roll_bar,
    d1_roll_bar,
    d2_roll_bar
FROM cmc_ema_multi_tf_cal_anchor
ON CONFLICT (id, ts, tf, period, alignment_source) DO NOTHING;


-- 3) tf_day (legacy cmc_ema_multi_tf)
INSERT INTO cmc_ema_multi_tf_u (
    id,
    ts,
    tf,
    period,
    ema,
    ingested_at,
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    alignment_source,
    ema_bar,
    d1_bar,
    d2_bar,
    roll_bar,
    d1_roll_bar,
    d2_roll_bar
)
SELECT
    id,
    ts,
    tf,
    period,
    ema,
    now() AS ingested_at,  -- or use the table's ingested_at if it exists
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    'tf_day'::text AS alignment_source,
    NULL::double precision AS ema_bar,
    NULL::double precision AS d1_bar,
    NULL::double precision AS d2_bar,
    NULL::boolean          AS roll_bar,
    NULL::double precision AS d1_roll_bar,
    NULL::double precision AS d2_roll_bar
FROM cmc_ema_multi_tf
ON CONFLICT (id, ts, tf, period, alignment_source) DO NOTHING;


-- 4) v2_daily (cmc_ema_multi_tf_v2)
INSERT INTO cmc_ema_multi_tf_u (
    id,
    ts,
    tf,
    period,
    ema,
    ingested_at,
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    alignment_source,
    ema_bar,
    d1_bar,
    d2_bar,
    roll_bar,
    d1_roll_bar,
    d2_roll_bar
)
SELECT
    id,
    ts,
    tf,
    period,
    ema,
    ingested_at,
    d1,
    d2,
    tf_days,
    roll,
    d1_roll,
    d2_roll,
    'v2_daily'::text AS alignment_source,
    NULL::double precision AS ema_bar,
    NULL::double precision AS d1_bar,
    NULL::double precision AS d2_bar,
    NULL::boolean          AS roll_bar,
    NULL::double precision AS d1_roll_bar,
    NULL::double precision AS d2_roll_bar
FROM cmc_ema_multi_tf_v2
ON CONFLICT (id, ts, tf, period, alignment_source) DO NOTHING;

SELECT 'cal' AS src, COUNT(*) FROM cmc_ema_multi_tf_cal
UNION ALL
SELECT 'anchor', COUNT(*) FROM cmc_ema_multi_tf_cal_anchor
UNION ALL
SELECT 'tf_day', COUNT(*) FROM cmc_ema_multi_tf
UNION ALL
SELECT 'v2_daily', COUNT(*) FROM cmc_ema_multi_tf_v2
UNION ALL
SELECT 'u_total', COUNT(*) FROM cmc_ema_multi_tf_u;

SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;


s
