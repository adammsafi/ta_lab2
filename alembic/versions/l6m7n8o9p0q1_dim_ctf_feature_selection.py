"""dim_ctf_feature_selection dimension table for CTF IC analysis

Creates:
  dim_ctf_feature_selection - stores CTF feature tier classifications
    (active, conditional, watch, archive) from IC analysis.
    Separate from Phase 80 dim_feature_selection to avoid interference.

PK: (feature_name, base_tf)

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-03-24
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "l6m7n8o9p0q1"
down_revision: Union[str, Sequence[str], None] = "k5l6m7n8o9p0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # dim_ctf_feature_selection table
    # Stores CTF tier classifications from IC analysis.
    # PK: (feature_name, base_tf)
    # tier CHECK: active, conditional, watch, archive
    # stationarity CHECK: STATIONARY, NON_STATIONARY, AMBIGUOUS, INSUFFICIENT_DATA
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.dim_ctf_feature_selection (
            feature_name          TEXT         NOT NULL,
            base_tf               TEXT         NOT NULL,
            tier                  TEXT         NOT NULL
                CONSTRAINT dim_ctf_feature_selection_tier_check
                CHECK (tier IN ('active','conditional','watch','archive')),
            ic_ir_mean            NUMERIC,
            pass_rate             NUMERIC,
            stationarity          TEXT
                CONSTRAINT dim_ctf_feature_selection_stationarity_check
                CHECK (stationarity IN (
                    'STATIONARY',
                    'NON_STATIONARY',
                    'AMBIGUOUS',
                    'INSUFFICIENT_DATA'
                )),
            ljung_box_flag        BOOLEAN      DEFAULT FALSE,
            selected_at           TIMESTAMPTZ  DEFAULT now(),
            yaml_version          TEXT,
            rationale             TEXT,
            PRIMARY KEY (feature_name, base_tf)
        )
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("DROP TABLE IF EXISTS public.dim_ctf_feature_selection"))
