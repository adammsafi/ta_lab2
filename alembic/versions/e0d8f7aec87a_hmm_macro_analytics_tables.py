"""hmm_macro_analytics_tables

Phase 68: HMM & Macro Analytics -- Wave 1 foundation.

Creates three tables for the macro analytical tools:

1. cmc_hmm_regimes: Daily HMM state labels per model configuration
   (n_states, model_run_date). Stores posterior probabilities, BIC/AIC
   model selection metrics, and winner flags for selecting best state count.
   PK: (date, n_states, model_run_date).

2. cmc_macro_lead_lag_results: Cross-correlation of macro features against
   asset returns across lags [-60..+60]. Stores the best lag, correlation,
   significance flag, and full JSON profile for research queries.
   PK: (macro_feature, asset_col, computed_at).

3. cmc_macro_transition_probs: Regime transition probability matrices for
   both rule-based and HMM regime sources, supporting static (all history)
   and rolling windows. Enables duration estimation and regime path analysis.
   PK: (regime_source, window_type, window_end_date, from_state, to_state).

Revision ID: e0d8f7aec87a
Revises: d5e6f7a8b9c0
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import func

# -- Revision identifiers --------------------------------------------------
revision = "e0d8f7aec87a"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Table 1: cmc_hmm_regimes ──────────────────────────────────────────
    # Daily HMM state labels per model configuration.
    # PK: (date, n_states, model_run_date)
    op.create_table(
        "cmc_hmm_regimes",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "n_states",
            sa.Integer(),
            nullable=False,
            comment="Number of HMM states (2 or 3)",
        ),
        sa.Column(
            "model_run_date",
            sa.Date(),
            nullable=False,
            comment="Date the model was last fit/retrained",
        ),
        sa.Column(
            "state_label",
            sa.Integer(),
            nullable=True,
            comment="HMM state index assigned to this date (0, 1, 2)",
        ),
        sa.Column(
            "state_probability",
            sa.Float(),
            nullable=True,
            comment="Posterior probability of the assigned state",
        ),
        sa.Column(
            "bic",
            sa.Float(),
            nullable=True,
            comment="Bayesian Information Criterion for this model",
        ),
        sa.Column(
            "aic",
            sa.Float(),
            nullable=True,
            comment="Akaike Information Criterion for this model",
        ),
        sa.Column(
            "is_bic_winner",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="True if this n_states had the best (lowest) BIC",
        ),
        sa.Column(
            "state_means_json",
            sa.Text(),
            nullable=True,
            comment="JSON string of state mean vectors for regime interpretation",
        ),
        sa.Column(
            "covariance_type",
            sa.Text(),
            nullable=False,
            server_default="full",
            comment="HMM covariance type (full, diag, spherical, tied)",
        ),
        sa.Column(
            "n_features",
            sa.Integer(),
            nullable=True,
            comment="Number of input features used to train the model",
        ),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.PrimaryKeyConstraint("date", "n_states", "model_run_date"),
    )
    op.create_index(
        "idx_cmc_hmm_regimes_date",
        "cmc_hmm_regimes",
        [sa.text("date DESC")],
    )
    op.create_index(
        "idx_cmc_hmm_regimes_winner",
        "cmc_hmm_regimes",
        ["is_bic_winner"],
        postgresql_where=sa.text("is_bic_winner = true"),
    )

    # ── Table 2: cmc_macro_lead_lag_results ───────────────────────────────
    # Cross-correlation results for macro features vs asset returns.
    # PK: (macro_feature, asset_col, computed_at)
    op.create_table(
        "cmc_macro_lead_lag_results",
        sa.Column(
            "macro_feature",
            sa.Text(),
            nullable=False,
            comment="Column name from fred_macro_features (e.g. vixcls, hy_oas_level)",
        ),
        sa.Column(
            "asset_col",
            sa.Text(),
            nullable=False,
            comment="Asset return column (e.g. btc_1d_return, eth_1d_return)",
        ),
        sa.Column(
            "computed_at",
            sa.Date(),
            nullable=False,
            comment="Date this analysis was run",
        ),
        sa.Column(
            "best_lag",
            sa.Integer(),
            nullable=True,
            comment="Lag with highest absolute correlation; negative = macro leads asset",
        ),
        sa.Column(
            "best_corr",
            sa.Float(),
            nullable=True,
            comment="Pearson correlation at best_lag",
        ),
        sa.Column(
            "is_significant",
            sa.Boolean(),
            nullable=True,
            comment="True if |best_corr| > 2/sqrt(N) (two-sigma significance)",
        ),
        sa.Column(
            "n_obs",
            sa.Integer(),
            nullable=True,
            comment="Number of overlapping observations used in correlation",
        ),
        sa.Column(
            "lag_range_min",
            sa.Integer(),
            nullable=True,
            comment="Minimum lag tested (e.g. -60)",
        ),
        sa.Column(
            "lag_range_max",
            sa.Integer(),
            nullable=True,
            comment="Maximum lag tested (e.g. +60)",
        ),
        sa.Column(
            "corr_by_lag_json",
            sa.Text(),
            nullable=True,
            comment="JSON string of {lag: corr} dict for full correlation profile",
        ),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.PrimaryKeyConstraint("macro_feature", "asset_col", "computed_at"),
    )
    op.create_index(
        "idx_lead_lag_significant",
        "cmc_macro_lead_lag_results",
        ["is_significant"],
        postgresql_where=sa.text("is_significant = true"),
    )

    # ── Table 3: cmc_macro_transition_probs ──────────────────────────────
    # Regime transition probability matrices (rule-based and HMM, static and rolling).
    # PK: (regime_source, window_type, window_end_date, from_state, to_state)
    op.create_table(
        "cmc_macro_transition_probs",
        sa.Column(
            "regime_source",
            sa.Text(),
            nullable=False,
            comment="Source of regime labels: rule_based or hmm",
        ),
        sa.Column(
            "window_type",
            sa.Text(),
            nullable=False,
            comment="Window type: static (all history) or rolling",
        ),
        sa.Column(
            "window_end_date",
            sa.Date(),
            nullable=False,
            comment="For static: max date in history; for rolling: end of rolling window",
        ),
        sa.Column(
            "from_state",
            sa.Text(),
            nullable=False,
            comment="Regime label being transitioned FROM",
        ),
        sa.Column(
            "to_state",
            sa.Text(),
            nullable=False,
            comment="Regime label being transitioned TO",
        ),
        sa.Column(
            "probability",
            sa.Float(),
            nullable=False,
            comment="Row-normalized transition probability (0.0 to 1.0)",
        ),
        sa.Column(
            "transition_count",
            sa.Integer(),
            nullable=False,
            comment="Raw count of from->to transitions in window",
        ),
        sa.Column(
            "total_from_count",
            sa.Integer(),
            nullable=False,
            comment="Total transitions from from_state in window (row sum)",
        ),
        sa.Column(
            "window_days",
            sa.Integer(),
            nullable=True,
            comment="For rolling: window size in days; for static: total history days",
        ),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "regime_source",
            "window_type",
            "window_end_date",
            "from_state",
            "to_state",
        ),
    )
    op.create_index(
        "idx_transition_source_date",
        "cmc_macro_transition_probs",
        ["regime_source", sa.text("window_end_date DESC")],
    )


def downgrade() -> None:
    # Drop in reverse creation order
    op.drop_index("idx_transition_source_date", table_name="cmc_macro_transition_probs")
    op.drop_table("cmc_macro_transition_probs")

    op.drop_index("idx_lead_lag_significant", table_name="cmc_macro_lead_lag_results")
    op.drop_table("cmc_macro_lead_lag_results")

    op.drop_index("idx_cmc_hmm_regimes_winner", table_name="cmc_hmm_regimes")
    op.drop_index("idx_cmc_hmm_regimes_date", table_name="cmc_hmm_regimes")
    op.drop_table("cmc_hmm_regimes")
