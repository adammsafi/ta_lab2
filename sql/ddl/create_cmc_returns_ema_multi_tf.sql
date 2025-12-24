-- create_cmc_returns_ema_multi_tf.sql
-- Creates:
--   public.cmc_returns_ema_multi_tf
--   public.cmc_returns_ema_multi_tf_state

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf (
    id          bigint       NOT NULL,
    ts          timestamptz  NOT NULL,
    tf          text         NOT NULL,
    period      integer      NOT NULL,
    roll        boolean      NOT NULL,

    ema         double precision NOT NULL,
    prev_ema    double precision NOT NULL,
    gap_days    integer          NOT NULL,

    ret_arith   double precision NOT NULL,
    ret_log     double precision NOT NULL,

    ingested_at timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, period, roll)
);

CREATE TABLE IF NOT EXISTS public.cmc_returns_ema_multi_tf_state (
    id          bigint      NOT NULL,
    tf          text        NOT NULL,
    period      integer     NOT NULL,
    roll        boolean     NOT NULL,
    last_ts     timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period, roll)
);

-- Helpful indexes (optional but recommended)
CREATE INDEX IF NOT EXISTS ix_cmc_returns_ema_multi_tf_key
ON public.cmc_returns_ema_multi_tf (id, tf, period, roll, ts);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_ema_multi_tf_ingested_at
ON public.cmc_returns_ema_multi_tf (ingested_at);

COMMIT;
