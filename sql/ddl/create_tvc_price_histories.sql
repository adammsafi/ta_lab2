-- Raw TradingView OHLCV price data
-- Loaded from CSV exports in tvc_price_data/YYYYMMDD/ folders.
-- PK includes venue to support multi-exchange data (e.g., CPOOL on
-- BYBIT, GATE, KRAKEN with potentially different prices).

CREATE TABLE IF NOT EXISTS public.tvc_price_histories (
    id              INTEGER          NOT NULL,
    venue           TEXT             NOT NULL,
    ts              TIMESTAMPTZ      NOT NULL,
    open            DOUBLE PRECISION NOT NULL,
    high            DOUBLE PRECISION NOT NULL,
    low             DOUBLE PRECISION NOT NULL,
    close           DOUBLE PRECISION NOT NULL,
    volume          DOUBLE PRECISION,
    data_watermark  DATE,
    source_file     TEXT,
    ingested_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, venue, ts)
);

-- Fast lookup by asset ID + timestamp (ignoring venue)
CREATE INDEX IF NOT EXISTS ix_tvc_ph_id_ts
  ON public.tvc_price_histories (id, ts);
