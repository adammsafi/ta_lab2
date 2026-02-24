-- data_sources: central registry of all external and derived data sources
-- Tracks what feeds the system, refresh cadence, and staleness.

CREATE TABLE IF NOT EXISTS public.data_sources (
    source_key      TEXT            PRIMARY KEY,
    name            TEXT            NOT NULL,
    source_type     TEXT            NOT NULL,        -- scrape, api, file_load, derived
    url             TEXT,
    description     TEXT,
    refresh_cadence TEXT,                            -- daily, weekly, manual, on_demand
    target_table    TEXT,
    run_log_table   TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    last_refreshed  TIMESTAMPTZ,
    last_row_count  INTEGER,
    config          JSONB,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
