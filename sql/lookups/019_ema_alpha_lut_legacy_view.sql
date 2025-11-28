-- 019_ema_alpha_lut_legacy_view.sql
--
-- Backwards-compatible ema_alpha_lut view using the *old* semantics,
-- reconstructed from:
--   - dim_timeframe for TFs that exist there
--   - ema_alpha_lut_old directly for TFs that do NOT exist in dim_timeframe
--
-- Old convention:
--   alpha_bar       = 2 / (period + 1)
--   effective_days  = tf_days * period
--   alpha_daily_eq  = 1 - (1 - alpha_bar)^(1 / tf_days)

DROP VIEW IF EXISTS ema_alpha_lut;

CREATE VIEW ema_alpha_lut AS
WITH keyset AS (
    -- All (tf, period) combos that ever existed in the old table
    SELECT DISTINCT tf, period
    FROM ema_alpha_lut_old
),
keys_with_dim AS (
    -- Keys whose tf is modeled in dim_timeframe
    SELECT
        k.tf,
        k.period,
        t.tf_days_nominal
    FROM keyset k
    JOIN dim_timeframe t
      ON t.tf = k.tf
),
keys_without_dim AS (
    -- Keys whose tf is NOT modeled in dim_timeframe (e.g., 1M, 2M, ...)
    SELECT
        k.tf,
        k.period
    FROM keyset k
    LEFT JOIN dim_timeframe t
      ON t.tf = k.tf
    WHERE t.tf IS NULL
)

-- Branch 1: TFs that *are* in dim_timeframe → recreate old semantics from dims
SELECT
    w.tf,
    w.tf_days_nominal                                           AS tf_days,
    w.period,

    -- old per-bar alpha convention (bar-based)
    (2.0::double precision
       / (w.period::double precision + 1.0::double precision))  AS alpha_bar,

    -- effective_days = tf_days * period
    (w.tf_days_nominal * w.period)                              AS effective_days,

    -- old daily-equivalent alpha
    1.0::double precision
      - POWER(
          1.0::double precision
            - (2.0::double precision
                 / (w.period::double precision + 1.0::double precision)),
          1.0::double precision / w.tf_days_nominal::double precision
        )                                                       AS alpha_daily_eq

FROM keys_with_dim w

UNION ALL

-- Branch 2: TFs that are NOT in dim_timeframe → pull exact values from old table
SELECT
    o.tf,
    o.tf_days::double precision             AS tf_days,
    o.period,
    o.alpha_bar::double precision           AS alpha_bar,
    o.effective_days                        AS effective_days,
    o.alpha_daily_eq::double precision      AS alpha_daily_eq
FROM ema_alpha_lut_old o
JOIN keys_without_dim u
  ON u.tf = o.tf AND u.period = o.period;
