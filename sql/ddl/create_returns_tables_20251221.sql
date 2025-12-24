-- 20251221_create_returns_tables.sql
-- Creates return tables + state tables:
--   1) cmc_returns_d1 (+ state)
--   2) cmc_bar_returns (+ state)
--   3) cmc_ema_returns (+ state)  <-- includes ema_bar returns columns

BEGIN;

-- ============================================================
-- 1) DAILY RETURNS (from public.cmc_price_histories7)
--    Grain: (id, time_close)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.cmc_returns_d1 (
    id           integer NOT NULL,
    time_close   timestamp with time zone NOT NULL,

    close        double precision,
    prev_close   double precision,

    gap_days     integer,                 -- days between prev close and this close (observed-to-observed)

    ret_arith    double precision,        -- (close/prev_close) - 1
    ret_log      double precision,        -- ln(close/prev_close)

    ingested_at  timestamp with time zone NOT NULL DEFAULT now(),

    CONSTRAINT cmc_returns_d1_pkey PRIMARY KEY (id, time_close)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_d1_id_timeclose
ON public.cmc_returns_d1 (id, time_close);


CREATE TABLE IF NOT EXISTS public.cmc_returns_d1_state (
    id              integer NOT NULL,
    last_time_close timestamp with time zone,
    updated_at      timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT cmc_returns_d1_state_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_cmc_returns_d1_state_last_timeclose
ON public.cmc_returns_d1_state (last_time_close);



-- ============================================================
-- 2) BAR RETURNS (from bar tables)
--    Grain: (id, bar_family, tf, bar_seq)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.cmc_bar_returns (
    id            integer NOT NULL,
    bar_family    text    NOT NULL,        -- 'multi_tf','cal_us','cal_iso','cal_anchor_us','cal_anchor_iso'
    tf            text    NOT NULL,
    bar_seq       integer NOT NULL,

    time_close    timestamp with time zone NOT NULL,

    close         double precision,
    prev_close    double precision,

    ret_arith     double precision,
    ret_log       double precision,

    is_partial_end boolean,                -- mirror from bars if desired; returns usually computed only when FALSE

    ingested_at   timestamp with time zone NOT NULL DEFAULT now(),

    CONSTRAINT cmc_bar_returns_pkey PRIMARY KEY (id, bar_family, tf, bar_seq),
    CONSTRAINT cmc_bar_returns_bar_family_chk CHECK (
        bar_family IN ('multi_tf','cal_us','cal_iso','cal_anchor_us','cal_anchor_iso')
    )
);

CREATE INDEX IF NOT EXISTS ix_cmc_bar_returns_family_tf_timeclose
ON public.cmc_bar_returns (bar_family, tf, time_close);

CREATE INDEX IF NOT EXISTS ix_cmc_bar_returns_id_family_tf
ON public.cmc_bar_returns (id, bar_family, tf);


CREATE TABLE IF NOT EXISTS public.cmc_bar_returns_state (
    id            integer NOT NULL,
    bar_family    text    NOT NULL,
    tf            text    NOT NULL,

    last_bar_seq  integer,
    updated_at    timestamp with time zone NOT NULL DEFAULT now(),

    CONSTRAINT cmc_bar_returns_state_pkey PRIMARY KEY (id, bar_family, tf),
    CONSTRAINT cmc_bar_returns_state_bar_family_chk CHECK (
        bar_family IN ('multi_tf','cal_us','cal_iso','cal_anchor_us','cal_anchor_iso')
    )
);

CREATE INDEX IF NOT EXISTS ix_cmc_bar_returns_state_family_tf_lastbar
ON public.cmc_bar_returns_state (bar_family, tf, last_bar_seq);



-- ============================================================
-- 3) EMA RETURNS (feature layer)
--    Includes returns on ema AND on ema_bar.
--    Grain: (id, ema_family, tf, period, time_close, roll_flag)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.cmc_ema_returns (
    id            integer NOT NULL,
    ema_family    text    NOT NULL,        -- 'multi_tf','cal_us','cal_iso','cal_anchor_us','cal_anchor_iso'
    tf            text    NOT NULL,
    period        integer NOT NULL,

    time_close    timestamp with time zone NOT NULL,

    roll_flag     boolean NOT NULL DEFAULT false,  -- canonical usually FALSE

    -- EMA series at time_close granularity (preview/canonical depending on family/table)
    ema           double precision,
    prev_ema      double precision,
    ret_arith     double precision,
    ret_log       double precision,

    -- EMA series in bar-space (canonical bar-to-bar EMA)
    ema_bar       double precision,
    prev_ema_bar  double precision,
    ret_arith_bar double precision,
    ret_log_bar   double precision,

    ingested_at   timestamp with time zone NOT NULL DEFAULT now(),

    CONSTRAINT cmc_ema_returns_pkey PRIMARY KEY (id, ema_family, tf, period, time_close, roll_flag),
    CONSTRAINT cmc_ema_returns_ema_family_chk CHECK (
        ema_family IN ('multi_tf','cal_us','cal_iso','cal_anchor_us','cal_anchor_iso')
    )
);

CREATE INDEX IF NOT EXISTS ix_cmc_ema_returns_family_tf_period_timeclose
ON public.cmc_ema_returns (ema_family, tf, period, time_close);

CREATE INDEX IF NOT EXISTS ix_cmc_ema_returns_id_family_tf_period
ON public.cmc_ema_returns (id, ema_family, tf, period);


CREATE TABLE IF NOT EXISTS public.cmc_ema_returns_state (
    id              integer NOT NULL,
    ema_family      text    NOT NULL,
    tf              text    NOT NULL,
    period          integer NOT NULL,
    roll_flag       boolean NOT NULL DEFAULT false,

    last_time_close timestamp with time zone,
    updated_at      timestamp with time zone NOT NULL DEFAULT now(),

    CONSTRAINT cmc_ema_returns_state_pkey PRIMARY KEY (id, ema_family, tf, period, roll_flag),
    CONSTRAINT cmc_ema_returns_state_ema_family_chk CHECK (
        ema_family IN ('multi_tf','cal_us','cal_iso','cal_anchor_us','cal_anchor_iso')
    )
);

CREATE INDEX IF NOT EXISTS ix_cmc_ema_returns_state_family_tf_period_lasttime
ON public.cmc_ema_returns_state (ema_family, tf, period, last_time_close);

COMMIT;
