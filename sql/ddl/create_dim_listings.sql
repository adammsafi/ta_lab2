-- Venue-specific tradeable instruments (listings)
-- One asset in dim_assets can have many listings across venues.
-- Example: CPOOL has listings on BYBIT (CPOOLUSDT), GATE (CPOOLUSDT),
--          and KRAKEN (CPOOLUSD). All share the same dim_assets.id.

CREATE TABLE IF NOT EXISTS public.dim_listings (
    id              INTEGER       NOT NULL,
    venue           TEXT          NOT NULL,
    ticker_on_venue TEXT          NOT NULL,
    asset_class     TEXT          NOT NULL,
    currency        TEXT,
    is_primary      BOOLEAN       DEFAULT FALSE,
    created_at      TIMESTAMPTZ   DEFAULT NOW(),
    PRIMARY KEY (id, venue, ticker_on_venue),
    CONSTRAINT fk_dim_listings_asset
        FOREIGN KEY (id) REFERENCES public.dim_assets(id)
);

-- Fast lookup by venue + ticker (used by CSV loader to resolve IDs)
CREATE INDEX IF NOT EXISTS ix_dl_venue_ticker
  ON public.dim_listings (venue, ticker_on_venue);
