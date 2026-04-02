"""Phase 97 FRED Macro Expansion: US Equity Index columns.

Adds 27 new columns to fred.fred_macro_features:
  - 3 raw series columns: sp500, nasdaqcom, djia
  - 24 derived feature columns (8 per series x 3 series):
    returns (1d/5d/21d/63d), vol_21d, drawdown_pct,
    ma_ratio_50_200d, zscore_252d

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

# -- Revision identifiers --------------------------------------------------
revision = "p0q1r2s3t4u5"
down_revision = "o9p0q1r2s3t4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Phase 97: SP500 raw + derived ─────────────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_ret_1d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_ret_5d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_ret_21d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_ret_63d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_vol_21d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_drawdown_pct", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_ma_ratio_50_200d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("sp500_zscore_252d", sa.Float(), nullable=True),
        schema="fred",
    )

    # ── Phase 97: NASDAQCOM raw + derived ─────────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_ret_1d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_ret_5d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_ret_21d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_ret_63d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_vol_21d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_drawdown_pct", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_ma_ratio_50_200d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nasdaqcom_zscore_252d", sa.Float(), nullable=True),
        schema="fred",
    )

    # ── Phase 97: DJIA raw + derived ──────────────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("djia", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_ret_1d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_ret_5d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_ret_21d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_ret_63d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_vol_21d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_drawdown_pct", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_ma_ratio_50_200d", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("djia_zscore_252d", sa.Float(), nullable=True),
        schema="fred",
    )


def downgrade() -> None:
    # ── Drop DJIA derived + raw ────────────────────────────────────────────
    op.drop_column("fred_macro_features", "djia_zscore_252d", schema="fred")
    op.drop_column("fred_macro_features", "djia_ma_ratio_50_200d", schema="fred")
    op.drop_column("fred_macro_features", "djia_drawdown_pct", schema="fred")
    op.drop_column("fred_macro_features", "djia_vol_21d", schema="fred")
    op.drop_column("fred_macro_features", "djia_ret_63d", schema="fred")
    op.drop_column("fred_macro_features", "djia_ret_21d", schema="fred")
    op.drop_column("fred_macro_features", "djia_ret_5d", schema="fred")
    op.drop_column("fred_macro_features", "djia_ret_1d", schema="fred")
    op.drop_column("fred_macro_features", "djia", schema="fred")

    # ── Drop NASDAQCOM derived + raw ──────────────────────────────────────
    op.drop_column("fred_macro_features", "nasdaqcom_zscore_252d", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom_ma_ratio_50_200d", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom_drawdown_pct", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom_vol_21d", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom_ret_63d", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom_ret_21d", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom_ret_5d", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom_ret_1d", schema="fred")
    op.drop_column("fred_macro_features", "nasdaqcom", schema="fred")

    # ── Drop SP500 derived + raw ───────────────────────────────────────────
    op.drop_column("fred_macro_features", "sp500_zscore_252d", schema="fred")
    op.drop_column("fred_macro_features", "sp500_ma_ratio_50_200d", schema="fred")
    op.drop_column("fred_macro_features", "sp500_drawdown_pct", schema="fred")
    op.drop_column("fred_macro_features", "sp500_vol_21d", schema="fred")
    op.drop_column("fred_macro_features", "sp500_ret_63d", schema="fred")
    op.drop_column("fred_macro_features", "sp500_ret_21d", schema="fred")
    op.drop_column("fred_macro_features", "sp500_ret_5d", schema="fred")
    op.drop_column("fred_macro_features", "sp500_ret_1d", schema="fred")
    op.drop_column("fred_macro_features", "sp500", schema="fred")
