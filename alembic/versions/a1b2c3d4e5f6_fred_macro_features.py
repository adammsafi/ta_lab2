"""fred_macro_features

Phase 65: FRED Table & Core Features -- Wave 1 foundation.

Creates fred.fred_macro_features table for storing daily-aligned macro
feature values computed from raw FRED observations in fred.series_values.

Columns include raw FRED series (forward-filled), derived features
(net liquidity, rate spreads, yield curve, VIX regime, dollar strength),
source frequency provenance, and days_since staleness tracking.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f7
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

# -- Revision identifiers --------------------------------------------------
revision = "b3c4d5e6f7a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure fred schema exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS fred")

    # fred.fred_macro_features
    # Stores daily-aligned macro features derived from fred.series_values.
    # Each row = one calendar date with all forward-filled FRED values and
    # derived features (net liquidity, rate spreads, VIX regime, etc.).
    op.create_table(
        "fred_macro_features",
        # Primary key: one row per calendar date
        sa.Column("date", sa.Date(), nullable=False),
        # --- Raw FRED series (forward-filled to daily cadence) ---
        # Federal Reserve balance sheet (weekly, WALCL)
        sa.Column("walcl", sa.Float(), nullable=True),
        # Treasury General Account / TGA (weekly, WTREGEN)
        sa.Column("wtregen", sa.Float(), nullable=True),
        # Overnight Reverse Repo (daily, RRPONTSYD)
        sa.Column("rrpontsyd", sa.Float(), nullable=True),
        # Fed Funds Effective Rate (daily, DFF)
        sa.Column("dff", sa.Float(), nullable=True),
        # 10-Year Treasury Yield (daily, DGS10)
        sa.Column("dgs10", sa.Float(), nullable=True),
        # 10-Year minus 2-Year yield spread (daily, T10Y2Y)
        sa.Column("t10y2y", sa.Float(), nullable=True),
        # CBOE Volatility Index (daily, VIXCLS)
        sa.Column("vixcls", sa.Float(), nullable=True),
        # Trade-Weighted USD Index: Broad (daily, DTWEXBGS)
        sa.Column("dtwexbgs", sa.Float(), nullable=True),
        # ECB Deposit Facility Rate (daily, ECBDFR)
        sa.Column("ecbdfr", sa.Float(), nullable=True),
        # Japan short-term rate (monthly, IRSTCI01JPM156N)
        sa.Column("irstci01jpm156n", sa.Float(), nullable=True),
        # Japan 10-year bond yield (monthly, IRLTLT01JPM156N)
        sa.Column("irltlt01jpm156n", sa.Float(), nullable=True),
        # --- FRED-03: Net liquidity proxy ---
        # WALCL - WTREGEN - RRPONTSYD (billions USD)
        sa.Column("net_liquidity", sa.Float(), nullable=True),
        # --- FRED-04: Rate spreads ---
        # US-Japan short-rate differential (DFF - IRSTCI01JPM156N)
        sa.Column("us_jp_rate_spread", sa.Float(), nullable=True),
        # US-ECB rate differential (DFF - ECBDFR)
        sa.Column("us_ecb_rate_spread", sa.Float(), nullable=True),
        # US-Japan 10Y bond spread (DGS10 - IRLTLT01JPM156N)
        sa.Column("us_jp_10y_spread", sa.Float(), nullable=True),
        # --- FRED-05: Yield curve dynamics ---
        # 5-day change in T10Y2Y spread (yield curve slope change)
        sa.Column("yc_slope_change_5d", sa.Float(), nullable=True),
        # --- FRED-06: VIX regime ---
        # Categorical: 'calm' (<15), 'elevated' (15-25), 'crisis' (>25)
        sa.Column("vix_regime", sa.Text(), nullable=True),
        # --- FRED-07: Dollar strength ---
        # 5-day and 20-day % change in trade-weighted USD index
        sa.Column("dtwexbgs_5d_change", sa.Float(), nullable=True),
        sa.Column("dtwexbgs_20d_change", sa.Float(), nullable=True),
        # --- Provenance: source frequency tracking ---
        # Frequency label for mixed-frequency series (weekly/monthly/daily)
        sa.Column("source_freq_walcl", sa.Text(), nullable=True),
        sa.Column("source_freq_wtregen", sa.Text(), nullable=True),
        sa.Column("source_freq_irstci01jpm156n", sa.Text(), nullable=True),
        sa.Column("source_freq_irltlt01jpm156n", sa.Text(), nullable=True),
        # --- Provenance: staleness tracking ---
        # Days since last actual WALCL/WTREGEN observation (not ffilled value)
        sa.Column("days_since_walcl", sa.Integer(), nullable=True),
        sa.Column("days_since_wtregen", sa.Integer(), nullable=True),
        # --- Metadata ---
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("date"),
        schema="fred",
    )

    # Index: efficient lookup by date descending (most recent features first)
    op.create_index(
        "idx_fred_macro_features_date",
        "fred_macro_features",
        [sa.text("date DESC")],
        schema="fred",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_fred_macro_features_date",
        table_name="fred_macro_features",
        schema="fred",
    )
    op.drop_table("fred_macro_features", schema="fred")
