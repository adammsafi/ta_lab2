"""fred_phase66_derived_columns

Phase 66: FRED Derived Features & Automation -- Wave 1 foundation.

Adds 25 new columns to fred.fred_macro_features:
  - 7 raw series columns (forward-filled FRED values)
  - 18 derived feature columns (FRED-08 through FRED-16)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

# -- Revision identifiers --------------------------------------------------
revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── FRED-08: Credit stress (BAMLH0A0HYM2) ──────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("bamlh0a0hym2", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("hy_oas_level", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("hy_oas_5d_change", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("hy_oas_30d_zscore", sa.Float(), nullable=True),
        schema="fred",
    )

    # ── FRED-09: Financial conditions (NFCI) ────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("nfci", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nfci_level", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("nfci_4wk_direction", sa.Text(), nullable=True),
        schema="fred",
    )

    # ── FRED-10: M2 money supply (M2SL) ─────────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("m2sl", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("m2_yoy_pct", sa.Float(), nullable=True),
        schema="fred",
    )

    # ── FRED-11: Carry trade FX (DEXJPUS) ───────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("dexjpus", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("dexjpus_level", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("dexjpus_5d_pct_change", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("dexjpus_20d_vol", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("dexjpus_daily_zscore", sa.Float(), nullable=True),
        schema="fred",
    )

    # ── FRED-12: Net liquidity z-score + trend ──────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("net_liquidity_365d_zscore", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("net_liquidity_trend", sa.Text(), nullable=True),
        schema="fred",
    )

    # ── FRED-13: Fed regime classification ──────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("dfedtaru", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("dfedtarl", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("fed_regime_structure", sa.Text(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("fed_regime_trajectory", sa.Text(), nullable=True),
        schema="fred",
    )

    # ── FRED-14: Carry momentum indicator ───────────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("carry_momentum", sa.Float(), nullable=True),
        schema="fred",
    )

    # ── FRED-15: CPI surprise proxy (CPIAUCSL) ─────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("cpiaucsl", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("cpi_surprise_proxy", sa.Float(), nullable=True),
        schema="fred",
    )

    # ── FRED-16: Fed target midpoint and spread ─────────────────────────
    op.add_column(
        "fred_macro_features",
        sa.Column("target_mid", sa.Float(), nullable=True),
        schema="fred",
    )
    op.add_column(
        "fred_macro_features",
        sa.Column("target_spread", sa.Float(), nullable=True),
        schema="fred",
    )


def downgrade() -> None:
    # Drop in reverse order of addition

    # ── FRED-16 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "target_spread", schema="fred")
    op.drop_column("fred_macro_features", "target_mid", schema="fred")

    # ── FRED-15 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "cpi_surprise_proxy", schema="fred")
    op.drop_column("fred_macro_features", "cpiaucsl", schema="fred")

    # ── FRED-14 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "carry_momentum", schema="fred")

    # ── FRED-13 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "fed_regime_trajectory", schema="fred")
    op.drop_column("fred_macro_features", "fed_regime_structure", schema="fred")
    op.drop_column("fred_macro_features", "dfedtarl", schema="fred")
    op.drop_column("fred_macro_features", "dfedtaru", schema="fred")

    # ── FRED-12 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "net_liquidity_trend", schema="fred")
    op.drop_column("fred_macro_features", "net_liquidity_365d_zscore", schema="fred")

    # ── FRED-11 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "dexjpus_daily_zscore", schema="fred")
    op.drop_column("fred_macro_features", "dexjpus_20d_vol", schema="fred")
    op.drop_column("fred_macro_features", "dexjpus_5d_pct_change", schema="fred")
    op.drop_column("fred_macro_features", "dexjpus_level", schema="fred")
    op.drop_column("fred_macro_features", "dexjpus", schema="fred")

    # ── FRED-10 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "m2_yoy_pct", schema="fred")
    op.drop_column("fred_macro_features", "m2sl", schema="fred")

    # ── FRED-09 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "nfci_4wk_direction", schema="fred")
    op.drop_column("fred_macro_features", "nfci_level", schema="fred")
    op.drop_column("fred_macro_features", "nfci", schema="fred")

    # ── FRED-08 ─────────────────────────────────────────────────────────
    op.drop_column("fred_macro_features", "hy_oas_30d_zscore", schema="fred")
    op.drop_column("fred_macro_features", "hy_oas_5d_change", schema="fred")
    op.drop_column("fred_macro_features", "hy_oas_level", schema="fred")
    op.drop_column("fred_macro_features", "bamlh0a0hym2", schema="fred")
