"""risk_controls

Revision ID: b5178d671e38
Revises: 225bf8646f03
Create Date: 2026-02-25 09:28:38.985115

Schema changes for Phase 46 (Risk Controls):

1. dim_risk_limits: Runtime-editable config for position caps, daily loss, circuit breaker.
2. dim_risk_state: Single-row live state (kill switch, daily loss tracking, circuit breaker counters).
3. cmc_risk_events: Immutable audit log for all risk events.
4. cmc_risk_overrides: Discretionary override store with sticky/non-sticky support.

Note: All comments use ASCII only (Windows cp1252 compatibility).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5178d671e38"
down_revision: Union[str, Sequence[str], None] = "225bf8646f03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema -- create Phase 46 risk control tables."""

    # ------------------------------------------------------------------
    # 1. dim_risk_limits: Runtime-editable risk limit configuration
    # ------------------------------------------------------------------
    op.create_table(
        "dim_risk_limits",
        sa.Column("limit_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column(
            "max_position_pct",
            sa.Numeric(),
            server_default=sa.text("0.15"),
            nullable=False,
        ),
        sa.Column(
            "max_portfolio_pct",
            sa.Numeric(),
            server_default=sa.text("0.80"),
            nullable=False,
        ),
        sa.Column(
            "daily_loss_pct_threshold",
            sa.Numeric(),
            server_default=sa.text("0.03"),
            nullable=False,
        ),
        sa.Column(
            "cb_consecutive_losses_n",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "cb_loss_threshold_pct",
            sa.Numeric(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "cb_cooldown_hours",
            sa.Numeric(),
            server_default=sa.text("24.0"),
            nullable=False,
        ),
        sa.Column(
            "allow_overrides",
            sa.Boolean(),
            server_default=sa.text("TRUE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("limit_id", name="pk_dim_risk_limits"),
        sa.CheckConstraint(
            "max_position_pct > 0 AND max_position_pct <= 1",
            name="chk_risk_limits_max_pos",
        ),
        sa.CheckConstraint(
            "max_portfolio_pct > 0 AND max_portfolio_pct <= 1",
            name="chk_risk_limits_max_port",
        ),
        sa.CheckConstraint(
            "daily_loss_pct_threshold > 0 AND daily_loss_pct_threshold <= 1",
            name="chk_risk_limits_daily",
        ),
        sa.CheckConstraint(
            "cb_consecutive_losses_n >= 1",
            name="chk_risk_limits_n",
        ),
        sa.CheckConstraint(
            "cb_cooldown_hours >= 0",
            name="chk_risk_limits_cooldown",
        ),
    )
    op.execute(
        sa.text(
            "COMMENT ON TABLE public.dim_risk_limits IS"
            " 'Runtime-editable risk limit configuration."
            " NULL asset_id/strategy_id = portfolio-wide defaults.'"
        )
    )
    # Seed portfolio-wide default row
    op.execute(
        sa.text(
            "INSERT INTO public.dim_risk_limits (asset_id, strategy_id) VALUES (NULL, NULL)"
        )
    )

    # ------------------------------------------------------------------
    # 2. dim_risk_state: Single-row live state table
    # ------------------------------------------------------------------
    op.create_table(
        "dim_risk_state",
        sa.Column(
            "state_id",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "trading_state",
            sa.Text(),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("halted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("halted_reason", sa.Text(), nullable=True),
        sa.Column("halted_by", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("day_open_portfolio_value", sa.Numeric(), nullable=True),
        sa.Column("last_day_open_date", sa.Date(), nullable=True),
        sa.Column(
            "cb_consecutive_losses",
            sa.Text(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "cb_breaker_tripped_at",
            sa.Text(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "cb_portfolio_consecutive_losses",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "cb_portfolio_breaker_tripped_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("state_id", name="pk_dim_risk_state"),
        sa.CheckConstraint(
            "trading_state IN ('active', 'halted')",
            name="chk_risk_state_trading",
        ),
        sa.CheckConstraint(
            "state_id = 1",
            name="chk_risk_state_single",
        ),
    )
    op.execute(
        sa.text(
            "COMMENT ON TABLE public.dim_risk_state IS"
            " 'Single-row live state table for kill switch and circuit breaker."
            " Enforced single-row via CHECK(state_id=1).'"
        )
    )
    # Seed the single required row
    op.execute(
        sa.text(
            "INSERT INTO public.dim_risk_state (state_id)"
            " VALUES (1)"
            " ON CONFLICT (state_id) DO NOTHING"
        )
    )

    # ------------------------------------------------------------------
    # 3. cmc_risk_events: Immutable audit log
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_risk_events",
        sa.Column(
            "event_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "event_ts",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("trigger_source", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column(
            "order_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "override_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("event_id", name="pk_cmc_risk_events"),
        sa.CheckConstraint(
            "event_type IN ("
            "'kill_switch_activated', 'kill_switch_disabled',"
            " 'position_cap_scaled', 'position_cap_blocked',"
            " 'daily_loss_stop_triggered', 'circuit_breaker_tripped',"
            " 'circuit_breaker_reset', 'override_created',"
            " 'override_applied', 'override_reverted'"
            ")",
            name="chk_risk_events_type",
        ),
        sa.CheckConstraint(
            "trigger_source IN ('manual', 'daily_loss_stop', 'circuit_breaker', 'system')",
            name="chk_risk_events_source",
        ),
    )
    op.execute(
        sa.text(
            "COMMENT ON TABLE public.cmc_risk_events IS"
            " 'Immutable audit log for all risk control events. Never DELETE rows.'"
        )
    )
    op.create_index(
        "idx_risk_events_ts",
        "cmc_risk_events",
        [sa.text("event_ts DESC")],
    )
    op.create_index(
        "idx_risk_events_type",
        "cmc_risk_events",
        ["event_type", sa.text("event_ts DESC")],
    )
    op.create_index(
        "idx_risk_events_asset",
        "cmc_risk_events",
        ["asset_id", sa.text("event_ts DESC")],
        postgresql_where=sa.text("asset_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 4. cmc_risk_overrides: Discretionary override store
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_risk_overrides",
        sa.Column(
            "override_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("system_signal", sa.Text(), nullable=False),
        sa.Column("override_action", sa.Text(), nullable=False),
        sa.Column(
            "sticky",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revert_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("override_id", name="pk_cmc_risk_overrides"),
    )
    op.execute(
        sa.text(
            "COMMENT ON TABLE public.cmc_risk_overrides IS"
            " 'Discretionary position overrides with sticky/non-sticky support."
            " Full audit trail.'"
        )
    )
    op.create_index(
        "idx_overrides_active",
        "cmc_risk_overrides",
        ["asset_id", "strategy_id"],
        postgresql_where=sa.text("reverted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema -- drop Phase 46 risk control tables in reverse order."""

    op.drop_table("cmc_risk_overrides")
    op.drop_table("cmc_risk_events")
    op.drop_table("dim_risk_state")
    op.drop_table("dim_risk_limits")
