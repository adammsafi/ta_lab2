"""loss_limits_policy

Schema changes for Phase 48 (Loss Limits Policy):

1. ALTER dim_risk_limits: add pool_name TEXT column with CHECK constraint
2. ALTER cmc_risk_overrides: add reason_category, expires_at, extended_at columns

Revision ID: 328fdc315e1b
Revises: ac4cf1223ec7
Create Date: 2026-02-25 15:26:01.665488

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "328fdc315e1b"
down_revision: Union[str, Sequence[str], None] = "ac4cf1223ec7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add pool_name column to dim_risk_limits
    op.add_column("dim_risk_limits", sa.Column("pool_name", sa.Text(), nullable=True))
    op.execute(
        """
        ALTER TABLE public.dim_risk_limits
        ADD CONSTRAINT chk_risk_limits_pool
        CHECK (pool_name IS NULL OR pool_name IN (
            'conservative', 'core', 'opportunistic', 'aggregate'
        ))
    """
    )

    # 2. Add override governance columns to cmc_risk_overrides
    op.add_column(
        "cmc_risk_overrides",
        sa.Column("reason_category", sa.Text(), nullable=True),
    )
    op.add_column(
        "cmc_risk_overrides",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cmc_risk_overrides",
        sa.Column("extended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_overrides
        ADD CONSTRAINT chk_overrides_reason_cat
        CHECK (reason_category IS NULL OR reason_category IN (
            'market_condition', 'strategy_review', 'technical_issue',
            'manual_risk_reduction', 'testing'
        ))
    """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse order
    op.execute(
        "ALTER TABLE public.cmc_risk_overrides "
        "DROP CONSTRAINT IF EXISTS chk_overrides_reason_cat"
    )
    op.drop_column("cmc_risk_overrides", "extended_at")
    op.drop_column("cmc_risk_overrides", "expires_at")
    op.drop_column("cmc_risk_overrides", "reason_category")
    op.execute(
        "ALTER TABLE public.dim_risk_limits "
        "DROP CONSTRAINT IF EXISTS chk_risk_limits_pool"
    )
    op.drop_column("dim_risk_limits", "pool_name")
