-- companiesmarketcap_assets: latest snapshot of assets ranked by market cap
-- Source: https://companiesmarketcap.com/assets-by-market-cap/
-- Refreshed by: ta_lab2.scripts.etl.load_companiesmarketcap_assets

CREATE TABLE IF NOT EXISTS public.companiesmarketcap_assets (
    ticker          TEXT             NOT NULL,
    asset_type      TEXT             NOT NULL,   -- equity, etf, crypto, precious_metal
    rank            INTEGER          NOT NULL,
    name            TEXT             NOT NULL,
    market_cap      BIGINT,
    price           DOUBLE PRECISION,
    change_pct      DOUBLE PRECISION,
    country         TEXT,
    url             TEXT,
    scraped_at      TIMESTAMPTZ      NOT NULL,   -- when the page was fetched
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),  -- first insert
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),  -- last upsert
    PRIMARY KEY (ticker, asset_type)
);

CREATE INDEX IF NOT EXISTS ix_companiesmarketcap_assets_rank
    ON public.companiesmarketcap_assets (rank);

CREATE INDEX IF NOT EXISTS ix_companiesmarketcap_assets_asset_type
    ON public.companiesmarketcap_assets (asset_type);
