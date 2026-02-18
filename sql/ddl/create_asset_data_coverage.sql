-- asset_data_coverage: tracks per-asset data availability metrics.
--
-- Populated by the 1D bar builder after processing each ID.
-- Consumed by multi-TF builders to filter out timeframes that exceed
-- the asset's available data window.
--
-- n_days: whole calendar days of data, regardless of source granularity.
--         For 1D source data, n_days = n_rows.
--         For intraday data (future), n_days counts distinct UTC dates.

CREATE TABLE IF NOT EXISTS public.asset_data_coverage (
    id              INTEGER     NOT NULL,
    source_table    TEXT        NOT NULL,
    granularity     TEXT        NOT NULL,   -- '1D', '1H', '5M', etc.
    n_rows          BIGINT      NOT NULL,
    n_days          INTEGER     NOT NULL,   -- whole calendar days only
    first_ts        TIMESTAMPTZ NOT NULL,
    last_ts         TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, source_table, granularity)
);

CREATE INDEX IF NOT EXISTS ix_asset_data_coverage_id
    ON public.asset_data_coverage (id);

CREATE INDEX IF NOT EXISTS ix_asset_data_coverage_source
    ON public.asset_data_coverage (source_table, granularity);
