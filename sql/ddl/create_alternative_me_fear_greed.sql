-- alternative_me_fear_greed: Crypto Fear & Greed Index (daily)
-- Source: https://api.alternative.me/fng/
-- Refreshed by: ta_lab2.scripts.etl.refresh_fear_greed

CREATE TABLE IF NOT EXISTS public.alternative_me_fear_greed (
    ts                    DATE            PRIMARY KEY,      -- UTC date of reading
    value                 SMALLINT        NOT NULL,         -- 0-100 index value
    value_classification  TEXT            NOT NULL,         -- Extreme Fear / Fear / Neutral / Greed / Extreme Greed
    api_timestamp         BIGINT          NOT NULL,         -- raw unix timestamp from API
    ingested_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.alternative_me_fear_greed IS
'Crypto Fear & Greed Index from alternative.me. One row per UTC day, value 0-100.';

CREATE INDEX IF NOT EXISTS ix_alternative_me_fear_greed_value
    ON public.alternative_me_fear_greed (value);
