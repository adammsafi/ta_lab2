-- 097_cmc_perp_positions.sql
-- Reference DDL for cmc_perp_positions table.
-- Phase 51: Perps Readiness.
-- ASCII-only: no box-drawing or non-ASCII characters (Windows cp1252 compatibility).
--
-- Purpose: Track perpetual futures positions with margin state, separate from cmc_positions (spot).
-- Kept separate from cmc_positions to avoid touching the existing spot position CHECK constraint
-- (cmc_positions has CHECK (exchange IN ('coinbase','kraken','paper','aggregate')) which
-- does not include perp venue names and is not extensible without breaking existing logic).
--
-- PK: (venue, symbol, strategy_id)
-- One row per active or closed position per strategy per symbol per venue.
-- strategy_id = 0 is the default strategy.

CREATE TABLE public.cmc_perp_positions (
    venue               TEXT        NOT NULL,
    symbol              TEXT        NOT NULL,
    strategy_id         INTEGER     NOT NULL DEFAULT 0,
    side                TEXT        NOT NULL,
    quantity            NUMERIC     NOT NULL DEFAULT 0,
    avg_entry_price     NUMERIC,
    mark_price          NUMERIC,
    unrealized_pnl      NUMERIC,
    margin_mode         TEXT        NOT NULL DEFAULT 'isolated',
    leverage            NUMERIC     NOT NULL DEFAULT 1,
    allocated_margin    NUMERIC     NOT NULL DEFAULT 0,
    maintenance_margin  NUMERIC,
    margin_utilization  NUMERIC,
    liquidation_price   NUMERIC,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_cmc_perp_positions
        PRIMARY KEY (venue, symbol, strategy_id),

    CONSTRAINT chk_perp_positions_venue
        CHECK (venue IN (
            'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'aster', 'lighter'
        )),

    CONSTRAINT chk_perp_positions_side
        CHECK (side IN ('long', 'short', 'flat')),

    CONSTRAINT chk_perp_positions_margin_mode
        CHECK (margin_mode IN ('isolated', 'cross'))
);

COMMENT ON TABLE public.cmc_perp_positions IS
    'Perpetual futures position tracking with margin state. '
    'PK: (venue, symbol, strategy_id). '
    'Kept separate from cmc_positions (spot) because cmc_positions has a '
    'CHECK (exchange IN (coinbase, kraken, paper, aggregate)) constraint '
    'that does not include perp venue names. '
    'Side = flat means position is closed but row is retained for audit. '
    'margin_utilization = allocated_margin / maintenance_margin; '
    'values <= 1.5 trigger warning alert, values <= 1.1 trigger liquidation alert.';

COMMENT ON COLUMN public.cmc_perp_positions.side IS
    'Position direction: long, short, or flat (closed).';

COMMENT ON COLUMN public.cmc_perp_positions.quantity IS
    'Position size in base asset units. 0 when side = flat.';

COMMENT ON COLUMN public.cmc_perp_positions.avg_entry_price IS
    'Volume-weighted average entry price in USDT.';

COMMENT ON COLUMN public.cmc_perp_positions.mark_price IS
    'Current mark price used for unrealized P&L and margin calculations.';

COMMENT ON COLUMN public.cmc_perp_positions.unrealized_pnl IS
    'Unrealized profit or loss in USDT at current mark_price.';

COMMENT ON COLUMN public.cmc_perp_positions.margin_mode IS
    'isolated: margin dedicated to this position only. '
    'cross: shared wallet margin across all positions at venue.';

COMMENT ON COLUMN public.cmc_perp_positions.leverage IS
    'Leverage multiplier for this position (1x to 125x, venue-dependent).';

COMMENT ON COLUMN public.cmc_perp_positions.allocated_margin IS
    'Collateral in USDT currently allocated to this position.';

COMMENT ON COLUMN public.cmc_perp_positions.maintenance_margin IS
    'Minimum margin in USDT required to keep position open (from cmc_margin_config tier).';

COMMENT ON COLUMN public.cmc_perp_positions.margin_utilization IS
    'Ratio: allocated_margin / maintenance_margin. '
    'Decreasing toward 1.0 means approaching liquidation. '
    '<= 1.5 triggers liquidation_warning event; <= 1.1 triggers liquidation_critical event.';

COMMENT ON COLUMN public.cmc_perp_positions.liquidation_price IS
    'Estimated price at which position would be liquidated given current margin.';
