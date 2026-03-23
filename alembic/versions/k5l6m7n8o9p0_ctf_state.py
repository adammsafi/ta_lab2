"""CTF state table for incremental refresh tracking

Creates:
  ctf_state - tracks last computed timestamp per (id, venue_id, base_tf, ref_tf,
              indicator_id, alignment_source) scope for incremental CTF refresh.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-03-23
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "k5l6m7n8o9p0"
down_revision: Union[str, Sequence[str], None] = "j4k5l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # ctf_state table
    # Incremental refresh state for CTF features.
    # Tracks last computed timestamp per scope.
    # PK: (id, venue_id, base_tf, ref_tf, indicator_id, alignment_source)
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.ctf_state (
            id                  INTEGER      NOT NULL,
            venue_id            SMALLINT     NOT NULL DEFAULT 1,
            base_tf             TEXT         NOT NULL,
            ref_tf              TEXT         NOT NULL,
            indicator_id        SMALLINT     NOT NULL,
            alignment_source    TEXT         NOT NULL DEFAULT 'multi_tf',
            last_ts             TIMESTAMPTZ  NULL,
            row_count           INTEGER      NULL,
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (id, venue_id, base_tf, ref_tf, indicator_id, alignment_source),
            FOREIGN KEY (indicator_id)
                REFERENCES public.dim_ctf_indicators(indicator_id)
        )
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("DROP TABLE IF EXISTS public.ctf_state"))
