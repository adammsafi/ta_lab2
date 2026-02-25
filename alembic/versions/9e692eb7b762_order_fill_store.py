"""order_fill_store

Revision ID: 9e692eb7b762
Revises: b180d8d07a85
Create Date: 2026-02-24 23:40:23.878950

Phase 44: Order and Fill Store
Creates 5 tables and 1 view for the paper trading OMS persistence layer.
Tables: cmc_orders, cmc_fills, cmc_positions, cmc_order_events, cmc_order_dead_letter
View: v_cmc_positions_agg

Note: All comments use ASCII only (Windows cp1252 compatibility).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e692eb7b762"
down_revision: Union[str, Sequence[str], None] = "b180d8d07a85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema -- create Phase 44 OMS tables and aggregate view."""

    # ------------------------------------------------------------------
    # 1. cmc_orders: master order record, one row per order lifecycle
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_orders",
        sa.Column(
            "order_id",
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
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "paper_order_uuid",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("limit_price", sa.Numeric(), nullable=True),
        sa.Column("stop_price", sa.Numeric(), nullable=True),
        sa.Column("time_in_force", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'created'"),
            nullable=False,
        ),
        sa.Column(
            "filled_qty",
            sa.Numeric(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("remaining_qty", sa.Numeric(), nullable=False),
        sa.Column("avg_fill_price", sa.Numeric(), nullable=True),
        sa.Column(
            "environment",
            sa.Text(),
            server_default=sa.text("'sandbox'"),
            nullable=False,
        ),
        sa.Column("client_order_id", sa.Text(), nullable=True),
        sa.Column("exchange_order_id", sa.Text(), nullable=True),
        # Primary key
        sa.PrimaryKeyConstraint("order_id", name="pk_cmc_orders"),
        # Check constraints
        sa.CheckConstraint("side IN ('buy', 'sell')", name="chk_orders_side"),
        sa.CheckConstraint(
            "order_type IN ('market', 'limit', 'stop')", name="chk_orders_order_type"
        ),
        sa.CheckConstraint(
            "status IN ('created', 'submitted', 'partial_fill', 'filled', 'cancelled', 'rejected', 'expired')",
            name="chk_orders_status",
        ),
        sa.CheckConstraint(
            "time_in_force IS NULL OR time_in_force IN ('GTC', 'GTD', 'IOC')",
            name="chk_orders_tif",
        ),
        sa.CheckConstraint(
            "environment IN ('sandbox', 'production')", name="chk_orders_environment"
        ),
        sa.CheckConstraint("quantity > 0", name="chk_orders_quantity_pos"),
        sa.CheckConstraint("remaining_qty >= 0", name="chk_orders_remaining_nn"),
        schema="public",
    )

    # Indexes on cmc_orders
    op.create_index(
        "idx_orders_asset_status",
        "cmc_orders",
        ["asset_id", "status", sa.text("created_at DESC")],
        schema="public",
    )
    op.create_index(
        "idx_orders_signal",
        "cmc_orders",
        ["signal_id"],
        schema="public",
        postgresql_where=sa.text("signal_id IS NOT NULL"),
    )
    op.create_index(
        "idx_orders_paper_order",
        "cmc_orders",
        ["paper_order_uuid"],
        schema="public",
        postgresql_where=sa.text("paper_order_uuid IS NOT NULL"),
    )
    op.create_index(
        "idx_orders_exchange_order",
        "cmc_orders",
        ["exchange_order_id"],
        schema="public",
        postgresql_where=sa.text("exchange_order_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 2. cmc_fills: individual fill events, FK to cmc_orders
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_fills",
        sa.Column(
            "fill_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "filled_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("cmc_orders.order_id", name="fk_fills_order_id"),
            nullable=False,
        ),
        sa.Column("fill_qty", sa.Numeric(), nullable=False),
        sa.Column("fill_price", sa.Numeric(), nullable=False),
        sa.Column(
            "fee_amount",
            sa.Numeric(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("fee_currency", sa.Text(), nullable=True),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("exchange_fill_id", sa.Text(), nullable=True),
        sa.Column(
            "lot_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Primary key
        sa.PrimaryKeyConstraint("fill_id", name="pk_cmc_fills"),
        # Check constraints
        sa.CheckConstraint("side IN ('buy', 'sell')", name="chk_fills_side"),
        sa.CheckConstraint("fill_qty > 0", name="chk_fills_qty_pos"),
        sa.CheckConstraint("fill_price > 0", name="chk_fills_price_pos"),
        sa.CheckConstraint("fee_amount >= 0", name="chk_fills_fee_nn"),
        schema="public",
    )

    # Indexes on cmc_fills
    op.create_index(
        "idx_fills_order_id",
        "cmc_fills",
        ["order_id", "filled_at"],
        schema="public",
    )
    op.create_index(
        "idx_fills_exchange_fill",
        "cmc_fills",
        ["exchange_fill_id"],
        schema="public",
        postgresql_where=sa.text("exchange_fill_id IS NOT NULL"),
    )
    op.create_index(
        "idx_fills_filled_at",
        "cmc_fills",
        [sa.text("filled_at DESC")],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 3. cmc_positions: current position per asset+exchange
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_positions",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "avg_cost_basis",
            sa.Numeric(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "realized_pnl",
            sa.Numeric(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("unrealized_pnl", sa.Numeric(), nullable=True),
        sa.Column("unrealized_pnl_pct", sa.Numeric(), nullable=True),
        sa.Column("last_mark_price", sa.Numeric(), nullable=True),
        sa.Column("last_mark_ts", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "last_fill_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "last_updated",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Composite primary key
        sa.PrimaryKeyConstraint("asset_id", "exchange", name="pk_cmc_positions"),
        # Check constraint on exchange values
        sa.CheckConstraint(
            "exchange IN ('coinbase', 'kraken', 'paper', 'aggregate')",
            name="chk_positions_exchange",
        ),
        schema="public",
    )

    # Index on cmc_positions
    op.create_index(
        "idx_positions_asset",
        "cmc_positions",
        ["asset_id"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 4. cmc_order_events: state machine transition audit trail
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_order_events",
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
        sa.Column(
            "order_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("cmc_orders.order_id", name="fk_events_order_id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "fill_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        # Primary key
        sa.PrimaryKeyConstraint("event_id", name="pk_cmc_order_events"),
        # Check constraint matches same 7 valid statuses as cmc_orders
        sa.CheckConstraint(
            "to_status IN ('created', 'submitted', 'partial_fill', 'filled', 'cancelled', 'rejected', 'expired')",
            name="chk_events_to_status",
        ),
        schema="public",
    )

    # Indexes on cmc_order_events
    op.create_index(
        "idx_events_order_id",
        "cmc_order_events",
        ["order_id", "event_ts"],
        schema="public",
    )
    op.create_index(
        "idx_events_ts",
        "cmc_order_events",
        [sa.text("event_ts DESC")],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 5. cmc_order_dead_letter: failed operations for retry/inspection
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_order_dead_letter",
        sa.Column(
            "dlq_id",
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
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column(
            "order_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "fill_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("error_reason", sa.Text(), nullable=False),
        sa.Column("error_stacktrace", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "retry_after",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Primary key
        sa.PrimaryKeyConstraint("dlq_id", name="pk_cmc_order_dead_letter"),
        # Check constraints
        sa.CheckConstraint(
            "operation_type IN ('process_fill', 'promote_order', 'update_position', 'other')",
            name="chk_dlq_operation",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'retrying', 'succeeded', 'abandoned')",
            name="chk_dlq_status",
        ),
        schema="public",
    )

    # Indexes on cmc_order_dead_letter
    op.create_index(
        "idx_dlq_status_retry",
        "cmc_order_dead_letter",
        ["status", "retry_after"],
        schema="public",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_dlq_order_id",
        "cmc_order_dead_letter",
        ["order_id"],
        schema="public",
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )
    op.create_index(
        "idx_dlq_created_at",
        "cmc_order_dead_letter",
        [sa.text("created_at DESC")],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 6. v_cmc_positions_agg: aggregate positions across exchanges
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW public.v_cmc_positions_agg AS
        SELECT
            asset_id,
            'aggregate'::TEXT AS exchange,
            SUM(quantity) AS quantity,
            CASE
                WHEN SUM(ABS(quantity)) = 0 THEN 0
                ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
            END AS avg_cost_basis,
            SUM(realized_pnl) AS realized_pnl,
            SUM(COALESCE(unrealized_pnl, 0)) AS unrealized_pnl,
            MAX(last_mark_price) AS last_mark_price,
            MAX(last_updated) AS last_updated
        FROM public.cmc_positions
        WHERE exchange != 'aggregate'
        GROUP BY asset_id
        """
    )


def downgrade() -> None:
    """Downgrade schema -- drop Phase 44 OMS tables and aggregate view."""

    # Drop in reverse dependency order
    op.execute("DROP VIEW IF EXISTS public.v_cmc_positions_agg")
    op.drop_table("cmc_order_dead_letter", schema="public")
    op.drop_table("cmc_order_events", schema="public")
    op.drop_table("cmc_positions", schema="public")
    op.drop_table("cmc_fills", schema="public")
    op.drop_table("cmc_orders", schema="public")
