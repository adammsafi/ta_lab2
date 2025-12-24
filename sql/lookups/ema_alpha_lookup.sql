BEGIN;

-- 0) Drop old lookup
DROP TABLE IF EXISTS public.ema_alpha_lookup;

-- 1) Recreate
CREATE TABLE public.ema_alpha_lookup (
  tf                   text    NOT NULL,
  period               integer NOT NULL,
  tf_days_nominal      integer NOT NULL,

  -- For ema (daily-space): horizon is period * tf_days_nominal
  alpha_ema_dailyspace double precision NOT NULL,

  -- For ema_bar (bar-space canonical): period is in bars, independent of tf_days
  alpha_bar            double precision NOT NULL,

  -- For ema_bar daily preview: composes over tf_days_nominal to equal alpha_bar per bar
  alpha_bar_preview_daily double precision NOT NULL,

  created_at           timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ema_alpha_lookup_pk PRIMARY KEY (tf, period),
  CONSTRAINT ema_alpha_lookup_period_gt0 CHECK (period > 0),
  CONSTRAINT ema_alpha_lookup_tf_days_gt0 CHECK (tf_days_nominal > 0),
  CONSTRAINT ema_alpha_lookup_alpha_bounds CHECK (
    alpha_ema_dailyspace > 0 AND alpha_ema_dailyspace <= 1
    AND alpha_bar > 0 AND alpha_bar <= 1
    AND alpha_bar_preview_daily > 0 AND alpha_bar_preview_daily <= 1
  )
);

-- 2) Insert from dim_timeframe x periods
INSERT INTO public.ema_alpha_lookup (
  tf, period, tf_days_nominal,
  alpha_ema_dailyspace,
  alpha_bar,
  alpha_bar_preview_daily
)
SELECT
  dt.tf,
  p.period,
  dt.tf_days_nominal,

  -- ema daily-space alpha: 2 / (period * tf_days + 1)
  (2.0 / ((p.period * dt.tf_days_nominal)::double precision + 1.0)) AS alpha_ema_dailyspace,

  -- ema_bar bar-space alpha: 2 / (period + 1)
  (2.0 / (p.period::double precision + 1.0)) AS alpha_bar,

  -- preview alpha: 1 - (1 - alpha_bar)^(1/tf_days)
  (
    1.0 - POWER(
      (1.0 - (2.0 / (p.period::double precision + 1.0))),
      (1.0 / dt.tf_days_nominal::double precision)
    )
  ) AS alpha_bar_preview_daily

FROM public.dim_timeframe dt
CROSS JOIN (
  VALUES
    (6), (9), (10), (12), (14), (17), (20), (21),
    (26), (30), (50), (52), (77), (100), (200),
    (252), (365)
) AS p(period)

WHERE dt.is_intraday = FALSE;

-- 3) Helpful indexes (optional)
CREATE INDEX IF NOT EXISTS ema_alpha_lookup_period_idx
  ON public.ema_alpha_lookup (period);

CREATE INDEX IF NOT EXISTS ema_alpha_lookup_tf_days_idx
  ON public.ema_alpha_lookup (tf_days_nominal);

-- 4) display_order passthrough from dim_timeframe
ALTER TABLE public.ema_alpha_lookup
  ADD COLUMN IF NOT EXISTS display_order integer;

UPDATE public.ema_alpha_lookup e
SET display_order = d.display_order
FROM public.dim_timeframe d
WHERE e.tf = d.tf;

COMMIT;
