-- Unified price histories view
-- Normalizes CMC and TVC raw price data into a common schema.
-- Used by multi-TF bar builders via --daily-table public.price_histories_u
-- to process both data sources transparently.
-- Includes is_primary_venue flag for downstream filtering.

DROP VIEW IF EXISTS public.price_histories_u;

CREATE VIEW public.price_histories_u AS

-- CMC source (7 crypto assets)
SELECT
    id,
    'CMC_AGG'::text           AS venue,
    "timestamp",
    timeopen,
    timeclose,
    timehigh,
    timelow,
    open,
    high,
    low,
    close,
    volume,
    marketcap,
    name,
    source_file               AS src_file,
    load_ts                   AS src_load_ts,
    TRUE::boolean             AS is_primary_venue
FROM public.cmc_price_histories7

UNION ALL

-- TVC source (equities, ETFs, multi-exchange crypto)
-- Returns ALL venues with is_primary_venue flag from dim_listings.
-- Downstream consumers filter by is_primary_venue = TRUE as needed.
SELECT
    t.id,
    t.venue,
    t.ts                      AS "timestamp",
    NULL::timestamptz         AS timeopen,
    t.ts                      AS timeclose,
    NULL::timestamptz         AS timehigh,
    NULL::timestamptz         AS timelow,
    t.open,
    t.high,
    t.low,
    t.close,
    t.volume,
    NULL::double precision    AS marketcap,
    'TradingView'::text       AS name,
    t.source_file             AS src_file,
    t.ingested_at             AS src_load_ts,
    COALESCE(dl.is_primary, TRUE)::boolean AS is_primary_venue
FROM public.tvc_price_histories t
LEFT JOIN public.dim_listings dl
    ON dl.id = t.id AND dl.venue = t.venue;
