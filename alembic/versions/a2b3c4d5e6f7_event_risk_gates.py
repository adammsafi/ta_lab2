"""event_risk_gates

Phase 71: Event Risk Gates -- database foundation.

Creates 4 new tables for macro-event-driven trading gates:

1. dim_macro_events: Calendar of scheduled macro events (FOMC, CPI, NFP).
   One row per event occurrence. Source of truth for event timing.
   PK: event_id (SERIAL). Unique on (event_type, event_ts).

2. dim_macro_gate_state: Live gate state for 8 gate types.
   Tracks current gate state ('normal','reduce','flatten'), size multiplier,
   trigger reason, and cooldown expiry. One row per gate.
   PK: gate_id (TEXT). Seeded with 8 rows at migration time.

3. cmc_macro_stress_history: Time series of composite macro stress scores.
   Stores composite_score, stress_tier, and raw factor inputs.
   PK: ts (TIMESTAMPTZ). Used by composite gate logic.

4. dim_macro_gate_overrides: Per-gate operator overrides with expiry.
   Supports disable_gate, force_normal, force_reduce override types.
   PK: override_id (UUID). Partial index on active (non-reverted) overrides.

Extends cmc_risk_events CHECK constraints:
- chk_risk_events_type: adds 5 macro gate event types
- chk_risk_events_source: adds 'macro_gate' source

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: a2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# -- Revision identifiers --------------------------------------------------
revision = "a2b3c4d5e6f7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Table 1: dim_macro_events ─────────────────────────────────────────
    # Calendar of scheduled macro events. One row per event occurrence.
    # event_type: 'fomc', 'cpi', 'nfp' (expandable)
    # source: 'hardcoded', 'fred_api' (where dates came from)
    op.create_table(
        "dim_macro_events",
        sa.Column(
            "event_id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        # Category of macro event
        sa.Column("event_type", sa.Text(), nullable=False),
        # Exact UTC timestamp of event announcement/release
        sa.Column("event_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        # Data period this event covers, e.g. '2026-01' for Jan CPI
        sa.Column("data_period", sa.Text(), nullable=False),
        # Where this date came from: 'hardcoded' or 'fred_api'
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_dim_macro_events"),
        sa.UniqueConstraint(
            "event_type", "event_ts", name="uq_dim_macro_events_type_ts"
        ),
    )

    # Index: chronological lookup within event type
    op.create_index(
        "idx_dim_macro_events_type_ts",
        "dim_macro_events",
        ["event_type", sa.text("event_ts ASC")],
    )

    # Index: upcoming events by timestamp
    op.create_index(
        "idx_dim_macro_events_ts",
        "dim_macro_events",
        [sa.text("event_ts ASC")],
    )

    # ── Table 2: dim_macro_gate_state ─────────────────────────────────────
    # Live gate state for 8 gate types (fomc, cpi, nfp, vix, carry, credit,
    # freshness, composite). One row per gate, seeded at migration time.
    # gate_state: 'normal' = full size, 'reduce' = scaled down, 'flatten' = no new positions
    # size_mult: multiplier applied to position sizes when gate is reduce/flatten
    op.create_table(
        "dim_macro_gate_state",
        # Natural PK: gate identifier string
        sa.Column("gate_id", sa.Text(), nullable=False),
        # Current gate state
        sa.Column(
            "gate_state",
            sa.Text(),
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
        # Size multiplier: 1.0 = normal, 0.5 = half size, 0.0 = flatten
        sa.Column(
            "size_mult",
            sa.Numeric(),
            server_default=sa.text("1.0"),
            nullable=False,
        ),
        # When the gate was last triggered (NULL = never triggered)
        sa.Column("triggered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Human-readable reason for current trigger
        sa.Column("trigger_reason", sa.Text(), nullable=True),
        # When the gate was last cleared (NULL = never cleared or still active)
        sa.Column("cleared_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Metadata timestamp
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # When cooldown expires after clearing (allows re-trigger suppression)
        sa.Column("cooldown_ends_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("gate_id", name="pk_dim_macro_gate_state"),
        sa.CheckConstraint(
            "gate_state IN ('normal', 'reduce', 'flatten')",
            name="chk_macro_gate_state",
        ),
        sa.CheckConstraint(
            "size_mult BETWEEN 0.0 AND 1.0",
            name="chk_macro_gate_size_mult",
        ),
    )

    # Seed 8 gate rows: all start in normal state with full size multiplier
    # Gate types:
    #   fomc     -- FOMC meeting window gate (event-driven)
    #   cpi      -- CPI release window gate (event-driven)
    #   nfp      -- NFP release window gate (event-driven)
    #   vix      -- VIX percentile gate (market-condition driven)
    #   carry    -- Carry velocity gate (market-condition driven)
    #   credit   -- HY OAS z-score gate (market-condition driven)
    #   freshness -- Data freshness gate (data-quality driven)
    #   composite -- Composite macro stress gate (multi-source)
    op.execute(
        sa.text(
            "INSERT INTO public.dim_macro_gate_state (gate_id)"
            " VALUES"
            " ('fomc'), ('cpi'), ('nfp'),"
            " ('vix'), ('carry'), ('credit'),"
            " ('freshness'), ('composite')"
            " ON CONFLICT (gate_id) DO NOTHING"
        )
    )

    # ── Table 3: cmc_macro_stress_history ─────────────────────────────────
    # Time series of composite macro stress scores and factor inputs.
    # One row per evaluation timestamp. Used by composite gate logic.
    # stress_tier: qualitative regime ('calm','elevated','stressed','crisis')
    op.create_table(
        "cmc_macro_stress_history",
        # Timestamp of this stress evaluation
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        # Composite stress score (0..1 scale, higher = more stressed)
        sa.Column("composite_score", sa.Numeric(), nullable=False),
        # Qualitative tier derived from composite_score thresholds
        sa.Column("stress_tier", sa.Text(), nullable=False),
        # Raw factor inputs (nullable: only populated when data available)
        # VIX percentile in [0,1] window (rolling 90d)
        sa.Column("vix_percentile", sa.Numeric(), nullable=True),
        # HY OAS z-score (rolling 90d window)
        sa.Column("hy_oas_zscore", sa.Numeric(), nullable=True),
        # FX carry velocity z-score (rolling 30d)
        sa.Column("carry_velocity_zscore", sa.Numeric(), nullable=True),
        # NFCI level (raw, not z-scored; higher = tighter financial conditions)
        sa.Column("nfci_level", sa.Numeric(), nullable=True),
        # Raw values for audit trail
        sa.Column("vix_raw", sa.Numeric(), nullable=True),
        sa.Column("hy_oas_raw", sa.Numeric(), nullable=True),
        sa.Column("dexjpus_zscore_raw", sa.Numeric(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("ts", name="pk_cmc_macro_stress_history"),
        sa.CheckConstraint(
            "stress_tier IN ('calm', 'elevated', 'stressed', 'crisis')",
            name="chk_macro_stress_tier",
        ),
    )

    # Index: most recent stress evaluations first
    op.create_index(
        "idx_cmc_macro_stress_history_ts",
        "cmc_macro_stress_history",
        [sa.text("ts DESC")],
    )

    # Partial index: crisis-tier events for fast alert lookups
    op.create_index(
        "idx_cmc_macro_stress_crisis",
        "cmc_macro_stress_history",
        [sa.text("ts DESC")],
        postgresql_where=sa.text("stress_tier = 'crisis'"),
    )

    # ── Table 4: dim_macro_gate_overrides ─────────────────────────────────
    # Per-gate operator overrides with expiry.
    # Allows manual suppression or forcing of gate states.
    # override_type meanings:
    #   disable_gate  -- Prevent gate from triggering (treat as normal always)
    #   force_normal  -- Force gate to normal state (bypass active trigger)
    #   force_reduce  -- Force gate to reduce state (proactive risk reduction)
    op.create_table(
        "dim_macro_gate_overrides",
        sa.Column(
            "override_id",
            UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Which gate this override applies to (FK to dim_macro_gate_state.gate_id)
        sa.Column("gate_id", sa.Text(), nullable=False),
        # Who created this override (operator identifier)
        sa.Column("operator", sa.Text(), nullable=False),
        # Human-readable reason for override
        sa.Column("reason", sa.Text(), nullable=False),
        # Override type: disable_gate, force_normal, force_reduce
        sa.Column("override_type", sa.Text(), nullable=False),
        # When this override automatically expires
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # When this override was manually reverted (NULL = still active)
        sa.Column("reverted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Reason for manual revert
        sa.Column("revert_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("override_id", name="pk_dim_macro_gate_overrides"),
        sa.CheckConstraint(
            "override_type IN ('disable_gate', 'force_normal', 'force_reduce')",
            name="chk_macro_gate_override_type",
        ),
    )

    # Partial index: active (non-reverted) overrides per gate for fast lookup
    op.create_index(
        "idx_dim_macro_gate_overrides_active",
        "dim_macro_gate_overrides",
        ["gate_id", sa.text("expires_at ASC")],
        postgresql_where=sa.text("reverted_at IS NULL"),
    )

    # ── Extend cmc_risk_events CHECK constraints ───────────────────────────
    # Drop and recreate chk_risk_events_type with 5 new macro gate event types.
    # Current state (from 30eac3660488_perps_readiness.py, 15 types):
    #   kill_switch_activated, kill_switch_disabled,
    #   position_cap_scaled, position_cap_blocked,
    #   daily_loss_stop_triggered,
    #   circuit_breaker_tripped, circuit_breaker_reset,
    #   override_created, override_applied, override_reverted,
    #   tail_risk_escalated, tail_risk_cleared,
    #   liquidation_warning, liquidation_critical, margin_alert
    # Adding 5 new macro gate types = 20 total
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_type"
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
            'tail_risk_escalated', 'tail_risk_cleared',
            'liquidation_warning', 'liquidation_critical', 'margin_alert',
            'macro_event_gate_triggered', 'macro_stress_gate_triggered',
            'macro_gate_cleared', 'macro_gate_override_created',
            'macro_gate_override_expired'
        ))
        """
    )

    # Drop and recreate chk_risk_events_source with 'macro_gate'.
    # Current state (from 30eac3660488_perps_readiness.py, 6 sources):
    #   manual, daily_loss_stop, circuit_breaker, system, tail_risk, margin_monitor
    # Adding 1 new source = 7 total
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_source"
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_source
        CHECK (trigger_source IN (
            'manual', 'daily_loss_stop', 'circuit_breaker',
            'system', 'tail_risk', 'margin_monitor', 'macro_gate'
        ))
        """
    )


def downgrade() -> None:
    # ── Revert cmc_risk_events CHECK constraints ───────────────────────────
    # Restore chk_risk_events_source (remove 'macro_gate')
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_source"
    )
    op.execute(
        """
        ALTER TABLE public.cmc_risk_events
        ADD CONSTRAINT chk_risk_events_source
        CHECK (trigger_source IN (
            'manual', 'daily_loss_stop', 'circuit_breaker',
            'system', 'tail_risk', 'margin_monitor'
        ))
        """
    )

    # Restore chk_risk_events_type (remove 5 macro gate event types)
    op.execute(
        "ALTER TABLE public.cmc_risk_events"
        " DROP CONSTRAINT IF EXISTS chk_risk_events_type"
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
            'tail_risk_escalated', 'tail_risk_cleared',
            'liquidation_warning', 'liquidation_critical', 'margin_alert'
        ))
        """
    )

    # ── Drop Table 4: dim_macro_gate_overrides ────────────────────────────
    op.drop_index(
        "idx_dim_macro_gate_overrides_active",
        table_name="dim_macro_gate_overrides",
    )
    op.drop_table("dim_macro_gate_overrides")

    # ── Drop Table 3: cmc_macro_stress_history ────────────────────────────
    op.drop_index(
        "idx_cmc_macro_stress_crisis",
        table_name="cmc_macro_stress_history",
    )
    op.drop_index(
        "idx_cmc_macro_stress_history_ts",
        table_name="cmc_macro_stress_history",
    )
    op.drop_table("cmc_macro_stress_history")

    # ── Drop Table 2: dim_macro_gate_state ────────────────────────────────
    op.drop_table("dim_macro_gate_state")

    # ── Drop Table 1: dim_macro_events ────────────────────────────────────
    op.drop_index(
        "idx_dim_macro_events_ts",
        table_name="dim_macro_events",
    )
    op.drop_index(
        "idx_dim_macro_events_type_ts",
        table_name="dim_macro_events",
    )
    op.drop_table("dim_macro_events")
