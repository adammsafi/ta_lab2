-- companiesmarketcap_assets_runs: scrape run log / state table
-- One row per refresh execution, tracking status and metrics.

CREATE TABLE IF NOT EXISTS public.companiesmarketcap_assets_runs (
    run_id              SERIAL          PRIMARY KEY,
    started_at          TIMESTAMPTZ     NOT NULL,
    finished_at         TIMESTAMPTZ,
    status              TEXT            NOT NULL DEFAULT 'running',  -- running, completed, failed
    rows_scraped        INTEGER,
    rows_loaded         INTEGER,
    min_mcap_floor      DOUBLE PRECISION,
    pages_fetched       INTEGER,
    error_message       TEXT,
    asset_type_counts   JSONB
);
