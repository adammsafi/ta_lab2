"""dim_feature_selection dimension table

Creates the dim_feature_selection table that mirrors the YAML feature
selection config to the database for runtime queries by downstream scripts.
Stores per-feature tier classification, IC/IR metrics, stationarity status,
and Ljung-Box autocorrelation flags from the IC analysis pipeline.

Columns:
  feature_name         - primary key, matches YAML key
  tier                 - active | conditional | watch | archive
  ic_ir_mean           - mean information coefficient / IR across lookbacks
  pass_rate            - fraction of IC computations where |IC| >= threshold
  quintile_monotonicity - Spearman correlation of Q1-Q5 terminal returns
  stationarity         - STATIONARY | NON_STATIONARY | AMBIGUOUS | INSUFFICIENT_DATA
  ljung_box_flag       - TRUE if autocorrelation detected in IC series
  regime_specialist    - TRUE if feature performs well only in specific regimes
  specialist_regimes   - array of regime labels where feature is effective
  selected_at          - timestamp when row was last written
  yaml_version         - version tag from YAML config at time of selection
  rationale            - free-text explanation for tier placement

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-03-22
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, Sequence[str], None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.dim_feature_selection (
            feature_name          TEXT NOT NULL,
            tier                  TEXT NOT NULL
                CONSTRAINT chk_dim_feature_selection_tier
                CHECK (tier IN ('active', 'conditional', 'watch', 'archive')),
            ic_ir_mean            NUMERIC,
            pass_rate             NUMERIC,
            quintile_monotonicity NUMERIC,
            stationarity          TEXT
                CONSTRAINT chk_dim_feature_selection_stationarity
                CHECK (stationarity IN (
                    'STATIONARY',
                    'NON_STATIONARY',
                    'AMBIGUOUS',
                    'INSUFFICIENT_DATA'
                )),
            ljung_box_flag        BOOLEAN DEFAULT FALSE,
            regime_specialist     BOOLEAN DEFAULT FALSE,
            specialist_regimes    TEXT[],
            selected_at           TIMESTAMPTZ DEFAULT now(),
            yaml_version          TEXT,
            rationale             TEXT,
            PRIMARY KEY (feature_name)
        )
    """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS public.dim_feature_selection"))
