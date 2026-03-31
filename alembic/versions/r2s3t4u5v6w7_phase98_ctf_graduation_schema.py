"""phase98_ctf_graduation_schema

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-03-31

Phase 98 Plan 01: CTF Feature Graduation schema changes.

DATA-DEPENDENT MIGRATION WARNING:
This migration queries public.ic_results at runtime to discover which CTF
features pass the IC > 0.02 cross-asset median threshold. The set of columns
added to the features table will vary depending on the IC data present at
migration time. The discovered column list is stored in the module-level
constant _CTF_PROMOTED_COLS, populated during upgrade() execution.

This is intentional: the schema evolves with the research findings, and
the migration captures the exact promoted feature set at the time of
graduation.

Four schema changes:

1. Add CTF promoted columns to public.features (dynamic, IC-driven).

2. Create public.dim_feature_selection_asset
   Separate from dim_feature_selection to avoid TRUNCATE hazard.
   Stores per-asset IC tier assignments (asset_id is NOT NULL).

3. Create public.ctf_composites
   Stores cross-asset composite signals (mean, PCA, z-score, lead-lag)
   computed from CTF features. PK: (ts, tf, venue_id, composite_name, method).

4. Create public.lead_lag_ic
   Stores all-vs-all asset pair lead-lag IC matrix with FDR correction.
   PK: (asset_a_id, asset_b_id, feature, horizon, tf, venue_id).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "r2s3t4u5v6w7"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None

# Module-level constant populated during upgrade() via the IC query.
# Also used in downgrade() to reverse the column additions.
_CTF_PROMOTED_COLS: list[str] = []

# IC threshold for feature promotion (cross-asset median absolute IC).
_IC_THRESHOLD = 0.02

# SQL to discover CTF features passing IC threshold.
_IC_DISCOVERY_SQL = """
    SELECT feature
    FROM public.ic_results
    WHERE horizon = 1
      AND return_type = 'arith'
      AND regime_col = 'all'
      AND regime_label = 'all'
      AND ic IS NOT NULL
      AND (
           feature LIKE '%_slope'
        OR feature LIKE '%_divergence'
        OR feature LIKE '%_agreement'
        OR feature LIKE '%_crossover'
        OR feature LIKE '%_ref_value'
        OR feature LIKE '%_base_value'
      )
    GROUP BY feature
    HAVING PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > :threshold
    ORDER BY feature
"""


def _discover_ctf_features(bind) -> list[str]:
    """Query ic_results to find CTF features passing the IC threshold.

    Parameters
    ----------
    bind:
        SQLAlchemy connection (from op.get_bind()).

    Returns
    -------
    Sorted list of feature name strings (valid PostgreSQL column names).
    Empty list if ic_results has no CTF rows yet (logs a warning).
    """
    result = bind.execute(
        sa.text(_IC_DISCOVERY_SQL),
        {"threshold": _IC_THRESHOLD},
    )
    features = [row[0] for row in result]
    if not features:
        logger.warning(
            "phase98 migration: ic_results returned 0 CTF features passing IC > %.2f. "
            "No CTF columns will be added to features table. "
            "Re-run migration after ic_results is populated.",
            _IC_THRESHOLD,
        )
    else:
        logger.info(
            "phase98 migration: discovered %d CTF features passing IC > %.2f",
            len(features),
            _IC_THRESHOLD,
        )
    return features


def upgrade() -> None:
    global _CTF_PROMOTED_COLS

    bind = op.get_bind()

    # =========================================================================
    # Step 1: Discover CTF features passing IC threshold and add to features
    # =========================================================================
    _CTF_PROMOTED_COLS = _discover_ctf_features(bind)

    # Only add columns that don't already exist in features (idempotency guard).
    existing_cols_result = bind.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'features'"
        )
    )
    existing_cols = {row[0] for row in existing_cols_result}

    new_cols_added = []
    for feature_name in _CTF_PROMOTED_COLS:
        if feature_name not in existing_cols:
            op.add_column(
                "features",
                sa.Column(feature_name, sa.Float(), nullable=True),
                schema="public",
            )
            new_cols_added.append(feature_name)

    logger.info(
        "phase98 migration: added %d new CTF columns to features (%d already existed)",
        len(new_cols_added),
        len(_CTF_PROMOTED_COLS) - len(new_cols_added),
    )

    # =========================================================================
    # Step 2: Create dim_feature_selection_asset
    # Separate from dim_feature_selection to avoid TRUNCATE hazard.
    # Stores per-asset CTF feature tier assignments.
    # =========================================================================
    op.create_table(
        "dim_feature_selection_asset",
        sa.Column("feature_name", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column(
            "tier",
            sa.Text(),
            nullable=False,
            server_default="asset_specific",
        ),
        sa.Column("ic_ir_mean", sa.Numeric(), nullable=True),
        sa.Column("pass_rate", sa.Numeric(), nullable=True),
        sa.Column("stationarity", sa.Text(), nullable=True),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("yaml_version", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("feature_name", "asset_id"),
        schema="public",
    )

    # =========================================================================
    # Step 3: Create ctf_composites
    # Stores cross-asset composite signals (sentiment, relative-value,
    # leader-follower) computed from CTF features.
    # =========================================================================
    op.create_table(
        "ctf_composites",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column(
            "venue_id",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("composite_name", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("n_assets", sa.Integer(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("ts", "tf", "venue_id", "composite_name", "method"),
        schema="public",
    )

    # =========================================================================
    # Step 4: Create lead_lag_ic
    # Stores all-vs-all asset pair lead-lag IC matrix with FDR correction flags.
    # =========================================================================
    op.create_table(
        "lead_lag_ic",
        sa.Column("asset_a_id", sa.Integer(), nullable=False),
        sa.Column("asset_b_id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column(
            "venue_id",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("ic", sa.Numeric(), nullable=True),
        sa.Column("ic_p_value", sa.Numeric(), nullable=True),
        sa.Column("ic_p_bh", sa.Numeric(), nullable=True),
        sa.Column("is_significant", sa.Boolean(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "asset_a_id",
            "asset_b_id",
            "feature",
            "horizon",
            "tf",
            "venue_id",
        ),
        schema="public",
    )


def downgrade() -> None:
    # =========================================================================
    # Reverse Step 4: Drop lead_lag_ic
    # =========================================================================
    op.drop_table("lead_lag_ic", schema="public")

    # =========================================================================
    # Reverse Step 3: Drop ctf_composites
    # =========================================================================
    op.drop_table("ctf_composites", schema="public")

    # =========================================================================
    # Reverse Step 2: Drop dim_feature_selection_asset
    # =========================================================================
    op.drop_table("dim_feature_selection_asset", schema="public")

    # =========================================================================
    # Reverse Step 1: Remove CTF columns from features
    # NOTE: We discover the columns dynamically on downgrade (same approach as
    # upgrade) to handle the case where the global is not populated.
    # =========================================================================
    bind = op.get_bind()
    ctf_cols_result = bind.execute(
        sa.text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'features'
              AND (
                   column_name LIKE '%_slope'
                OR column_name LIKE '%_divergence'
                OR column_name LIKE '%_agreement'
                OR column_name LIKE '%_crossover'
                OR column_name LIKE '%_ref_value'
                OR column_name LIKE '%_base_value'
              )
            ORDER BY column_name
            """
        )
    )
    ctf_cols_to_drop = [row[0] for row in ctf_cols_result]

    # Filter to only columns that match CTF naming pattern strictly
    # (indicator_name + _ + ref_tf + _ + composite suffix).
    # This avoids accidentally dropping non-CTF columns that happen to match.
    # All CTF column names contain exactly 2+ underscores: e.g. rsi_14_7d_slope
    ctf_cols_to_drop = [c for c in ctf_cols_to_drop if c.count("_") >= 2]

    for col in ctf_cols_to_drop:
        op.drop_column("features", col, schema="public")

    logger.info(
        "phase98 downgrade: removed %d CTF columns from features",
        len(ctf_cols_to_drop),
    )
