"""ic_results_table

Revision ID: c3b718c2d088
Revises: 5f8223cfbf06
Create Date: 2026-02-23 21:00:50.428642

Creates the cmc_ic_results table for storing Information Coefficient (IC)
evaluation results. Each row records the IC of a single feature against a
forward return horizon in a specific regime slice over a bounded training window.

The unique constraint on the 9-column natural key prevents duplicate computations
and enables upsert semantics (compute only what changed).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3b718c2d088"
down_revision: Union[str, Sequence[str], None] = "5f8223cfbf06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create cmc_ic_results table."""
    op.create_table(
        "cmc_ic_results",
        # Primary key -- UUID generated server-side
        sa.Column(
            "result_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Asset + timeframe
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        # Feature name (column name from cmc_features)
        sa.Column("feature", sa.Text(), nullable=False),
        # Forward return horizon in bars
        sa.Column("horizon", sa.Integer(), nullable=False),
        # Forward return horizon in calendar days (horizon * tf_days_nominal), nullable
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        # Return type: 'arith' or 'log'
        sa.Column("return_type", sa.Text(), nullable=False),
        # Regime slice key: 'trend_state', 'vol_state', or 'all'
        sa.Column("regime_col", sa.Text(), nullable=False),
        # Regime slice label: e.g. 'Up', 'High', 'all'
        sa.Column("regime_label", sa.Text(), nullable=False),
        # Training window bounds (inclusive)
        sa.Column("train_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("train_end", sa.TIMESTAMP(timezone=True), nullable=False),
        # IC outputs -- nullable because some windows may lack sufficient data
        sa.Column("ic", sa.Numeric(), nullable=True),
        sa.Column("ic_t_stat", sa.Numeric(), nullable=True),
        sa.Column("ic_p_value", sa.Numeric(), nullable=True),
        sa.Column("ic_ir", sa.Numeric(), nullable=True),
        sa.Column("ic_ir_t_stat", sa.Numeric(), nullable=True),
        sa.Column("turnover", sa.Numeric(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        # Audit timestamp
        sa.Column(
            "computed_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint(
            "asset_id",
            "tf",
            "feature",
            "horizon",
            "return_type",
            "regime_col",
            "regime_label",
            "train_start",
            "train_end",
            name="uq_ic_results_key",
        ),
        schema="public",
    )

    # Index for fast lookup by asset + timeframe + feature
    op.create_index(
        "idx_ic_results_asset_feature",
        "cmc_ic_results",
        ["asset_id", "tf", "feature"],
        schema="public",
    )

    # Index for time-based queries and freshness checks
    op.create_index(
        "idx_ic_results_computed_at",
        "cmc_ic_results",
        ["computed_at"],
        schema="public",
    )


def downgrade() -> None:
    """Downgrade schema: drop cmc_ic_results table."""
    op.drop_index(
        "idx_ic_results_computed_at", table_name="cmc_ic_results", schema="public"
    )
    op.drop_index(
        "idx_ic_results_asset_feature", table_name="cmc_ic_results", schema="public"
    )
    op.drop_table("cmc_ic_results", schema="public")
