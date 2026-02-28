"""add_cs_norms_to_features

Phase 56 Migration 4 of 4: Factor Analytics Reporting

Adds 6 cross-sectional normalization columns to cmc_features.
CS-norms are computed PARTITION BY (ts, tf) across all assets at each timestamp.

New columns:
  ret_arith_cs_zscore    -- CS z-score of ret_arith
  ret_arith_cs_rank      -- CS percentile rank of ret_arith [0,1]
  rsi_14_cs_zscore       -- CS z-score of rsi_14
  rsi_14_cs_rank         -- CS percentile rank of rsi_14 [0,1]
  vol_parkinson_20_cs_zscore -- CS z-score of vol_parkinson_20
  vol_parkinson_20_cs_rank   -- CS percentile rank of vol_parkinson_20 [0,1]

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-02-28 06:25:03.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 6 cross-sectional normalization columns to cmc_features."""

    # -------------------------------------------------------------------------
    # ret_arith cross-sectional columns
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_features",
        sa.Column("ret_arith_cs_zscore", sa.Float(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_features.ret_arith_cs_zscore IS"
        " 'Cross-sectional z-score of ret_arith."
        " Computed PARTITION BY (ts, tf) across all assets at each timestamp."
        " z = (ret_arith - mean) / std. NULL when fewer than 3 assets have data.'"
    )

    op.add_column(
        "cmc_features",
        sa.Column("ret_arith_cs_rank", sa.Float(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_features.ret_arith_cs_rank IS"
        " 'Cross-sectional percentile rank of ret_arith in [0, 1]."
        " Computed PARTITION BY (ts, tf) via scipy.stats.rankdata with method=average."
        " 1.0 = highest return in cross-section. NULL when fewer than 3 assets have data.'"
    )

    # -------------------------------------------------------------------------
    # rsi_14 cross-sectional columns
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_features",
        sa.Column("rsi_14_cs_zscore", sa.Float(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_features.rsi_14_cs_zscore IS"
        " 'Cross-sectional z-score of rsi_14."
        " Computed PARTITION BY (ts, tf) across all assets at each timestamp."
        " z = (rsi_14 - mean) / std. NULL when fewer than 3 assets have data.'"
    )

    op.add_column(
        "cmc_features",
        sa.Column("rsi_14_cs_rank", sa.Float(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_features.rsi_14_cs_rank IS"
        " 'Cross-sectional percentile rank of rsi_14 in [0, 1]."
        " Computed PARTITION BY (ts, tf) via scipy.stats.rankdata with method=average."
        " 1.0 = highest RSI in cross-section. NULL when fewer than 3 assets have data.'"
    )

    # -------------------------------------------------------------------------
    # vol_parkinson_20 cross-sectional columns
    # -------------------------------------------------------------------------
    op.add_column(
        "cmc_features",
        sa.Column("vol_parkinson_20_cs_zscore", sa.Float(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_features.vol_parkinson_20_cs_zscore IS"
        " 'Cross-sectional z-score of vol_parkinson_20."
        " Computed PARTITION BY (ts, tf) across all assets at each timestamp."
        " z = (vol_parkinson_20 - mean) / std. NULL when fewer than 3 assets have data.'"
    )

    op.add_column(
        "cmc_features",
        sa.Column("vol_parkinson_20_cs_rank", sa.Float(), nullable=True),
        schema="public",
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_features.vol_parkinson_20_cs_rank IS"
        " 'Cross-sectional percentile rank of vol_parkinson_20 in [0, 1]."
        " Computed PARTITION BY (ts, tf) via scipy.stats.rankdata with method=average."
        " 1.0 = highest vol in cross-section. NULL when fewer than 3 assets have data.'"
    )


def downgrade() -> None:
    """Drop 6 cross-sectional normalization columns from cmc_features."""

    # Drop in reverse order of addition
    op.drop_column("cmc_features", "vol_parkinson_20_cs_rank", schema="public")
    op.drop_column("cmc_features", "vol_parkinson_20_cs_zscore", schema="public")
    op.drop_column("cmc_features", "rsi_14_cs_rank", schema="public")
    op.drop_column("cmc_features", "rsi_14_cs_zscore", schema="public")
    op.drop_column("cmc_features", "ret_arith_cs_rank", schema="public")
    op.drop_column("cmc_features", "ret_arith_cs_zscore", schema="public")
