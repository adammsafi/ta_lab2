"""add_mae_mfe_to_trades

Phase 56 Migration 2 of 4: Factor Analytics Reporting

Adds mae and mfe columns to cmc_backtest_trades.
mae = Maximum Adverse Excursion (worst intra-trade return vs entry price).
mfe = Maximum Favorable Excursion (best intra-trade return vs entry price).

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-02-28 06:25:01.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add mae and mfe columns to cmc_backtest_trades."""

    # -------------------------------------------------------------------------
    # 1. Add mae column (nullable NUMERIC)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_backtest_trades",
        sa.Column("mae", sa.Numeric(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_backtest_trades.mae IS"
        " 'Maximum Adverse Excursion: worst intra-trade return vs entry price."
        " Expressed as a decimal fraction (e.g. -0.05 = -5%)."
        " NULL until computed by the MAE/MFE analyzer in Phase 56.'"
    )

    # -------------------------------------------------------------------------
    # 2. Add mfe column (nullable NUMERIC)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_backtest_trades",
        sa.Column("mfe", sa.Numeric(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_backtest_trades.mfe IS"
        " 'Maximum Favorable Excursion: best intra-trade return vs entry price."
        " Expressed as a decimal fraction (e.g. 0.10 = +10%)."
        " NULL until computed by the MAE/MFE analyzer in Phase 56.'"
    )


def downgrade() -> None:
    """Drop mae and mfe columns from cmc_backtest_trades."""

    op.drop_column("cmc_backtest_trades", "mfe", schema="public")
    op.drop_column("cmc_backtest_trades", "mae", schema="public")
