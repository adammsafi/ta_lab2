"""Phase 87 live pipeline and alert wiring schema.

Creates:
  pipeline_run_log       - Dead-man switch audit: one row per daily pipeline run.
  signal_anomaly_log     - Audit log for signal validation gate decisions.
  pipeline_alert_log     - Throttle log for all Phase 87 alert types.
  dim_ic_weight_overrides - BL weight halving for IC-decayed features.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-03-24
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# -- Revision identifiers --------------------------------------------------
revision: str = "n8o9p0q1r2s3"
down_revision: Union[str, Sequence[str], None] = "m7n8o9p0q1r2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # pipeline_run_log
    # One row per daily pipeline run -- used as a dead-man switch audit.
    # status CHECK: running -> complete (success) or failed (error).
    # stages_completed JSONB: ordered list of completed stage names.
    # total_duration_sec: wall-clock seconds from started_at to completed_at.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.pipeline_run_log (
            run_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at        TIMESTAMPTZ,
            status              VARCHAR(20) NOT NULL DEFAULT 'running'
                                    CHECK (status IN ('running', 'complete', 'failed')),
            stages_completed    JSONB       DEFAULT '[]',
            total_duration_sec  NUMERIC,
            error_message       TEXT
        )
        """)
    )

    # ------------------------------------------------------------------
    # signal_anomaly_log
    # Audit log for signal validation gate decisions.
    # anomaly_type CHECK: count_anomaly, strength_anomaly, crowded_signal.
    # blocked = TRUE means signal was held back from executor.
    # count_zscore: (count_today - count_mean) / count_std for count anomalies.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.signal_anomaly_log (
            check_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            signal_type     VARCHAR(50) NOT NULL,
            anomaly_type    VARCHAR(50) NOT NULL
                                CHECK (anomaly_type IN (
                                    'count_anomaly', 'strength_anomaly', 'crowded_signal'
                                )),
            severity        VARCHAR(20) NOT NULL,
            count_today     INTEGER,
            count_mean      NUMERIC,
            count_zscore    NUMERIC,
            blocked         BOOLEAN     NOT NULL DEFAULT FALSE,
            notes           TEXT
        )
        """)
    )

    # ------------------------------------------------------------------
    # pipeline_alert_log
    # Throttle log for all Phase 87 alert types.
    # alert_key: a discriminator within the alert_type (e.g. feature name
    #   for ic_decay, signal_type for signal_anomaly).
    # throttled = TRUE means the alert fired but Telegram send was suppressed.
    # INDEX on (alert_type, alert_key, sent_at) for efficient throttle queries.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.pipeline_alert_log (
            alert_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            alert_type      VARCHAR(50) NOT NULL,
            alert_key       VARCHAR(100),
            severity        VARCHAR(20) NOT NULL,
            message_preview TEXT,
            sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            throttled       BOOLEAN     NOT NULL DEFAULT FALSE
        )
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_pipeline_alert_log_throttle
            ON public.pipeline_alert_log (alert_type, alert_key, sent_at)
        """)
    )

    # ------------------------------------------------------------------
    # dim_ic_weight_overrides
    # BL weight-halving dimension table for IC-decayed features.
    # asset_id NULL = override applies to all assets for this feature.
    # multiplier = fractional weight factor (0.5 = halved, default).
    # expires_at NULL = override never expires automatically.
    # cleared_at NOT NULL = override was manually cleared (soft delete).
    # UNIQUE on (feature, COALESCE(asset_id, -1)) -- one active override
    #   per (feature, asset) pair; ON CONFLICT DO NOTHING for idempotent inserts.
    # ------------------------------------------------------------------
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.dim_ic_weight_overrides (
            override_id     SERIAL      PRIMARY KEY,
            feature         TEXT        NOT NULL,
            asset_id        INTEGER,
            multiplier      NUMERIC     NOT NULL DEFAULT 0.5,
            reason          TEXT,
            created_at      TIMESTAMPTZ DEFAULT now(),
            expires_at      TIMESTAMPTZ,
            cleared_at      TIMESTAMPTZ
        )
        """)
    )

    conn.execute(
        text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ic_weight_overrides
            ON public.dim_ic_weight_overrides (feature, COALESCE(asset_id, -1))
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("DROP INDEX IF EXISTS public.uq_ic_weight_overrides"))
    conn.execute(text("DROP TABLE IF EXISTS public.dim_ic_weight_overrides"))
    conn.execute(text("DROP INDEX IF EXISTS public.ix_pipeline_alert_log_throttle"))
    conn.execute(text("DROP TABLE IF EXISTS public.pipeline_alert_log"))
    conn.execute(text("DROP TABLE IF EXISTS public.signal_anomaly_log"))
    conn.execute(text("DROP TABLE IF EXISTS public.pipeline_run_log"))
