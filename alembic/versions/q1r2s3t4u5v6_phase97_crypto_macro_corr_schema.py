"""phase97_crypto_macro_corr_schema

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-03-31

Phase 97 Plan 02: Multi-window BTC-equity correlation schema upgrade.

Adds `window` column to crypto_macro_corr_regimes PK (enables 30/60/90/180d windows)
and 7 new columns for equity vol regime, VIX cross-validation, and divergence signals.

Changes:
  - Add window INTEGER column (NOT NULL, server_default='60' for existing row backfill)
  - Add equity_vol_regime TEXT (nullable)
  - Add vix_agreement_flag BOOLEAN (nullable)
  - Add realized_vol_z FLOAT (nullable)
  - Add vix_z FLOAT (nullable)
  - Add vol_spread FLOAT (nullable)
  - Add divergence_zscore FLOAT (nullable)
  - Add divergence_flag BOOLEAN (nullable)
  - Drop existing PK (date, asset_id, macro_var)
  - Recreate PK as (date, asset_id, macro_var, window)
  - Remove server_default from window after backfill
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "q1r2s3t4u5v6"
down_revision = "p0q1r2s3t4u5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add window column with server_default='60' to backfill existing rows.
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("window", sa.Integer(), nullable=False, server_default="60"),
    )

    # Step 2: Add 7 new nullable columns.
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("equity_vol_regime", sa.Text(), nullable=True),
    )
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("vix_agreement_flag", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("realized_vol_z", sa.Float(), nullable=True),
    )
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("vix_z", sa.Float(), nullable=True),
    )
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("vol_spread", sa.Float(), nullable=True),
    )
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("divergence_zscore", sa.Float(), nullable=True),
    )
    op.add_column(
        "crypto_macro_corr_regimes",
        sa.Column("divergence_flag", sa.Boolean(), nullable=True),
    )

    # Step 3: Drop existing PK and recreate with window in PK.
    op.drop_constraint(
        "crypto_macro_corr_regimes_pkey",
        "crypto_macro_corr_regimes",
        type_="primary",
    )
    op.create_primary_key(
        "crypto_macro_corr_regimes_pkey",
        "crypto_macro_corr_regimes",
        ["date", "asset_id", "macro_var", "window"],
    )

    # Step 4: Remove server_default from window (only needed for backfill of existing rows).
    op.alter_column("crypto_macro_corr_regimes", "window", server_default=None)


def downgrade() -> None:
    # NOTE: downgrade will fail if multiple window values exist for the same
    # (date, asset_id, macro_var). This is acceptable -- downgrade is for dev only.

    # Step 1: Drop the PK with window.
    op.drop_constraint(
        "crypto_macro_corr_regimes_pkey",
        "crypto_macro_corr_regimes",
        type_="primary",
    )

    # Step 2: Recreate original PK without window.
    op.create_primary_key(
        "crypto_macro_corr_regimes_pkey",
        "crypto_macro_corr_regimes",
        ["date", "asset_id", "macro_var"],
    )

    # Step 3: Drop all 8 new columns.
    op.drop_column("crypto_macro_corr_regimes", "divergence_flag")
    op.drop_column("crypto_macro_corr_regimes", "divergence_zscore")
    op.drop_column("crypto_macro_corr_regimes", "vol_spread")
    op.drop_column("crypto_macro_corr_regimes", "vix_z")
    op.drop_column("crypto_macro_corr_regimes", "realized_vol_z")
    op.drop_column("crypto_macro_corr_regimes", "vix_agreement_flag")
    op.drop_column("crypto_macro_corr_regimes", "equity_vol_regime")
    op.drop_column("crypto_macro_corr_regimes", "window")
