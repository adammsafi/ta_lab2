"""cross_asset_aggregation_tables

Phase 70: Cross-Asset Aggregation -- Wave 1 foundation.

Creates three tables for cross-asset signal computation and storage,
plus adds a crypto_macro_corr column to cmc_macro_regimes:

1. cmc_cross_asset_agg: Daily crypto-wide market metrics.
   Stores BTC/ETH 30d correlation, average pairwise correlation across
   all crypto assets, a high-correlation flag (>0.7 = macro-driven market),
   and the asset count used for computation.
   PK: (date).

2. cmc_funding_rate_agg: Aggregate funding rate signal per symbol per date.
   Stores simple average and VWAP of funding rates across venues, 30d and
   90d z-scores, and the list of venues included in that day's aggregate.
   PK: (date, symbol).

3. crypto_macro_corr_regimes: Rolling crypto-macro correlation per asset per
   macro variable. Tracks 60d rolling correlation, prior day value, sign-flip
   detection, and a qualitative regime label. No cmc_ prefix: mixes crypto
   assets with non-crypto (FRED) macro variables.
   PK: (date, asset_id, macro_var).

ALTER TABLE cmc_macro_regimes: Adds nullable TEXT column crypto_macro_corr
for storing the daily crypto-macro correlation regime label
('correlated', 'decorrelated', 'flipping') alongside monetary/liquidity/
risk_appetite/carry labels.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: e1f2a3b4c5d6
Revises: f1a2b3c4d5e6
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

# -- Revision identifiers --------------------------------------------------
revision = "e1f2a3b4c5d6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Table 1: cmc_cross_asset_agg ──────────────────────────────────────
    # Daily crypto-wide market metrics. One row per calendar date.
    # Assets come from both cmc_price_histories7 and tvc_price_histories.
    # cmc_ prefix used because primary asset source is cmc_price_histories7.
    op.create_table(
        "cmc_cross_asset_agg",
        # Primary key
        sa.Column("date", sa.Date(), nullable=False),
        # BTC/ETH 30-day rolling Pearson correlation
        sa.Column("btc_eth_corr_30d", sa.Float(), nullable=True),
        # Average pairwise correlation across all tracked crypto assets (30d window)
        sa.Column("avg_pairwise_corr_30d", sa.Float(), nullable=True),
        # True when avg_pairwise_corr_30d > high_corr_threshold (YAML-configurable)
        # Signals macro-driven market where diversification benefit is reduced
        sa.Column("high_corr_flag", sa.Boolean(), nullable=True),
        # Number of assets included in avg_pairwise_corr_30d computation
        sa.Column("n_assets", sa.Integer(), nullable=True),
        # Metadata
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("date"),
    )

    # Index: most recent dates first for efficient lookback queries
    op.create_index(
        "idx_cmc_cross_asset_agg_date",
        "cmc_cross_asset_agg",
        [sa.text("date DESC")],
    )

    # ── Table 2: cmc_funding_rate_agg ─────────────────────────────────────
    # Aggregate funding rate signal per symbol per date.
    # Source: cmc_funding_rates (multi-venue perpetual funding rates).
    # Stores simple average (always available) and VWAP (when volume exists).
    op.create_table(
        "cmc_funding_rate_agg",
        # Primary key columns
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        # Simple average of funding rates across venues (NaN venues excluded)
        sa.Column("avg_funding_rate", sa.Float(), nullable=True),
        # Volume-weighted average of funding rates (nullable: requires volume data)
        sa.Column("vwap_funding_rate", sa.Float(), nullable=True),
        # Number of venues contributing to today's aggregate
        sa.Column("n_venues", sa.Integer(), nullable=True),
        # 30-day rolling z-score of avg_funding_rate (primary signal)
        sa.Column("zscore_30d", sa.Float(), nullable=True),
        # 90-day rolling z-score of avg_funding_rate (secondary signal)
        sa.Column("zscore_90d", sa.Float(), nullable=True),
        # Comma-separated list of venues included, e.g. 'binance,bybit,hyperliquid'
        sa.Column("venues_included", sa.Text(), nullable=True),
        # Metadata
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("date", "symbol"),
    )

    # Index: per-symbol time-series queries (most recent first)
    op.create_index(
        "idx_cmc_funding_rate_agg_symbol",
        "cmc_funding_rate_agg",
        ["symbol", sa.text("date DESC")],
    )

    # ── Table 3: crypto_macro_corr_regimes ────────────────────────────────
    # Rolling crypto-macro correlation per asset per macro variable.
    # No cmc_ prefix: mixes crypto assets with non-crypto (FRED) macro data.
    # Macro variables: VIX, DXY, HY OAS, net_liquidity (4 from fred_macro_features).
    op.create_table(
        "crypto_macro_corr_regimes",
        # Primary key columns
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        # Macro variable label: 'vix', 'dxy', 'hy_oas', 'net_liquidity'
        sa.Column("macro_var", sa.Text(), nullable=False),
        # 60-day rolling Pearson correlation between asset return and macro variable
        sa.Column("corr_60d", sa.Float(), nullable=True),
        # Prior day's 60d correlation (for sign-flip detection)
        sa.Column("prev_corr_60d", sa.Float(), nullable=True),
        # True when correlation flips sign with |magnitude| > sign_flip_threshold (YAML)
        # e.g., corr crosses from >0.3 to <-0.3 or vice versa
        sa.Column(
            "sign_flip_flag", sa.Boolean(), nullable=True, server_default="FALSE"
        ),
        # Qualitative regime label: 'correlated', 'decorrelated', 'flipping'
        sa.Column("corr_regime", sa.Text(), nullable=True),
        # Metadata
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("date", "asset_id", "macro_var"),
    )

    # Index: per-asset time-series queries (most recent first)
    op.create_index(
        "idx_crypto_macro_corr_regimes_asset",
        "crypto_macro_corr_regimes",
        ["asset_id", sa.text("date DESC")],
    )

    # Partial index: fast retrieval of sign-flip events only
    op.create_index(
        "idx_crypto_macro_corr_regimes_flip",
        "crypto_macro_corr_regimes",
        ["sign_flip_flag"],
        postgresql_where=sa.text("sign_flip_flag = TRUE"),
    )

    # ── ALTER TABLE: cmc_macro_regimes ────────────────────────────────────
    # Add nullable crypto_macro_corr column to store the daily crypto-macro
    # correlation regime label alongside existing dimension labels.
    # Labels: 'correlated', 'decorrelated', 'flipping'
    # Nullable with no default: populated by Phase 70 cross-asset aggregation writer.
    op.add_column(
        "cmc_macro_regimes",
        sa.Column("crypto_macro_corr", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Remove ALTER TABLE change first
    op.drop_column("cmc_macro_regimes", "crypto_macro_corr")

    # Drop indexes and tables in reverse order of creation
    op.drop_index(
        "idx_crypto_macro_corr_regimes_flip",
        table_name="crypto_macro_corr_regimes",
    )
    op.drop_index(
        "idx_crypto_macro_corr_regimes_asset",
        table_name="crypto_macro_corr_regimes",
    )
    op.drop_table("crypto_macro_corr_regimes")

    op.drop_index(
        "idx_cmc_funding_rate_agg_symbol",
        table_name="cmc_funding_rate_agg",
    )
    op.drop_table("cmc_funding_rate_agg")

    op.drop_index(
        "idx_cmc_cross_asset_agg_date",
        table_name="cmc_cross_asset_agg",
    )
    op.drop_table("cmc_cross_asset_agg")
