"""ml_experiments_table

Phase 60: ML Infrastructure & Experimentation -- MLINFRA-05 experiment tracking.

Creates cmc_ml_experiments table for tracking ML experiment runs including
model type, hyperparameters, feature set used, cross-validation method,
OOS metrics, and feature importances.

All Phase 60 ML modules (MDA/SFI feature importance, regime routing,
DoubleEnsemble, Optuna) log their results here.

Revision ID: 3caddeff4691
Revises: f6a7b8c9d0e1
Create Date: 2026-02-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3caddeff4691"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create cmc_ml_experiments table with indexes and comments."""

    # -------------------------------------------------------------------------
    # CREATE TABLE cmc_ml_experiments
    # DDL mirrors sql/ml/095_cmc_ml_experiments.sql
    # -------------------------------------------------------------------------
    op.create_table(
        "cmc_ml_experiments",
        # UUID primary key, auto-generated
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        # Human-readable run label (not required to be unique)
        sa.Column("run_name", sa.Text(), nullable=False),
        # Model family: lgbm, random_forest, double_ensemble, regime_routed, etc.
        sa.Column("model_type", sa.Text(), nullable=False),
        # Full hyperparameter dict as JSONB (for reproducibility)
        sa.Column("model_params", postgresql.JSONB(), nullable=False),
        # Array of feature column names used in training
        sa.Column("feature_set", postgresql.ARRAY(sa.Text()), nullable=False),
        # SHA256 of sorted feature_set (fast lookup by feature set)
        sa.Column("feature_set_hash", sa.Text(), nullable=False),
        # Cross-validation method: purged_kfold, cpcv, walk_forward, etc.
        sa.Column("cv_method", sa.Text(), nullable=False),
        # Number of CV splits (NULL if not applicable)
        sa.Column("cv_n_splits", sa.Integer(), nullable=True),
        # Fractional embargo width between train and test folds
        sa.Column("cv_embargo_frac", sa.Numeric(), nullable=True),
        # Target label construction method
        sa.Column("label_method", sa.Text(), nullable=True),
        # Parameters for label construction as JSONB
        sa.Column("label_params", postgresql.JSONB(), nullable=True),
        # Training period boundaries
        sa.Column("train_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("train_end", sa.TIMESTAMP(timezone=True), nullable=False),
        # Asset IDs used in training
        sa.Column("asset_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        # Timeframe (e.g., '1D', '4h')
        sa.Column("tf", sa.Text(), nullable=False),
        # OOS metrics averaged across CV folds
        sa.Column("oos_accuracy", sa.Numeric(), nullable=True),
        sa.Column("oos_sharpe", sa.Numeric(), nullable=True),
        sa.Column("oos_precision", sa.Numeric(), nullable=True),
        sa.Column("oos_recall", sa.Numeric(), nullable=True),
        sa.Column("oos_f1", sa.Numeric(), nullable=True),
        sa.Column("n_oos_folds", sa.Integer(), nullable=True),
        # Feature importance scores as JSONB {feature_name: score}
        sa.Column("mda_importances", postgresql.JSONB(), nullable=True),
        sa.Column("sfi_importances", postgresql.JSONB(), nullable=True),
        # Optuna study linkage (NULL if Optuna not used)
        sa.Column("optuna_study_name", sa.Text(), nullable=True),
        sa.Column("optuna_n_trials", sa.Integer(), nullable=True),
        sa.Column("optuna_best_params", postgresql.JSONB(), nullable=True),
        # Regime routing fields
        sa.Column(
            "regime_routing",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("false"),
        ),
        sa.Column("regime_performance", postgresql.JSONB(), nullable=True),
        # Metadata
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("duration_seconds", sa.Numeric(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # -------------------------------------------------------------------------
    # Indexes
    # -------------------------------------------------------------------------
    op.create_index(
        "idx_ml_experiments_model_type",
        "cmc_ml_experiments",
        ["model_type"],
    )

    op.create_index(
        "idx_ml_experiments_created_at",
        "cmc_ml_experiments",
        [sa.text("created_at DESC")],
    )

    op.create_index(
        "idx_ml_experiments_asset_ids",
        "cmc_ml_experiments",
        ["asset_ids"],
        postgresql_using="gin",
    )

    op.create_index(
        "idx_ml_experiments_feature_set_hash",
        "cmc_ml_experiments",
        ["feature_set_hash"],
    )

    # -------------------------------------------------------------------------
    # Table and column comments
    # -------------------------------------------------------------------------
    op.execute(
        "COMMENT ON TABLE public.cmc_ml_experiments IS "
        "'ML experiment run tracking: model type, hyperparameters, feature set, CV method, "
        "OOS metrics, and feature importances. All Phase 60 ML modules (MDA/SFI, regime "
        "routing, DoubleEnsemble, Optuna) log results here.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.experiment_id IS "
        "'UUID primary key, auto-generated. Used as the stable reference for each experiment run.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.run_name IS "
        "'Human-readable run label (e.g., lgbm_1d_btc_purged_v1). Not required to be unique.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.model_type IS "
        "'Model family identifier: lgbm, random_forest, double_ensemble, regime_routed, etc.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.model_params IS "
        "'Full hyperparameter dict as JSONB. Enables reproducibility and parameter-performance comparison.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.feature_set IS "
        "'Array of feature column names used in training. Ordered list matches model feature order.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.feature_set_hash IS "
        "'SHA256 of sorted feature_set joined by comma. Enables fast lookup of runs with identical feature sets.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.cv_method IS "
        "'Cross-validation method: purged_kfold, cpcv, walk_forward, etc.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.cv_embargo_frac IS "
        "'Fractional embargo width between train and test folds (e.g., 0.01 = 1%). NULL for methods without embargo.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.label_method IS "
        "'Target label construction method: triple_barrier, fixed_horizon, triple_barrier_meta, etc.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.label_params IS "
        "'Parameters for label construction as JSONB (e.g., {pt: 0.02, sl: 0.01, t1_days: 5}).'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.oos_accuracy IS "
        "'Mean OOS accuracy across all CV folds. NULL if not computed.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.oos_sharpe IS "
        "'Mean OOS Sharpe ratio across all CV folds. NULL if not computed.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.mda_importances IS "
        "'Mean Decrease Accuracy importances as JSONB {feature_name: score}. NULL if MDA not run.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.sfi_importances IS "
        "'Single Feature Importance scores as JSONB {feature_name: score}. NULL if SFI not run.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.optuna_study_name IS "
        "'Optuna study name if hyperparameters were tuned via Optuna. NULL otherwise.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.regime_routing IS "
        "'TRUE if per-regime sub-models were used (TRA pattern via cmc_regimes labels).'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.regime_performance IS "
        "'Per-regime OOS accuracy as JSONB {regime_label: accuracy}. NULL if regime_routing is FALSE.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.duration_seconds IS "
        "'Wall-clock training + evaluation duration in seconds.'"
    )

    op.execute(
        "COMMENT ON COLUMN public.cmc_ml_experiments.notes IS "
        "'Free-text notes about this run (e.g., observations, known issues, next steps).'"
    )


def downgrade() -> None:
    """Drop cmc_ml_experiments table and all associated indexes."""
    op.drop_index(
        "idx_ml_experiments_feature_set_hash", table_name="cmc_ml_experiments"
    )
    op.drop_index("idx_ml_experiments_asset_ids", table_name="cmc_ml_experiments")
    op.drop_index("idx_ml_experiments_created_at", table_name="cmc_ml_experiments")
    op.drop_index("idx_ml_experiments_model_type", table_name="cmc_ml_experiments")
    op.drop_table("cmc_ml_experiments")
