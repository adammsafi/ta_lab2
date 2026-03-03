"""macro_regime_tables

Phase 67: Macro Regime Classifier -- Wave 1 foundation.

Creates two tables for the macro regime classification system:

1. cmc_macro_regimes: Daily macro regime labels with per-dimension
   classifications (monetary_policy, liquidity, risk_appetite, carry),
   a composite regime_key, and a bucketed macro_state for downstream
   policy lookups. PK: (date, profile).

2. cmc_macro_hysteresis_state: Persistent hysteresis tracker state for
   incremental resume. Stores pending label transitions and confirmation
   counts per (profile, dimension) to avoid regime-flip whipsaw.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

# -- Revision identifiers --------------------------------------------------
revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Table 1: cmc_macro_regimes ────────────────────────────────────────
    # Daily macro regime labels. One row per (date, profile).
    # The classifier writes per-dimension labels, a composite regime_key,
    # and a bucketed macro_state (favorable/constructive/neutral/cautious/adverse).
    op.create_table(
        "cmc_macro_regimes",
        # Primary key columns
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "profile",
            sa.Text(),
            nullable=False,
            server_default="default",
        ),
        # --- Per-dimension labels ---
        # Monetary policy stance: Hiking / Holding / Cutting
        sa.Column("monetary_policy", sa.Text(), nullable=True),
        # Liquidity regime: Strongly_Expanding / Expanding / Neutral /
        #                    Contracting / Strongly_Contracting
        sa.Column("liquidity", sa.Text(), nullable=True),
        # Risk appetite: RiskOff / Neutral / RiskOn
        sa.Column("risk_appetite", sa.Text(), nullable=True),
        # Carry trade stress: Unwind / Stress / Stable
        sa.Column("carry", sa.Text(), nullable=True),
        # --- Composite key ---
        # Concatenation of dimension labels, e.g. 'Cutting-Expanding-RiskOn-Stable'
        sa.Column("regime_key", sa.Text(), nullable=True),
        # --- Bucketed state ---
        # Mapped from regime_key: favorable/constructive/neutral/cautious/adverse
        sa.Column("macro_state", sa.Text(), nullable=True),
        # --- Provenance ---
        # Hash of the classifier config used (for reproducibility)
        sa.Column("regime_version_hash", sa.Text(), nullable=True),
        # --- Metadata ---
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("date", "profile"),
    )

    # Index: efficient lookup by date descending (most recent regimes first)
    op.create_index(
        "idx_cmc_macro_regimes_date",
        "cmc_macro_regimes",
        [sa.text("date DESC")],
    )

    # Index: downstream policy lookups by macro_state
    op.create_index(
        "idx_cmc_macro_regimes_state",
        "cmc_macro_regimes",
        ["macro_state"],
    )

    # ── Table 2: cmc_macro_hysteresis_state ───────────────────────────────
    # Persistent tracker state for hysteresis-based regime classification.
    # One row per (profile, dimension). The classifier reads/writes this
    # to avoid whipsaw regime flips on noisy data.
    op.create_table(
        "cmc_macro_hysteresis_state",
        sa.Column("profile", sa.Text(), nullable=False),
        # Dimension name: monetary_policy / liquidity / risk_appetite / carry
        sa.Column("dimension", sa.Text(), nullable=False),
        # Current confirmed label for this dimension
        sa.Column("current_label", sa.Text(), nullable=True),
        # Label that is pending confirmation (not yet confirmed)
        sa.Column("pending_label", sa.Text(), nullable=True),
        # Number of consecutive observations confirming the pending label
        sa.Column(
            "pending_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # Last update timestamp
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("profile", "dimension"),
    )


def downgrade() -> None:
    # Drop in reverse order of creation
    op.drop_table("cmc_macro_hysteresis_state")
    op.drop_index("idx_cmc_macro_regimes_state", table_name="cmc_macro_regimes")
    op.drop_index("idx_cmc_macro_regimes_date", table_name="cmc_macro_regimes")
    op.drop_table("cmc_macro_regimes")
