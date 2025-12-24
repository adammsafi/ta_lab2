-- create_cmc_returns_ema_multi_tf_u.sql
-- Unified EMA returns built from public.cmc_ema_multi_tf_u
--
-- Keyed by:
--   (id, ts, tf, period, alignment_source, series, roll)
--
-- series in ('ema','ema_bar')
-- roll meaning:
--   series='ema'     => source roll
--   series='ema_bar' => source roll_bar (aliased to roll)
--
-- State keyed by:
--   (id, tf, period, alignment_source, series, roll) -> last_ts

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_u (
    id               bigint NOT NULL,
    ts               timestamptz NOT NULL,
    tf               text NOT NULL,
    period           integer NOT NULL,
    alignment_source text NOT NULL,
    series           text NOT NULL,      -- 'ema' or 'ema_bar'
    roll             boolean NOT NULL,

    ema              double precision NOT NULL,
    prev_ema         double precision NOT NULL,
    gap_days         integer NOT NULL,

    ret_arith        double precision NOT NULL,
    ret_log          double precision NOT NULL,

    ingested_at      timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period, alignment_source, series, roll)
);

CREATE INDEX IF NOT EXISTS ix_ret_ema_u_key_ts
ON public.cmc_returns_ema_multi_tf_u (id, tf, period, alignment_source, series, roll, ts);

CREATE INDEX IF NOT EXISTS ix_ret_ema_u_tf_period
ON public.cmc_returns_ema_multi_tf_u (tf, period);

CREATE INDEX IF NOT EXISTS ix_ret_ema_u_alignment_source
ON public.cmc_returns_ema_multi_tf_u (alignment_source);

-- Add a CHECK constraint for series safely (works even if table already existed)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_ret_ema_u_series'
  ) THEN
    ALTER TABLE public.cmc_returns_ema_multi_tf_u
      ADD CONSTRAINT ck_ret_ema_u_series
      CHECK (series IN ('ema','ema_bar'));
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_u_state (
    id               bigint NOT NULL,
    tf               text NOT NULL,
    period           integer NOT NULL,
    alignment_source text NOT NULL,
    series           text NOT NULL,
    roll             boolean NOT NULL,
    last_ts          timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, tf, period, alignment_source, series, roll)
);

-- Add a CHECK constraint for series on the state table safely
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_ret_ema_u_state_series'
  ) THEN
    ALTER TABLE public.cmc_returns_ema_multi_tf_u_state
      ADD CONSTRAINT ck_ret_ema_u_state_series
      CHECK (series IN ('ema','ema_bar'));
  END IF;
END$$;

COMMIT;
