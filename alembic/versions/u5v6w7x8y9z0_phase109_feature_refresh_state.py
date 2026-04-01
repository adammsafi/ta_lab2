"""Phase 109: feature_refresh_state table for per-asset skip logic.

Creates:
  feature_refresh_state  - Per-asset watermark table keyed on (id, tf,
                           alignment_source).  Stores last_bar_ts so the
                           feature refresh orchestrator can compare against
                           source bar ingested_at and skip assets with no
                           new bar data.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: u5v6w7x8y9z0
Revises: w6x7y8z9a0b1
Create Date: 2026-04-01
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "u5v6w7x8y9z0"
down_revision: Union[str, Sequence[str], None] = "w6x7y8z9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # feature_refresh_state
    # One row per (id, tf, alignment_source) tracking the last bar
    # timestamp seen when features were computed.  The feature refresh
    # orchestrator compares MAX(ingested_at) from price_bars_multi_tf_u
    # against last_bar_ts to decide whether to skip an asset entirely.
    #
    # PK is (id, tf, alignment_source) -- no venue_id in PK.
    # Features currently use venue_id=1 (CMC_AGG) exclusively.
    # If multi-venue feature support is added later, venue_id can be
    # added to the PK via a follow-up migration.
    #
    # Columns:
    #   id               -- asset id (FK to dim_assets conceptually)
    #   tf               -- timeframe string e.g. '1D', '4H'
    #   alignment_source -- bar alignment source e.g. 'multi_tf'
    #   last_bar_ts      -- MAX(ingested_at) from source bars at last run
    #   last_refresh_ts  -- wall-clock time of the last feature refresh
    #   rows_written     -- total feature rows written in last refresh
    #   updated_at       -- set to NOW() on every upsert
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.feature_refresh_state (
            id                  INTEGER      NOT NULL,
            tf                  TEXT         NOT NULL,
            alignment_source    TEXT         NOT NULL DEFAULT 'multi_tf',
            last_bar_ts         TIMESTAMPTZ  NULL,
            last_refresh_ts     TIMESTAMPTZ  NULL,
            rows_written        INTEGER      NULL,
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf, alignment_source)
        )
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS public.feature_refresh_state"))
