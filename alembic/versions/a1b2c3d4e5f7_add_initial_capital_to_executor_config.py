"""add_initial_capital_to_executor_config

Phase 63: Tech Debt Cleanup -- wire initial_capital from DB column.

Adds initial_capital column to dim_executor_config so operators can
configure starting portfolio value per strategy without code changes.

Revision ID: a1b2c3d4e5f7
Revises: 3caddeff4691
Create Date: 2026-03-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "3caddeff4691"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dim_executor_config",
        sa.Column(
            "initial_capital",
            sa.Numeric(),
            nullable=True,
            server_default=sa.text("100000"),
        ),
        schema="public",
    )
    op.create_check_constraint(
        "chk_exec_config_initial_capital",
        "dim_executor_config",
        "initial_capital > 0",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_exec_config_initial_capital",
        "dim_executor_config",
        schema="public",
        type_="check",
    )
    op.drop_column("dim_executor_config", "initial_capital", schema="public")
