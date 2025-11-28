-- 017_ema_alpha_lookup.sql
--
-- Normalized EMA alpha lookup built from:
--   - dim_timeframe (tf_days_nominal)
--   - dim_period (period)
--
-- This is intended to coexist with the older ema_alpha_lut table.
-- Later you can migrate code to use this as the source of truth.

BEGIN;

-- ======================================================
-- 1. Create table
-- ======================================================

CREATE TABLE IF NOT EXISTS ema_alpha_lookup (
    tf              text    NOT NULL REFERENCES dim_timeframe(tf),
    period          integer NOT NULL REFERENCES dim_period(period),

    -- Nominal days per bar for this timeframe (from dim_timeframe)
    tf_days         integer NOT NULL,

    -- Total effective days for this EMA (tf_days * period)
    effective_days  integer NOT NULL,

    -- Alpha applied per TF bar
    alpha_bar       double precision NOT NULL,

    -- Daily-equivalent alpha (same time constant as effective_days)
    alpha_daily_eq  double precision NOT NULL,

    PRIMARY KEY (tf, period)
);

-- Optional: index to help lookups by tf_days / effective_days if needed
CREATE INDEX IF NOT EXISTS idx_ema_alpha_lookup_tf_days
    ON ema_alpha_lookup (tf_days, period);

CREATE INDEX IF NOT EXISTS idx_ema_alpha_lookup_effective_days
    ON ema_alpha_lookup (effective_days);

-- ======================================================
-- 2. Populate table from dim_timeframe × dim_period
-- ======================================================
--
-- Definitions:
--   tf_days        = t.tf_days_nominal
--   effective_days = tf_days * period
--
-- "Daily-equivalent" alpha is the alpha you would use on
-- daily bars to get the same effective time constant:
--
--   alpha_daily_eq = 2 / (effective_days + 1)
--
-- "Per-bar" alpha is the alpha applied on the TF bars
-- (e.g., weekly, monthly), such that compounding those
-- bars matches the daily-equivalent decay:
--
--   alpha_bar = 1 - (1 - alpha_daily_eq) ^ tf_days
--
-- This matches the usual equivalence:
--   (1 - alpha_daily_eq) ^ effective_days
-- = (1 - alpha_bar) ^ period

INSERT INTO ema_alpha_lookup (
    tf,
    period,
    tf_days,
    effective_days,
    alpha_bar,
    alpha_daily_eq
)
SELECT
    t.tf,
    p.period,
    t.tf_days_nominal                AS tf_days,
    t.tf_days_nominal * p.period     AS effective_days,
    -- per-bar alpha
    1.0 - POWER(
        1.0 - (2.0 / (t.tf_days_nominal * p.period + 1.0)),
        t.tf_days_nominal
    )                                AS alpha_bar,
    -- daily-equivalent alpha
    2.0 / (t.tf_days_nominal * p.period + 1.0)
                                     AS alpha_daily_eq
FROM dim_timeframe t
CROSS JOIN dim_period p
ON CONFLICT (tf, period) DO UPDATE
SET
    tf_days        = EXCLUDED.tf_days,
    effective_days = EXCLUDED.effective_days,
    alpha_bar      = EXCLUDED.alpha_bar,
    alpha_daily_eq = EXCLUDED.alpha_daily_eq;

COMMIT;
