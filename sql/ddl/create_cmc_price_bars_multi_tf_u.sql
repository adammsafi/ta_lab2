-- create_cmc_price_bars_multi_tf_u.sql
--
-- Unified price bars: union of all 5 alignment variants with alignment_source.
-- PK: (id, tf, bar_seq, "timestamp", alignment_source)

BEGIN;

CREATE TABLE IF NOT EXISTS public.cmc_price_bars_multi_tf_u (
    id                          integer       NOT NULL,
    "timestamp"                 timestamptz   NOT NULL,
    tf                          text          NOT NULL,
    tf_days                     integer,
    bar_seq                     integer       NOT NULL,
    alignment_source            text          NOT NULL,

    pos_in_bar                  integer,
    count_days                  integer,
    count_days_remaining        integer,
    time_open_bar               timestamptz,
    time_close_bar              timestamptz,

    "open"                      double precision NOT NULL,
    high                        double precision NOT NULL,
    low                         double precision NOT NULL,
    "close"                     double precision NOT NULL,
    volume                      double precision,
    market_cap                  double precision,
    time_high                   timestamptz   NOT NULL,
    time_low                    timestamptz   NOT NULL,

    is_partial_start            boolean       NOT NULL,
    is_partial_end              boolean       NOT NULL,
    time_open                   timestamptz   NOT NULL,
    time_close                  timestamptz   NOT NULL,
    last_ts_half_open           timestamptz,

    is_missing_days             boolean       NOT NULL,
    count_missing_days          integer,
    count_missing_days_start    integer,
    count_missing_days_end      integer,
    count_missing_days_interior integer,
    missing_days_where          text,
    first_missing_day           timestamptz,
    last_missing_day            timestamptz,

    repaired_timehigh           boolean       NOT NULL,
    repaired_timelow            boolean       NOT NULL,
    repaired_high               boolean       NOT NULL,
    repaired_low                boolean       NOT NULL,
    repaired_open               boolean       NOT NULL,
    repaired_close              boolean       NOT NULL,
    repaired_volume             boolean       NOT NULL,
    repaired_market_cap         boolean       NOT NULL,

    src_name                    text,
    src_load_ts                 timestamptz,
    src_file                    text,

    ingested_at                 timestamptz   NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, bar_seq, "timestamp", alignment_source)
);

CREATE INDEX IF NOT EXISTS ix_price_bars_u_alignment
ON public.cmc_price_bars_multi_tf_u (alignment_source);

CREATE INDEX IF NOT EXISTS ix_price_bars_u_id_tf_ts
ON public.cmc_price_bars_multi_tf_u (id, tf, "timestamp");

CREATE INDEX IF NOT EXISTS ix_price_bars_u_ingested
ON public.cmc_price_bars_multi_tf_u (ingested_at);

COMMIT;
