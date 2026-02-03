-- 1) From cmc_ema_multi_tf_cal  → alignment_source = 'calendar'
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
FROM cmc_ema_multi_tf_cal;


-- 2) From cmc_ema_multi_tf_cal_anchor  → alignment_source = 'calendar_anchor'
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
FROM cmc_ema_multi_tf_cal_anchor;


-- 3) From cmc_ema_multi_tf (v1 tf-day engine)  → alignment_source = 'tf_day'
-- This table does NOT necessarily have ingested_at or bar columns,
-- so we synthesize ingested_at and set bar fields to NULL.
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
    now() AS ingested_at,
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
FROM cmc_ema_multi_tf;


-- 4) From cmc_ema_multi_tf_v2 (pure daily engine) → alignment_source = 'v2_daily'
-- Has ingested_at, but no bar-space EMA, so bar fields are NULL.
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
FROM cmc_ema_multi_tf_v2;

SELECT
    id,
    ts,
    tf,
    period,
    COUNT(*) AS n
FROM cmc_ema_multi_tf_cal
GROUP BY id, ts, tf, period
HAVING COUNT(*) > 1
ORDER BY n DESC, id, ts, tf, period;
