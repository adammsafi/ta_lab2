"""phase100_meta_filter

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
Create Date: 2026-04-01

Phase 100 Plan 03: ML Signal Combination -- XGBoost Meta-Label Filter.

Adds 3 columns to dim_executor_config that enable a per-config meta-label
confidence filter:

  meta_filter_enabled   BOOLEAN  -- gates the filter on/off per config
  meta_filter_threshold NUMERIC  -- P(trade success) below this = skip trade
  meta_filter_model_path TEXT    -- path to serialized XGBoost model file

All three default to disabled/neutral so existing executor behaviour is
unchanged (meta_filter_enabled defaults to FALSE).

ASCII-only comments throughout (Windows cp1252 safety).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision = "w6x7y8z9a0b1"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # Add meta_filter_enabled -- gate that enables the confidence filter per config.
    # Defaults to FALSE so existing executor configs are unaffected.
    op.add_column(
        "dim_executor_config",
        sa.Column(
            "meta_filter_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )

    # Add meta_filter_threshold -- P(trade success) threshold.
    # Trades with predicted P(success) < threshold are skipped.
    # Default 0.5 (balanced classification boundary).
    op.add_column(
        "dim_executor_config",
        sa.Column(
            "meta_filter_threshold",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
    )

    # Add meta_filter_model_path -- filesystem path to the serialized XGBoost model.
    # NULL means no model loaded (filter will not activate even if enabled=TRUE).
    op.add_column(
        "dim_executor_config",
        sa.Column(
            "meta_filter_model_path",
            sa.Text(),
            nullable=True,
        ),
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_column("dim_executor_config", "meta_filter_model_path")
    op.drop_column("dim_executor_config", "meta_filter_threshold")
    op.drop_column("dim_executor_config", "meta_filter_enabled")
