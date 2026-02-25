"""perps_readiness

Schema changes for Phase 51 (Perps Readiness):

1. CREATE TABLE cmc_funding_rates: multi-venue funding rate history
2. CREATE TABLE cmc_margin_config: venue-specific tiered margin rates (seed data included)
3. CREATE TABLE cmc_perp_positions: perp position tracking with margin state
4. Extend cmc_risk_events type CHECK: add liquidation event types
5. Extend cmc_risk_events source CHECK: add margin_monitor trigger source
6. ALTER dim_risk_limits: add margin alert threshold columns

Revision ID: 30eac3660488
Revises: a9ec3c00a54a
Create Date: 2026-02-25 23:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "30eac3660488"
down_revision: Union[str, Sequence[str], None] = "a9ec3c00a54a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema -- create Phase 51 perps tables and extend risk event constraints."""

    # -------------------------------------------------------------------------
    # 1. CREATE TABLE cmc_funding_rates
    # -------------------------------------------------------------------------
    op.create_table(
        "cmc_funding_rates",
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column("funding_rate", sa.Numeric(), nullable=False),
        sa.Column("mark_price", sa.Numeric(), nullable=True),
        sa.Column("raw_tf", sa.Text(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "venue", "symbol", "ts", "tf", name="pk_cmc_funding_rates"
        ),
    )

    op.execute(
        "ALTER TABLE public.cmc_funding_rates"
        " ADD CONSTRAINT chk_funding_venue"
        " CHECK (venue IN ("
        "'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'aster', 'lighter'"
        "))"
    )

    op.execute(
        "ALTER TABLE public.cmc_funding_rates"
        " ADD CONSTRAINT chk_funding_tf"
        " CHECK (tf IN ('1h', '4h', '8h', '1d'))"
    )

    op.create_index(
        "idx_funding_rates_symbol_ts",
        "cmc_funding_rates",
        ["symbol", sa.text("ts DESC")],
    )

    op.create_index(
        "idx_funding_rates_venue_symbol_ts",
        "cmc_funding_rates",
        ["venue", "symbol", sa.text("ts DESC")],
    )

    op.execute(
        "COMMENT ON TABLE public.cmc_funding_rates IS"
        " 'Multi-venue perpetual funding rate history."
        " PK: (venue, symbol, ts, tf)."
        " tf stores native settlement granularity (1h, 4h, 8h) or daily rollup (1d)."
        " Positive funding_rate means longs pay shorts.'"
    )

    # -------------------------------------------------------------------------
    # 2. CREATE TABLE cmc_margin_config
    # -------------------------------------------------------------------------
    op.create_table(
        "cmc_margin_config",
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column(
            "notional_floor",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("notional_cap", sa.Numeric(), nullable=True),
        sa.Column("initial_margin_rate", sa.Numeric(), nullable=False),
        sa.Column("maintenance_margin_rate", sa.Numeric(), nullable=False),
        sa.Column("max_leverage", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("venue", "symbol", "tier", name="pk_cmc_margin_config"),
    )

    op.execute(
        "ALTER TABLE public.cmc_margin_config"
        " ADD CONSTRAINT chk_margin_config_venue"
        " CHECK (venue IN ("
        "'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'aster', 'lighter'"
        "))"
    )

    op.execute(
        "COMMENT ON TABLE public.cmc_margin_config IS"
        " 'Venue-specific tiered margin rates for perpetual futures."
        " PK: (venue, symbol, tier)."
        " Seed data includes Binance BTC/ETH tiers and Hyperliquid BTC/ETH tiers."
        " initial_margin_rate and maintenance_margin_rate are decimal fractions.'"
    )

    # Seed data: Binance BTC tiers
    op.execute(
        "INSERT INTO public.cmc_margin_config"
        " (venue, symbol, tier, notional_floor, notional_cap,"
        "  initial_margin_rate, maintenance_margin_rate, max_leverage)"
        " VALUES"
        " ('binance', 'BTC', 1,      0,    50000, 0.008, 0.004, 125),"
        " ('binance', 'BTC', 2,  50000,   250000, 0.010, 0.005, 100),"
        " ('binance', 'BTC', 3, 250000,  1000000, 0.020, 0.010,  50)"
        " ON CONFLICT (venue, symbol, tier) DO NOTHING"
    )

    # Seed data: Binance ETH tiers
    op.execute(
        "INSERT INTO public.cmc_margin_config"
        " (venue, symbol, tier, notional_floor, notional_cap,"
        "  initial_margin_rate, maintenance_margin_rate, max_leverage)"
        " VALUES"
        " ('binance', 'ETH', 1,      0,    50000, 0.008, 0.004, 100),"
        " ('binance', 'ETH', 2,  50000,   250000, 0.010, 0.005,  75),"
        " ('binance', 'ETH', 3, 250000,  1000000, 0.020, 0.010,  50)"
        " ON CONFLICT (venue, symbol, tier) DO NOTHING"
    )

    # Seed data: Hyperliquid BTC single tier (max leverage 50x)
    op.execute(
        "INSERT INTO public.cmc_margin_config"
        " (venue, symbol, tier, notional_floor, notional_cap,"
        "  initial_margin_rate, maintenance_margin_rate, max_leverage)"
        " VALUES"
        " ('hyperliquid', 'BTC', 1, 0, NULL, 0.020, 0.010, 50)"
        " ON CONFLICT (venue, symbol, tier) DO NOTHING"
    )

    # Seed data: Hyperliquid ETH single tier (max leverage 50x)
    op.execute(
        "INSERT INTO public.cmc_margin_config"
        " (venue, symbol, tier, notional_floor, notional_cap,"
        "  initial_margin_rate, maintenance_margin_rate, max_leverage)"
        " VALUES"
        " ('hyperliquid', 'ETH', 1, 0, NULL, 0.020, 0.010, 50)"
        " ON CONFLICT (venue, symbol, tier) DO NOTHING"
    )

    # -------------------------------------------------------------------------
    # 3. CREATE TABLE cmc_perp_positions
    # -------------------------------------------------------------------------
    op.create_table(
        "cmc_perp_positions",
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column(
            "strategy_id", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column(
            "quantity", sa.Numeric(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("avg_entry_price", sa.Numeric(), nullable=True),
        sa.Column("mark_price", sa.Numeric(), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(), nullable=True),
        sa.Column(
            "margin_mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'isolated'"),
        ),
        sa.Column(
            "leverage", sa.Numeric(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "allocated_margin",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("maintenance_margin", sa.Numeric(), nullable=True),
        sa.Column("margin_utilization", sa.Numeric(), nullable=True),
        sa.Column("liquidation_price", sa.Numeric(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "venue", "symbol", "strategy_id", name="pk_cmc_perp_positions"
        ),
    )

    op.execute(
        "ALTER TABLE public.cmc_perp_positions"
        " ADD CONSTRAINT chk_perp_positions_venue"
        " CHECK (venue IN ("
        "'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'aster', 'lighter'"
        "))"
    )

    op.execute(
        "ALTER TABLE public.cmc_perp_positions"
        " ADD CONSTRAINT chk_perp_positions_side"
        " CHECK (side IN ('long', 'short', 'flat'))"
    )

    op.execute(
        "ALTER TABLE public.cmc_perp_positions"
        " ADD CONSTRAINT chk_perp_positions_margin_mode"
        " CHECK (margin_mode IN ('isolated', 'cross'))"
    )

    op.execute(
        "COMMENT ON TABLE public.cmc_perp_positions IS"
        " 'Perp futures position tracking with margin state."
        " PK: (venue, symbol, strategy_id)."
        " Separate from cmc_positions (spot) to avoid extending the spot exchange CHECK constraint."
        " margin_utilization <= 1.5 triggers warning; <= 1.1 triggers liquidation critical.'"
    )

    # -------------------------------------------------------------------------
    # 4. Extend cmc_risk_events event_type CHECK
    # Add: liquidation_warning, liquidation_critical, margin_alert
    # Current (from a9ec3c00a54a): 12 types including tail_risk_escalated, tail_risk_cleared
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_type"
    )
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " ADD CONSTRAINT chk_risk_events_type CHECK (event_type IN ("
        "'kill_switch_activated', 'kill_switch_disabled',"
        " 'position_cap_scaled', 'position_cap_blocked',"
        " 'daily_loss_stop_triggered',"
        " 'circuit_breaker_tripped', 'circuit_breaker_reset',"
        " 'override_created', 'override_applied', 'override_reverted',"
        " 'tail_risk_escalated', 'tail_risk_cleared',"
        " 'liquidation_warning', 'liquidation_critical', 'margin_alert'"
        "))"
    )

    # -------------------------------------------------------------------------
    # 5. Extend cmc_risk_events trigger_source CHECK
    # Add: margin_monitor
    # Current (from a9ec3c00a54a): 5 sources including tail_risk
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_source"
    )
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " ADD CONSTRAINT chk_risk_events_source CHECK (trigger_source IN ("
        "'manual', 'daily_loss_stop', 'circuit_breaker', 'system', 'tail_risk', 'margin_monitor'"
        "))"
    )

    # -------------------------------------------------------------------------
    # 6. Add margin threshold columns to dim_risk_limits
    # -------------------------------------------------------------------------
    op.add_column(
        "dim_risk_limits",
        sa.Column(
            "margin_alert_threshold",
            sa.Numeric(),
            nullable=True,
            server_default=sa.text("1.5"),
        ),
    )
    op.add_column(
        "dim_risk_limits",
        sa.Column(
            "liquidation_kill_threshold",
            sa.Numeric(),
            nullable=True,
            server_default=sa.text("1.1"),
        ),
    )

    op.execute(
        "COMMENT ON COLUMN public.dim_risk_limits.margin_alert_threshold IS"
        " 'margin_utilization at or below this value triggers liquidation_warning event."
        " Default 1.5 means alert when current margin <= 1.5x maintenance margin.'"
    )
    op.execute(
        "COMMENT ON COLUMN public.dim_risk_limits.liquidation_kill_threshold IS"
        " 'margin_utilization at or below this value triggers liquidation_critical event"
        " and blocks new orders via RiskEngine Gate 1.6."
        " Default 1.1 means kill switch when margin <= 1.1x maintenance margin.'"
    )


def downgrade() -> None:
    """Downgrade schema -- remove Phase 51 perps tables and restore prior constraints."""

    # -------------------------------------------------------------------------
    # 6-reverse: drop margin threshold columns from dim_risk_limits
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.dim_risk_limits"
        " DROP COLUMN IF EXISTS liquidation_kill_threshold,"
        " DROP COLUMN IF EXISTS margin_alert_threshold"
    )

    # -------------------------------------------------------------------------
    # 5-reverse: restore trigger_source CHECK without margin_monitor
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_source"
    )
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " ADD CONSTRAINT chk_risk_events_source CHECK (trigger_source IN ("
        "'manual', 'daily_loss_stop', 'circuit_breaker', 'system', 'tail_risk'"
        "))"
    )

    # -------------------------------------------------------------------------
    # 4-reverse: restore event_type CHECK without liquidation types
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_type"
    )
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " ADD CONSTRAINT chk_risk_events_type CHECK (event_type IN ("
        "'kill_switch_activated', 'kill_switch_disabled',"
        " 'position_cap_scaled', 'position_cap_blocked',"
        " 'daily_loss_stop_triggered',"
        " 'circuit_breaker_tripped', 'circuit_breaker_reset',"
        " 'override_created', 'override_applied', 'override_reverted',"
        " 'tail_risk_escalated', 'tail_risk_cleared'"
        "))"
    )

    # -------------------------------------------------------------------------
    # 3-reverse: drop cmc_perp_positions
    # -------------------------------------------------------------------------
    op.drop_table("cmc_perp_positions")

    # -------------------------------------------------------------------------
    # 2-reverse: drop cmc_margin_config
    # -------------------------------------------------------------------------
    op.drop_table("cmc_margin_config")

    # -------------------------------------------------------------------------
    # 1-reverse: drop cmc_funding_rates
    # -------------------------------------------------------------------------
    op.drop_index("idx_funding_rates_venue_symbol_ts", table_name="cmc_funding_rates")
    op.drop_index("idx_funding_rates_symbol_ts", table_name="cmc_funding_rates")
    op.drop_table("cmc_funding_rates")
