"""macro_drift_attribution

Phase 72: Macro Observability -- database foundation.

Changes:
1. Adds attr_macro_regime_delta FLOAT column to cmc_drift_metrics.
   Used by DriftMonitor to capture macro regime delta attribution --
   how much of observed drift is attributable to macro regime changes.

2. Creates cmc_macro_alert_log table for Telegram alerting with
   throttling support.  One row per alert sent or throttled, keyed by
   alert_type (dimension_change vs composite_change), dimension (nullable),
   and the old/new label.

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: e6f7a8b9c0d1
Revises: a2b3c4d5e6f7
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

# -- Revision identifiers --------------------------------------------------
revision = "e6f7a8b9c0d1"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Column: cmc_drift_metrics.attr_macro_regime_delta ─────────────────
    # Nullable FLOAT -- populated by DriftMonitor when macro regime changes
    # are a contributing source of drift.  NULL = not yet computed or not
    # applicable for the row's metric_date.
    op.add_column(
        "cmc_drift_metrics",
        sa.Column(
            "attr_macro_regime_delta",
            sa.Float(),
            nullable=True,
            comment=(
                "Macro regime delta attribution: fraction of drift "
                "attributable to macro regime change. NULL if not computed."
            ),
        ),
    )

    # ── Table: cmc_macro_alert_log ─────────────────────────────────────────
    # Telegram alert throttling log.  Every alert attempt (sent or throttled)
    # is recorded here.  Query pattern: check recent rows for same
    # (alert_type, dimension) before sending to enforce cooldown windows.
    #
    # alert_type values:
    #   dimension_change  -- Per-dimension label changed (monetary_policy, etc.)
    #   composite_change  -- Composite regime_key changed
    #
    # dimension: NULL for composite_change rows, otherwise the dimension name
    #   that changed (e.g. 'monetary_policy', 'liquidity', etc.)
    op.create_table(
        "cmc_macro_alert_log",
        sa.Column(
            "alert_id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        # Type of alert: dimension_change or composite_change
        sa.Column("alert_type", sa.Text(), nullable=False),
        # Which dimension changed (NULL for composite_change rows)
        sa.Column("dimension", sa.Text(), nullable=True),
        # Previous label value (e.g. 'Hiking', 'favorable')
        sa.Column("old_label", sa.Text(), nullable=False),
        # New label value
        sa.Column("new_label", sa.Text(), nullable=False),
        # Composite regime key at time of alert (e.g. 'C-N-R-S')
        sa.Column("regime_key", sa.Text(), nullable=True),
        # Composite macro state at time of alert (e.g. 'adverse')
        sa.Column("macro_state", sa.Text(), nullable=True),
        # When this alert was logged (sent or throttled)
        sa.Column(
            "sent_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # True if the alert was suppressed by throttle logic (not actually sent)
        sa.Column(
            "throttled",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("alert_id", name="pk_cmc_macro_alert_log"),
        sa.CheckConstraint(
            "alert_type IN ('dimension_change', 'composite_change')",
            name="chk_macro_alert_log_type",
        ),
    )

    # Index: recent alerts by time (primary query pattern for throttle checks)
    op.create_index(
        "idx_cmc_macro_alert_log_sent_at",
        "cmc_macro_alert_log",
        [sa.text("sent_at DESC")],
    )


def downgrade() -> None:
    # ── Drop cmc_macro_alert_log ───────────────────────────────────────────
    op.drop_index(
        "idx_cmc_macro_alert_log_sent_at",
        table_name="cmc_macro_alert_log",
    )
    op.drop_table("cmc_macro_alert_log")

    # ── Drop attr_macro_regime_delta column ────────────────────────────────
    op.drop_column("cmc_drift_metrics", "attr_macro_regime_delta")
