"""portfolio_tables

Phase 58: Portfolio Construction & Sizing -- Wave 1 foundation.

Creates cmc_portfolio_allocations table for storing optimizer output
and final position weights after bet sizing.

References:
  - Modern Portfolio Theory (Markowitz, 1952)
  - Hierarchical Risk Parity (Lopez de Prado, 2016)
  - CVaR optimization (Rockafellar & Uryasev, 2000)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a1b2c3d4
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# -- Revision identifiers --------------------------------------------------
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # cmc_portfolio_allocations
    # Stores per-asset allocation weights from portfolio optimizer runs.
    # Each row = one optimizer output for (ts, optimizer, asset_id).
    op.create_table(
        "cmc_portfolio_allocations",
        # Primary key
        sa.Column(
            "alloc_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        # When this allocation was computed
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        # Optimizer type: 'mv', 'cvar', 'hrp', 'bl'
        sa.Column("optimizer", sa.Text(), nullable=False),
        # Whether this allocation is the current active one
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Regime label at time of optimization (e.g., 'bear', 'stable', 'uncertain')
        sa.Column("regime_label", sa.Text(), nullable=True),
        # Asset identifier (FK to dim_assets)
        sa.Column("asset_id", sa.Integer(), nullable=False),
        # Raw optimizer weight (pre bet-sizing)
        sa.Column("weight", sa.Numeric(), nullable=False),
        # Final position weight after probability-based bet sizing
        sa.Column("final_weight", sa.Numeric(), nullable=True),
        # Signal score used as BL view or confidence input
        sa.Column("signal_score", sa.Numeric(), nullable=True),
        # Covariance matrix condition number (diagnostic)
        sa.Column("condition_number", sa.Numeric(), nullable=True),
        # Full config snapshot at run time (for reproducibility)
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=True),
        # Ingestion timestamp
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )

    # Unique constraint: one allocation per (ts, optimizer, asset) tuple
    op.create_unique_constraint(
        "uq_portfolio_alloc_ts_opt_asset",
        "cmc_portfolio_allocations",
        ["ts", "optimizer", "asset_id"],
    )

    # Index: efficient lookup by ts descending (most recent allocations)
    op.create_index(
        "idx_portfolio_alloc_ts",
        "cmc_portfolio_allocations",
        [sa.text("ts DESC")],
    )

    # Partial index: lookup of active allocations only
    op.create_index(
        "idx_portfolio_alloc_active",
        "cmc_portfolio_allocations",
        ["ts", "is_active"],
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("idx_portfolio_alloc_active", table_name="cmc_portfolio_allocations")
    op.drop_index("idx_portfolio_alloc_ts", table_name="cmc_portfolio_allocations")
    op.drop_constraint(
        "uq_portfolio_alloc_ts_opt_asset", "cmc_portfolio_allocations", type_="unique"
    )
    op.drop_table("cmc_portfolio_allocations")
