"""feature_experiment_tables

Revision ID: 6f82e9117c58
Revises: c3b718c2d088
Create Date: 2026-02-24 12:18:06.000000

Creates two tables for the Phase 38 Feature Experimentation Framework:

dim_feature_registry:
  Tracks every named feature through its lifecycle (experimental -> promoted
  -> deprecated). Stores compute spec, input metadata, promotion thresholds,
  and best-observed IC metrics.

cmc_feature_experiments:
  Records IC experiment results per (feature, asset, tf, horizon, return_type,
  regime slice, training window). Also captures wall-clock and memory cost so
  ExperimentRunner can route cheap vs. expensive features appropriately.

Both tables use schema="public" throughout for Windows compatibility.
No UTF-8 box-drawing characters are used to avoid cp1252 decode errors.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f82e9117c58"
down_revision: Union[str, Sequence[str], None] = "c3b718c2d088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create dim_feature_registry and cmc_feature_experiments."""

    # ------------------------------------------------------------------
    # Table: dim_feature_registry
    # ------------------------------------------------------------------
    op.create_table(
        "dim_feature_registry",
        # Primary key -- feature name is the natural key
        sa.Column("feature_name", sa.Text(), nullable=False),
        # Lifecycle state with CHECK constraint
        sa.Column("lifecycle", sa.Text(), nullable=False),
        # Human-readable description
        sa.Column("description", sa.Text(), nullable=True),
        # Path to the YAML spec file that defines this feature
        sa.Column("yaml_source_path", sa.Text(), nullable=True),
        # SHA-256 digest of spec for change tracking
        sa.Column("yaml_digest", sa.Text(), nullable=True),
        # How to compute: 'inline' expression or 'dotpath' import
        sa.Column("compute_mode", sa.Text(), nullable=True),
        # The actual expression or dotpath string
        sa.Column("compute_spec", sa.Text(), nullable=True),
        # Source tables this feature reads from
        sa.Column("input_tables", sa.ARRAY(sa.Text()), nullable=True),
        # Source columns this feature depends on
        sa.Column("input_columns", sa.ARRAY(sa.Text()), nullable=True),
        # Arbitrary classification tags
        sa.Column("tags", sa.ARRAY(sa.Text()), nullable=True),
        # Promotion metadata
        sa.Column("promoted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("promoted_by", sa.Text(), nullable=True),
        # IC thresholds that triggered promotion
        sa.Column("promotion_alpha", sa.Numeric(), nullable=True),
        sa.Column("promotion_min_pass_rate", sa.Numeric(), nullable=True),
        # Best observed IC across all experiments
        sa.Column("best_ic", sa.Numeric(), nullable=True),
        sa.Column("best_horizon", sa.Integer(), nullable=True),
        # Path to any DDL stub generated for a promoted feature
        sa.Column("migration_stub_path", sa.Text(), nullable=True),
        # Audit timestamps
        sa.Column(
            "registered_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("feature_name"),
        sa.CheckConstraint(
            "lifecycle IN ('experimental', 'promoted', 'deprecated')",
            name="ck_feature_registry_lifecycle",
        ),
        schema="public",
    )

    # Index for fast lookup by lifecycle state
    op.create_index(
        "idx_feature_registry_lifecycle",
        "dim_feature_registry",
        ["lifecycle"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # Table: cmc_feature_experiments
    # ------------------------------------------------------------------
    op.create_table(
        "cmc_feature_experiments",
        # Primary key -- UUID generated server-side
        sa.Column(
            "experiment_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Feature being evaluated
        sa.Column("feature_name", sa.Text(), nullable=False),
        # When the experiment ran
        sa.Column(
            "run_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        # Asset + timeframe
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        # Training window bounds (inclusive)
        sa.Column("train_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("train_end", sa.TIMESTAMP(timezone=True), nullable=False),
        # Forward return horizon in bars
        sa.Column("horizon", sa.Integer(), nullable=False),
        # Forward return horizon in calendar days (horizon * tf_days_nominal)
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        # Return type: 'arith' or 'log'
        sa.Column("return_type", sa.Text(), nullable=False),
        # Regime slice key: 'trend_state', 'vol_state', or 'all'
        sa.Column("regime_col", sa.Text(), nullable=False),
        # Regime slice label: e.g. 'Up', 'High', 'all'
        sa.Column("regime_label", sa.Text(), nullable=False),
        # IC outputs -- nullable because some windows may lack sufficient data
        sa.Column("ic", sa.Numeric(), nullable=True),
        sa.Column("ic_t_stat", sa.Numeric(), nullable=True),
        sa.Column("ic_p_value", sa.Numeric(), nullable=True),
        # Benjamini-Hochberg corrected p-value
        sa.Column("ic_p_value_bh", sa.Numeric(), nullable=True),
        sa.Column("ic_ir", sa.Numeric(), nullable=True),
        sa.Column("ic_ir_t_stat", sa.Numeric(), nullable=True),
        # Number of observations in the training window
        sa.Column("n_obs", sa.Integer(), nullable=True),
        # Compute cost metadata
        sa.Column("wall_clock_seconds", sa.Numeric(), nullable=True),
        sa.Column("peak_memory_mb", sa.Numeric(), nullable=True),
        sa.Column("n_rows_computed", sa.Integer(), nullable=True),
        # YAML spec digest at time of experiment (for reproducibility)
        sa.Column("yaml_digest", sa.Text(), nullable=True),
        # Constraints
        sa.PrimaryKeyConstraint("experiment_id"),
        sa.UniqueConstraint(
            "feature_name",
            "asset_id",
            "tf",
            "horizon",
            "return_type",
            "regime_col",
            "regime_label",
            "train_start",
            "train_end",
            name="uq_feature_experiments_key",
        ),
        schema="public",
    )

    # Index for fast lookup by feature name
    op.create_index(
        "idx_feature_experiments_feature_name",
        "cmc_feature_experiments",
        ["feature_name"],
        schema="public",
    )

    # Index for time-based queries and freshness checks
    op.create_index(
        "idx_feature_experiments_run_at",
        "cmc_feature_experiments",
        ["run_at"],
        schema="public",
    )


def downgrade() -> None:
    """Downgrade schema: drop cmc_feature_experiments and dim_feature_registry."""
    # Drop indexes first, then tables
    op.drop_index(
        "idx_feature_experiments_run_at",
        table_name="cmc_feature_experiments",
        schema="public",
    )
    op.drop_index(
        "idx_feature_experiments_feature_name",
        table_name="cmc_feature_experiments",
        schema="public",
    )
    op.drop_table("cmc_feature_experiments", schema="public")

    op.drop_index(
        "idx_feature_registry_lifecycle",
        table_name="dim_feature_registry",
        schema="public",
    )
    op.drop_table("dim_feature_registry", schema="public")
