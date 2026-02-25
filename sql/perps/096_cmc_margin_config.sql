-- 096_cmc_margin_config.sql
-- Reference DDL for cmc_margin_config dimension table.
-- Phase 51: Perps Readiness.
-- ASCII-only: no box-drawing or non-ASCII characters (Windows cp1252 compatibility).
--
-- Purpose: Venue-specific tiered margin rates for perpetual futures positions.
-- Dimension/config table; seed data for Binance and Hyperliquid BTC/ETH provided below.
-- PK: (venue, symbol, tier)

CREATE TABLE public.cmc_margin_config (
    venue                   TEXT        NOT NULL,
    symbol                  TEXT        NOT NULL,
    tier                    INTEGER     NOT NULL,
    notional_floor          NUMERIC     NOT NULL DEFAULT 0,
    notional_cap            NUMERIC,
    initial_margin_rate     NUMERIC     NOT NULL,
    maintenance_margin_rate NUMERIC     NOT NULL,
    max_leverage            INTEGER,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_cmc_margin_config
        PRIMARY KEY (venue, symbol, tier),

    CONSTRAINT chk_margin_config_venue
        CHECK (venue IN (
            'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'aster', 'lighter'
        ))
);

COMMENT ON TABLE public.cmc_margin_config IS
    'Venue-specific tiered margin rates for perpetual futures. '
    'PK: (venue, symbol, tier). '
    'Tier 1 applies to the smallest notional bracket (notional_floor = 0). '
    'notional_cap NULL means no cap (last tier). '
    'initial_margin_rate: fraction required to open position (e.g. 0.008 = 0.8%). '
    'maintenance_margin_rate: fraction below which liquidation occurs (e.g. 0.004 = 0.4%). '
    'Rates are as of Phase 51 creation date; fetch live from venue API for production use.';

COMMENT ON COLUMN public.cmc_margin_config.notional_floor IS
    'Minimum position notional (in USDT) for this tier to apply. Tier 1 is always 0.';

COMMENT ON COLUMN public.cmc_margin_config.notional_cap IS
    'Maximum position notional for this tier. NULL for the highest (last) tier.';

COMMENT ON COLUMN public.cmc_margin_config.initial_margin_rate IS
    'Initial margin rate as decimal fraction (e.g. 0.008 = 0.8%).';

COMMENT ON COLUMN public.cmc_margin_config.maintenance_margin_rate IS
    'Maintenance margin rate as decimal fraction (e.g. 0.004 = 0.4%).';

-- Seed data: Binance BTC perpetual tiers (BTCUSDT, as of 2025)
-- Source: GET /fapi/v1/leverageBracket (Binance Futures API)
-- Tier 1: 0 - 50K USDT, max lev 125x, IM 0.8%, MM 0.4%
-- Tier 2: 50K - 250K USDT, max lev 100x, IM 1%, MM 0.5%
-- Tier 3: 250K - 1M USDT, max lev 50x, IM 2%, MM 1%
INSERT INTO public.cmc_margin_config
    (venue, symbol, tier, notional_floor, notional_cap, initial_margin_rate, maintenance_margin_rate, max_leverage)
VALUES
    ('binance', 'BTC', 1,      0,    50000, 0.008, 0.004, 125),
    ('binance', 'BTC', 2,  50000,   250000, 0.010, 0.005, 100),
    ('binance', 'BTC', 3, 250000,  1000000, 0.020, 0.010,  50)
ON CONFLICT (venue, symbol, tier) DO NOTHING;

-- Seed data: Binance ETH perpetual tiers (ETHUSDT, as of 2025)
-- Similar tier structure to BTC
INSERT INTO public.cmc_margin_config
    (venue, symbol, tier, notional_floor, notional_cap, initial_margin_rate, maintenance_margin_rate, max_leverage)
VALUES
    ('binance', 'ETH', 1,      0,    50000, 0.008, 0.004, 100),
    ('binance', 'ETH', 2,  50000,   250000, 0.010, 0.005,  75),
    ('binance', 'ETH', 3, 250000,  1000000, 0.020, 0.010,  50)
ON CONFLICT (venue, symbol, tier) DO NOTHING;

-- Seed data: Hyperliquid BTC (single tier, max leverage 50x)
-- Formula: IM rate = 1/max_leverage, MM rate = 1/(2*max_leverage)
-- At 50x: IM = 2%, MM = 1%
INSERT INTO public.cmc_margin_config
    (venue, symbol, tier, notional_floor, notional_cap, initial_margin_rate, maintenance_margin_rate, max_leverage)
VALUES
    ('hyperliquid', 'BTC', 1, 0, NULL, 0.020, 0.010, 50)
ON CONFLICT (venue, symbol, tier) DO NOTHING;

-- Seed data: Hyperliquid ETH (single tier, max leverage 50x)
INSERT INTO public.cmc_margin_config
    (venue, symbol, tier, notional_floor, notional_cap, initial_margin_rate, maintenance_margin_rate, max_leverage)
VALUES
    ('hyperliquid', 'ETH', 1, 0, NULL, 0.020, 0.010, 50)
ON CONFLICT (venue, symbol, tier) DO NOTHING;
