"""add experiment_name to strategy_bakeoff_results

Revision ID: 440fdfb3e8e1
Revises: i3j4k5l6m7n8
Create Date: 2026-03-22 15:55:46.056354

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "440fdfb3e8e1"
down_revision: Union[str, Sequence[str], None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add experiment_name column to strategy_bakeoff_results for lineage tracking."""
    op.add_column(
        "strategy_bakeoff_results",
        sa.Column("experiment_name", sa.String(128), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    """Remove experiment_name column from strategy_bakeoff_results."""
    op.drop_column("strategy_bakeoff_results", "experiment_name", schema="public")
