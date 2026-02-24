"""psr_results_table

Revision ID: 5f8223cfbf06
Revises: adf582a23467
Create Date: 2026-02-23 19:03:36.680051

Creates the psr_results table for storing detailed Probabilistic Sharpe Ratio
(PSR), Deflated Sharpe Ratio (DSR), and Minimum Track Record Length (MinTRL)
formula outputs.

Each row records the full formula inputs/outputs for one backtest run under one
formula_version. The unique constraint on (run_id, formula_version) prevents
duplicate computations.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f8223cfbf06"
down_revision: Union[str, Sequence[str], None] = "adf582a23467"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create psr_results table."""
    op.create_table(
        "psr_results",
        # Primary key
        sa.Column(
            "result_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Foreign key to parent backtest run
        sa.Column("run_id", sa.UUID(), nullable=False),
        # Formula identification
        sa.Column("formula_version", sa.Text(), nullable=False),
        # PSR/DSR/MinTRL outputs
        sa.Column("psr", sa.Numeric(), nullable=True),
        sa.Column("dsr", sa.Numeric(), nullable=True),
        sa.Column("min_trl_bars", sa.Integer(), nullable=True),
        sa.Column("min_trl_days", sa.Integer(), nullable=True),
        # Sharpe ratio inputs/intermediates
        sa.Column("sr_hat", sa.Numeric(), nullable=True),
        sa.Column("sr_star", sa.Numeric(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        # Distributional moments used in formula
        sa.Column("skewness", sa.Numeric(), nullable=True),
        sa.Column("kurtosis_pearson", sa.Numeric(), nullable=True),
        # Return source distinguishes portfolio-level vs trade-reconstruction returns
        sa.Column("return_source", sa.Text(), nullable=True),
        # Audit timestamp
        sa.Column(
            "computed_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("result_id"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["public.cmc_backtest_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id", "formula_version", name="uq_psr_results_run_version"
        ),
        schema="public",
    )

    # Index for fast lookup by run_id
    op.create_index(
        "idx_psr_results_run_id",
        "psr_results",
        ["run_id"],
        schema="public",
    )


def downgrade() -> None:
    """Downgrade schema: drop psr_results table."""
    op.drop_index("idx_psr_results_run_id", table_name="psr_results", schema="public")
    op.drop_table("psr_results", schema="public")
