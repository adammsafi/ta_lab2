-- ============================
-- Returns on bar snapshots
-- ============================

CREATE TABLE IF NOT EXISTS public.cmc_returns_bars_multi_tf (
    id           integer NOT NULL,
    tf           text    NOT NULL,
    bar_seq      integer NOT NULL,
    time_close   timestamptz,
    close        double precision,
    prev_close   double precision,
    gap_bars     integer,
    ret_arith    double precision,
    ret_log      double precision,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cmc_returns_bars_multi_tf_pk PRIMARY KEY (id, tf, bar_seq)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_bars_multi_tf_time_close
ON public.cmc_returns_bars_multi_tf (id, tf, time_close);

-- State: watermark per (id, tf)
CREATE TABLE IF NOT EXISTS public.cmc_returns_bars_multi_tf_state (
    id            integer NOT NULL,
    tf            text    NOT NULL,
    last_bar_seq  integer,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cmc_returns_bars_multi_tf_state_pk PRIMARY KEY (id, tf)
);
