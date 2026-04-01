"""Phase 107 pipeline_stage_log table and pipeline_run_log killed status.

Creates:
  pipeline_stage_log  - Per-stage timing rows linked to pipeline_run_log.
                        Enables the ops dashboard to show real-time stage
                        progress and react to a kill switch.

Also alters:
  pipeline_run_log.status CHECK  - adds 'killed' as an allowed value.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-04-01
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "t4u5v6w7x8y9"
down_revision: Union[str, Sequence[str], None] = "s3t4u5v6w7x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # pipeline_stage_log
    # One row per stage per pipeline run.  FK to pipeline_run_log with
    # CASCADE delete so cleaning up old run rows removes stage rows too.
    # status CHECK mirrors pipeline_run_log values plus 'running'.
    # duration_sec is nullable -- NULL while stage is still running.
    # rows_written is optional, populated by writers that track row counts.
    # INDEX on (run_id, started_at) for efficient per-run stage queries.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.pipeline_stage_log (
            stage_log_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id          UUID        NOT NULL
                                REFERENCES public.pipeline_run_log(run_id)
                                ON DELETE CASCADE,
            stage_name      VARCHAR(50) NOT NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ,
            status          VARCHAR(20) NOT NULL DEFAULT 'running'
                                CHECK (status IN ('running', 'complete', 'failed', 'killed')),
            duration_sec    NUMERIC,
            rows_written    INTEGER,
            error_message   TEXT
        )
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_pipeline_stage_log_run_id
            ON public.pipeline_stage_log (run_id, started_at)
        """)
    )

    # ------------------------------------------------------------------
    # ALTER pipeline_run_log: add 'killed' to the status CHECK constraint.
    # We must DROP the existing constraint by name then ADD a new one.
    # The constraint name was set by PostgreSQL when the table was created
    # (format: pipeline_run_log_status_check).  We look it up defensively
    # with pg_constraint so this is idempotent even if the name changes.
    # ------------------------------------------------------------------

    # Drop the existing status CHECK on pipeline_run_log
    conn.execute(
        text("""
        DO $$
        DECLARE
            _cname TEXT;
        BEGIN
            SELECT conname INTO _cname
            FROM pg_constraint
            WHERE conrelid = 'public.pipeline_run_log'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%status%';

            IF _cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE public.pipeline_run_log DROP CONSTRAINT %I', _cname);
            END IF;
        END;
        $$
        """)
    )

    # Add updated CHECK constraint that includes 'killed'
    conn.execute(
        text("""
        ALTER TABLE public.pipeline_run_log
            ADD CONSTRAINT pipeline_run_log_status_check
            CHECK (status IN ('running', 'complete', 'failed', 'killed'))
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove the pipeline_stage_log table and index
    conn.execute(text("DROP INDEX IF EXISTS public.ix_pipeline_stage_log_run_id"))
    conn.execute(text("DROP TABLE IF EXISTS public.pipeline_stage_log"))

    # Restore original CHECK constraint on pipeline_run_log (without 'killed')
    conn.execute(
        text("""
        DO $$
        DECLARE
            _cname TEXT;
        BEGIN
            SELECT conname INTO _cname
            FROM pg_constraint
            WHERE conrelid = 'public.pipeline_run_log'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%status%';

            IF _cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE public.pipeline_run_log DROP CONSTRAINT %I', _cname);
            END IF;
        END;
        $$
        """)
    )

    conn.execute(
        text("""
        ALTER TABLE public.pipeline_run_log
            ADD CONSTRAINT pipeline_run_log_status_check
            CHECK (status IN ('running', 'complete', 'failed'))
        """)
    )
