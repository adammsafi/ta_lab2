"""add_mc_ci_to_metrics

Phase 56 Migration 3 of 4: Factor Analytics Reporting

Adds Monte Carlo confidence interval columns to cmc_backtest_metrics
and tearsheet_path to cmc_backtest_runs.

New columns on cmc_backtest_metrics:
  mc_sharpe_lo     -- Monte Carlo 5th percentile Sharpe (95% CI lower bound)
  mc_sharpe_hi     -- Monte Carlo 95th percentile Sharpe (95% CI upper bound)
  mc_sharpe_median -- Monte Carlo median Sharpe
  mc_n_samples     -- Number of Monte Carlo resamples used

New column on cmc_backtest_runs:
  tearsheet_path   -- File path to QuantStats HTML tear sheet

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-02-28 06:25:02.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Monte Carlo CI columns to cmc_backtest_metrics and tearsheet_path to cmc_backtest_runs."""

    # -------------------------------------------------------------------------
    # 1. Add mc_sharpe_lo (nullable NUMERIC)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_backtest_metrics",
        sa.Column("mc_sharpe_lo", sa.Numeric(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_backtest_metrics.mc_sharpe_lo IS"
        " 'Monte Carlo 5th percentile Sharpe ratio (lower bound of 95% CI)."
        " Computed from N=1000 block-bootstrap resamples of daily returns."
        " NULL until computed by Phase 56 MC analyzer.'"
    )

    # -------------------------------------------------------------------------
    # 2. Add mc_sharpe_hi (nullable NUMERIC)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_backtest_metrics",
        sa.Column("mc_sharpe_hi", sa.Numeric(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_backtest_metrics.mc_sharpe_hi IS"
        " 'Monte Carlo 95th percentile Sharpe ratio (upper bound of 95% CI)."
        " Computed from N=1000 block-bootstrap resamples of daily returns."
        " NULL until computed by Phase 56 MC analyzer.'"
    )

    # -------------------------------------------------------------------------
    # 3. Add mc_sharpe_median (nullable NUMERIC)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_backtest_metrics",
        sa.Column("mc_sharpe_median", sa.Numeric(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_backtest_metrics.mc_sharpe_median IS"
        " 'Monte Carlo median Sharpe ratio across all resamples."
        " More robust than point estimate for noisy return series."
        " NULL until computed by Phase 56 MC analyzer.'"
    )

    # -------------------------------------------------------------------------
    # 4. Add mc_n_samples (nullable INTEGER)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_backtest_metrics",
        sa.Column("mc_n_samples", sa.Integer(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_backtest_metrics.mc_n_samples IS"
        " 'Number of Monte Carlo resamples used to compute CI bounds."
        " Typically 1000. NULL until MC analysis is run.'"
    )

    # -------------------------------------------------------------------------
    # 5. Add tearsheet_path to cmc_backtest_runs (nullable TEXT)
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_backtest_runs",
        sa.Column("tearsheet_path", sa.Text(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_backtest_runs.tearsheet_path IS"
        " 'File path to the QuantStats HTML tear sheet generated for this run."
        " Relative to project root or absolute path depending on config."
        " NULL if tear sheet generation was skipped.'"
    )


def downgrade() -> None:
    """Drop Monte Carlo CI columns from cmc_backtest_metrics and tearsheet_path from cmc_backtest_runs."""

    # Drop from cmc_backtest_runs first (dependency order doesn't matter here,
    # but maintaining upgrade-reverse order for clarity)
    op.drop_column("cmc_backtest_runs", "tearsheet_path", schema="public")

    # Drop MC columns from cmc_backtest_metrics (reverse order)
    op.drop_column("cmc_backtest_metrics", "mc_n_samples", schema="public")
    op.drop_column("cmc_backtest_metrics", "mc_sharpe_median", schema="public")
    op.drop_column("cmc_backtest_metrics", "mc_sharpe_hi", schema="public")
    op.drop_column("cmc_backtest_metrics", "mc_sharpe_lo", schema="public")
