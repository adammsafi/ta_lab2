-- 1) Lookup table of alphas per (tf, tf_days, period)
CREATE TABLE IF NOT EXISTS public.ema_alpha_lut (
    tf              text            NOT NULL,
    tf_days         integer         NOT NULL,
    period          integer         NOT NULL,   -- EMA period in TF bars
    alpha_bar       double precision NOT NULL,  -- EMA alpha on TF closes
    effective_days  integer         NOT NULL,   -- period * tf_days
    alpha_daily_eq  double precision,           -- optional: daily alpha with same time constant
    PRIMARY KEY (tf, period)
);

-- 2) Populate from your TF set and default periods
WITH tfs(tf, tf_days) AS (
    VALUES
      ('1D', 1),
      ('2D', 2),
      ('3D', 3),
      ('4D', 4),
      ('5D', 5),
      ('10D', 10),
      ('15D', 15),
      ('20D', 20),
      ('25D', 25),
      ('45D', 45),
      ('100D', 100),
      ('1W', 7),
      ('2W', 14),
      ('3W', 21),
      ('4W', 28),
      ('6W', 42),
      ('8W', 56),
      ('10W', 70),
      ('1M', 30),
      ('2M', 60),
      ('3M', 90),
      ('6M', 180),
      ('9M', 270),
      ('12M', 360)
),
periods(period) AS (
    VALUES
      (10),
      (21),
      (50),
      (100),
      (200)
)
INSERT INTO public.ema_alpha_lut (tf, tf_days, period, alpha_bar, effective_days, alpha_daily_eq)
SELECT
    t.tf,
    t.tf_days,
    p.period,
    2.0 / (p.period + 1.0)                                     AS alpha_bar,
    p.period * t.tf_days                                       AS effective_days,
    1.0 - POWER(1.0 - (2.0 / (p.period + 1.0)), 1.0 / t.tf_days) AS alpha_daily_eq
FROM tfs t
CROSS JOIN periods p
ON CONFLICT (tf, period) DO UPDATE
SET
    tf_days        = EXCLUDED.tf_days,
    alpha_bar      = EXCLUDED.alpha_bar,
    effective_days = EXCLUDED.effective_days,
    alpha_daily_eq = EXCLUDED.alpha_daily_eq;
