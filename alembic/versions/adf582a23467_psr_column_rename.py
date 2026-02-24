"""psr_column_rename

Revision ID: adf582a23467
Revises: 25f2b3c90f65
Create Date: 2026-02-23 19:02:19.163040

Conditionally renames the existing `psr` column on cmc_backtest_metrics to
`psr_legacy`, then adds a new nullable `psr` column.

If `psr` column does not exist (fresh install path), adds `psr_legacy` as a
new nullable column and still adds the new `psr` column.

Downgrade unconditionally drops both columns (IF EXISTS) so that the table
returns to its exact pre-migration state regardless of which upgrade branch ran.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "adf582a23467"
down_revision: Union[str, Sequence[str], None] = "25f2b3c90f65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    """Return True if *column_name* exists on *table_name* in the public schema."""
    result = bind.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = :tbl "
            "AND column_name = :col"
        ),
        {"tbl": table_name, "col": column_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    """Upgrade schema: rename psr -> psr_legacy (if it exists), add new psr column."""
    bind = op.get_bind()

    if _column_exists(bind, "cmc_backtest_metrics", "psr"):
        # Rename the existing psr column to psr_legacy to preserve historical data.
        op.alter_column(
            "cmc_backtest_metrics",
            "psr",
            new_column_name="psr_legacy",
            schema="public",
        )
    else:
        # No psr column in DB (e.g. fresh install after psr was removed from DDL).
        # Add psr_legacy as empty placeholder so the schema is consistent.
        op.add_column(
            "cmc_backtest_metrics",
            sa.Column("psr_legacy", sa.Numeric(), nullable=True),
            schema="public",
        )

    # Always add the new nullable psr column (used by upcoming PSR formula code).
    op.add_column(
        "cmc_backtest_metrics",
        sa.Column("psr", sa.Numeric(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    """Downgrade schema: unconditionally drop both psr and psr_legacy columns.

    Uses IF EXISTS so the statement is safe regardless of which upgrade branch ran.
    We do NOT rename psr_legacy back to psr -- that would create a phantom column
    that never existed before this migration (the pre-migration state had no psr
    column because the live DB schema was created without one).
    """
    op.execute("ALTER TABLE public.cmc_backtest_metrics DROP COLUMN IF EXISTS psr")
    op.execute(
        "ALTER TABLE public.cmc_backtest_metrics DROP COLUMN IF EXISTS psr_legacy"
    )
