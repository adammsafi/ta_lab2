"""tail_risk_policy

Schema changes for Phase 49 (Tail-Risk Policy):

1. ALTER dim_risk_state: add tail_risk_state TEXT with CHECK constraint
2. ALTER dim_risk_state: add tail_risk_triggered_at, tail_risk_trigger_reason, tail_risk_cleared_at
3. DROP + RECREATE cmc_risk_events event_type CHECK with new tail risk event types
4. DROP + RECREATE cmc_risk_events trigger_source CHECK with tail_risk source

Revision ID: a9ec3c00a54a
Revises: 328fdc315e1b
Create Date: 2026-02-25 16:15:12.767728
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9ec3c00a54a"
down_revision: Union[str, Sequence[str], None] = "328fdc315e1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema -- add tail_risk_state column and extend event type constraints."""

    # 1. Add tail_risk_state column to dim_risk_state (default 'normal')
    op.add_column(
        "dim_risk_state",
        sa.Column(
            "tail_risk_state",
            sa.Text(),
            nullable=False,
            server_default="normal",
        ),
    )

    # 2. CHECK constraint for tail_risk_state values
    op.execute(
        """
        ALTER TABLE public.dim_risk_state
        ADD CONSTRAINT chk_risk_state_tail
        CHECK (tail_risk_state IN ('normal', 'reduce', 'flatten'))
        """
    )

    # 3. Audit columns for tail risk state changes
    op.add_column(
        "dim_risk_state",
        sa.Column("tail_risk_triggered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dim_risk_state",
        sa.Column("tail_risk_trigger_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "dim_risk_state",
        sa.Column("tail_risk_cleared_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 4. Extend cmc_risk_events event_type CHECK -- must DROP first then RECREATE
    # Include ALL existing event types plus new tail_risk ones
    op.execute(
        "ALTER TABLE public.cmc_risk_events DROP CONSTRAINT IF EXISTS chk_risk_events_type"
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_type
        CHECK (event_type IN (
            'kill_switch_activated', 'kill_switch_disabled',
            'position_cap_scaled', 'position_cap_blocked',
            'daily_loss_stop_triggered',
            'circuit_breaker_tripped', 'circuit_breaker_reset',
            'override_created', 'override_applied', 'override_reverted',
            'tail_risk_escalated', 'tail_risk_cleared'
        ))
        """
    )

    # 5. Extend trigger_source CHECK with tail_risk
    op.execute(
        "ALTER TABLE public.cmc_risk_events DROP CONSTRAINT IF EXISTS chk_risk_events_source"
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_source
        CHECK (trigger_source IN ('manual', 'daily_loss_stop', 'circuit_breaker', 'system', 'tail_risk'))
        """
    )


def downgrade() -> None:
    """Downgrade schema -- remove tail_risk_state and revert CHECK constraints."""

    # Revert trigger_source CHECK
    op.execute(
        "ALTER TABLE public.cmc_risk_events DROP CONSTRAINT IF EXISTS chk_risk_events_source"
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_source
        CHECK (trigger_source IN ('manual', 'daily_loss_stop', 'circuit_breaker', 'system'))
        """
    )

    # Revert event_type CHECK
    op.execute(
        "ALTER TABLE public.cmc_risk_events DROP CONSTRAINT IF EXISTS chk_risk_events_type"
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_type
        CHECK (event_type IN (
            'kill_switch_activated', 'kill_switch_disabled',
            'position_cap_scaled', 'position_cap_blocked',
            'daily_loss_stop_triggered',
            'circuit_breaker_tripped', 'circuit_breaker_reset',
            'override_created', 'override_applied', 'override_reverted'
        ))
        """
    )

    # Remove tail risk audit columns
    op.execute(
        "ALTER TABLE public.dim_risk_state DROP CONSTRAINT IF EXISTS chk_risk_state_tail"
    )
    op.drop_column("dim_risk_state", "tail_risk_cleared_at")
    op.drop_column("dim_risk_state", "tail_risk_trigger_reason")
    op.drop_column("dim_risk_state", "tail_risk_triggered_at")
    op.drop_column("dim_risk_state", "tail_risk_state")
