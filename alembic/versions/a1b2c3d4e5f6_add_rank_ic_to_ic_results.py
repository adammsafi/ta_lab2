"""add_rank_ic_to_ic_results

Phase 56 Migration 1 of 4: Factor Analytics Reporting

Adds rank_ic column to cmc_ic_results.
Backfills rank_ic = ic for all existing rows (Spearman IC is already rank-based).

Revision ID: a1b2c3d4e5f6
Revises: 30eac3660488
Create Date: 2026-02-28 06:25:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "30eac3660488"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add rank_ic column to cmc_ic_results and backfill from ic."""

    # -------------------------------------------------------------------------
    # 1. Add rank_ic column (nullable NUMERIC)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_ic_results",
        sa.Column("rank_ic", sa.Numeric(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ic_results.rank_ic IS"
        " 'Spearman rank IC (explicit label for the Spearman IC"
        " already stored in the ic column)."
        " Backfilled from ic on migration; populated independently"
        " by future evaluators that compute rank and Pearson separately.'"
    )

    # -------------------------------------------------------------------------
    # 2. Backfill: rank_ic = ic for all existing rows
    # -------------------------------------------------------------------------
    op.execute("UPDATE public.cmc_ic_results SET rank_ic = ic WHERE rank_ic IS NULL")


def downgrade() -> None:
    """Drop rank_ic column from cmc_ic_results."""

    op.drop_column("cmc_ic_results", "rank_ic", schema="public")
