-- create_cmc_returns_ema_multi_tf_cal_unified.sql
--
-- Unified returns per scheme (US / ISO), includes BOTH:
--   series='ema'     (ema + roll)
--   series='ema_bar' (ema_bar + roll_bar mapped into roll)

BEGIN;

-- ============================================================
-- CAL US unified returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_us (
    id          bigint       NOT NULL,
    ts          timestamptz  NOT NULL,
    tf          text         NOT NULL,
    period      integer      NOT NULL,
    series      text         NOT NULL,   -- 'ema' | 'ema_bar'
    roll        boolean      NOT NULL,   -- for ema: roll; for ema_bar: roll_bar

    ema         double precision NOT NULL,
    prev_ema    double precision NOT NULL,
    gap_days    integer          NOT NULL,

    ret_arith   double precision NOT NULL,
    ret_log     double precision NOT NULL,

    ingested_at timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period, series, roll)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_us_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    series      text        NOT NULL,  -- 'ema' | 'ema_bar'
    roll        boolean     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period, series, roll)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_us_key
ON public.cmc_returns_ema_multi_tf_cal_us (id, tf, period, series, roll, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_us_ingested
ON public.cmc_returns_ema_multi_tf_cal_us (ingested_at);


-- ============================================================
-- CAL ISO unified returns + state
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_iso (
    id          bigint       NOT NULL,
    ts          timestamptz  NOT NULL,
    tf          text         NOT NULL,
    period      integer      NOT NULL,
    series      text         NOT NULL,   -- 'ema' | 'ema_bar'
    roll        boolean      NOT NULL,   -- for ema: roll; for ema_bar: roll_bar

    ema         double precision NOT NULL,
    prev_ema    double precision NOT NULL,
    gap_days    integer          NOT NULL,

    ret_arith   double precision NOT NULL,
    ret_log     double precision NOT NULL,

    ingested_at timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period, series, roll)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_cal_iso_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    series      text        NOT NULL,  -- 'ema' | 'ema_bar'
    roll        boolean     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period, series, roll)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_iso_key
ON public.cmc_returns_ema_multi_tf_cal_iso (id, tf, period, series, roll, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_cal_iso_ingested
ON public.cmc_returns_ema_multi_tf_cal_iso (ingested_at);

COMMIT;

-- ============================================================
-- CHECK constraints (idempotent) via DO blocks
-- ============================================================

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_ret_ema_cal_us_series'
  ) THEN
    ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us
      ADD CONSTRAINT ck_ret_ema_cal_us_series
      CHECK (series IN ('ema','ema_bar'));
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_ret_ema_cal_us_state_series'
  ) THEN
    ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us_state
      ADD CONSTRAINT ck_ret_ema_cal_us_state_series
      CHECK (series IN ('ema','ema_bar'));
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_ret_ema_cal_iso_series'
  ) THEN
    ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso
      ADD CONSTRAINT ck_ret_ema_cal_iso_series
      CHECK (series IN ('ema','ema_bar'));
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_ret_ema_cal_iso_state_series'
  ) THEN
    ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso_state
      ADD CONSTRAINT ck_ret_ema_cal_iso_state_series
      CHECK (series IN ('ema','ema_bar'));
  END IF;
END$$;
