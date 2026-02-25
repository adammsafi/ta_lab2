-- 095_cmc_funding_rates.sql
-- Reference DDL for cmc_funding_rates table.
-- Phase 51: Perps Readiness.
-- ASCII-only: no box-drawing or non-ASCII characters (Windows cp1252 compatibility).
--
-- Purpose: Multi-venue perpetual funding rate history.
-- PK: (venue, symbol, ts, tf)
-- tf stores the native settlement granularity: '1h' (Hyperliquid, dYdX, Aevo),
-- '4h' (Aevo instruments, Aster ASTERUSDT), '8h' (Binance, Bybit, Aster),
-- '1d' is a daily rollup computed from sub-day rates.

CREATE TABLE public.cmc_funding_rates (
    venue           TEXT        NOT NULL,
    symbol          TEXT        NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT        NOT NULL,
    funding_rate    NUMERIC     NOT NULL,
    mark_price      NUMERIC,
    raw_tf          TEXT,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_cmc_funding_rates
        PRIMARY KEY (venue, symbol, ts, tf),

    CONSTRAINT chk_funding_venue
        CHECK (venue IN (
            'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'aster', 'lighter'
        )),

    CONSTRAINT chk_funding_tf
        CHECK (tf IN ('1h', '4h', '8h', '1d'))
);

CREATE INDEX idx_funding_rates_symbol_ts
    ON public.cmc_funding_rates (symbol, ts DESC);

CREATE INDEX idx_funding_rates_venue_symbol_ts
    ON public.cmc_funding_rates (venue, symbol, ts DESC);

COMMENT ON TABLE public.cmc_funding_rates IS
    'Multi-venue perpetual funding rate history. '
    'PK: (venue, symbol, ts, tf). '
    'tf stores native settlement granularity (1h, 4h, 8h) or daily rollup (1d). '
    'Positive funding_rate means longs pay shorts (standard convention). '
    'mark_price is nullable; not all venues return it with funding data.';

COMMENT ON COLUMN public.cmc_funding_rates.venue IS
    'Exchange venue: binance, hyperliquid, bybit, dydx, aevo, aster, or lighter.';

COMMENT ON COLUMN public.cmc_funding_rates.symbol IS
    'Base asset symbol without quote currency, e.g. BTC, ETH.';

COMMENT ON COLUMN public.cmc_funding_rates.ts IS
    'UTC settlement timestamp for this funding rate payment.';

COMMENT ON COLUMN public.cmc_funding_rates.tf IS
    'Settlement granularity: 1h, 4h, 8h, or 1d (daily rollup). '
    'Stored in raw_tf column for original venue settlement period.';

COMMENT ON COLUMN public.cmc_funding_rates.funding_rate IS
    'Raw per-settlement rate as decimal (e.g. 0.0001 = 0.01% per settlement). '
    'NOT annualized. Normalize in queries as needed.';

COMMENT ON COLUMN public.cmc_funding_rates.raw_tf IS
    'Original venue settlement period string, e.g. 8h, 1h, rollup.';
