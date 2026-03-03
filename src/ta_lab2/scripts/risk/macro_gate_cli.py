"""Macro gate override management CLI.

Provides 4 subcommands for managing macro gate overrides and inspecting gate state:

  create  -- Create a gate override (disable_gate, force_normal, force_reduce)
  list    -- List active (non-reverted, non-expired) overrides
  revert  -- Revert an active override
  status  -- Print current state of all 8 macro gates from dim_macro_gate_state

Usage examples::

    python -m ta_lab2.scripts.risk.macro_gate_cli status

    python -m ta_lab2.scripts.risk.macro_gate_cli create \\
        --gate-id vix --type disable_gate \\
        --reason "Known vol spike, not fundamental" --operator asafi

    python -m ta_lab2.scripts.risk.macro_gate_cli create \\
        --gate-id fomc --type force_reduce \\
        --reason "Pre-emptive FOMC caution" --operator asafi --expires-hours 48

    python -m ta_lab2.scripts.risk.macro_gate_cli list
    python -m ta_lab2.scripts.risk.macro_gate_cli list --gate-id vix
    python -m ta_lab2.scripts.risk.macro_gate_cli list --all

    python -m ta_lab2.scripts.risk.macro_gate_cli revert \\
        --override-id <uuid> --reason "Resolved" --operator asafi

Override types:
    disable_gate  -- Prevent gate from triggering (treat as normal always)
    force_normal  -- Force gate to normal state (bypass active trigger)
    force_reduce  -- Force gate to reduce state (proactive risk reduction)

Environment / config:
    Database URL is resolved via resolve_db_url() which checks:
    1. --db-url CLI flag (if provided)
    2. db_config.env file (searched up to 5 dirs up)
    3. TARGET_DB_URL environment variable
    4. MARKETDATA_DB_URL environment variable
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.risk.macro_gate_overrides import GateOverrideManager
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# Gate IDs recognized by the macro gate evaluator
_VALID_GATE_IDS = frozenset(
    {"fomc", "cpi", "nfp", "vix", "carry", "credit", "freshness", "composite"}
)

# Override types (matches dim_macro_gate_overrides CHECK constraint)
_VALID_OVERRIDE_TYPES = frozenset({"disable_gate", "force_normal", "force_reduce"})

# Gate display names for the status table
_GATE_DISPLAY_NAMES: dict[str, str] = {
    "fomc": "FOMC window (+/-24h)",
    "cpi": "CPI window (+/-24h)",
    "nfp": "NFP window (+/-12h)",
    "vix": "VIX level (>30 reduce)",
    "carry": "Carry unwind (JPY z>2)",
    "credit": "Credit spread (HY OAS z)",
    "freshness": "Data freshness",
    "composite": "Composite stress score",
}


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    """Handle 'create' subcommand -- create a new gate override."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)
    mgr = GateOverrideManager(engine)

    override_id = mgr.create_override(
        gate_id=args.gate_id,
        operator=args.operator,
        reason=args.reason,
        override_type=args.type,
        expires_hours=args.expires_hours,
    )

    print(f"Override created: {override_id}")
    print(f"  Gate:         {args.gate_id}")
    print(f"  Type:         {args.type}")
    print(f"  Reason:       {args.reason}")
    print(f"  Operator:     {args.operator}")
    print(f"  Expires in:   {args.expires_hours:.1f} hours")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Handle 'list' subcommand -- list overrides."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)
    mgr = GateOverrideManager(engine)

    gate_id = getattr(args, "gate_id", None)

    if getattr(args, "all", False):
        # Include expired/reverted overrides
        overrides = _get_all_overrides(engine, gate_id=gate_id)
        title = "All Overrides (including expired/reverted)"
    else:
        overrides = mgr.get_active_overrides(gate_id=gate_id)
        title = "Active Overrides"

    if not overrides:
        print(f"No overrides found ({title.lower()}).")
        return 0

    _print_overrides_table(overrides, title=title)
    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    """Handle 'revert' subcommand -- revert an active override."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)
    mgr = GateOverrideManager(engine)

    reverted = mgr.revert_override(
        override_id=args.override_id,
        reason=args.reason,
        operator=args.operator,
    )

    if not reverted:
        print(
            f"ERROR: Override {args.override_id} not found or already reverted.",
            file=sys.stderr,
        )
        return 1

    print(f"Override reverted: {args.override_id}")
    print(f"  Reason:   {args.reason}")
    print(f"  Operator: {args.operator}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Handle 'status' subcommand -- print current gate states."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT gate_id, gate_state, size_mult,
                           trigger_reason, triggered_at, cooldown_ends_at
                    FROM public.dim_macro_gate_state
                    ORDER BY gate_id
                    """
                )
            ).fetchall()
    except Exception as exc:
        print(f"ERROR: Could not read dim_macro_gate_state: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print(
            "No gate states in dim_macro_gate_state. "
            "Run evaluate_macro_gates to populate."
        )
        return 0

    _print_status_table(rows)
    return 0


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _print_status_table(rows) -> None:
    """Print gate states as a formatted table."""
    state_indicators = {"normal": "  ", "reduce": ">>", "flatten": "!!"}
    state_labels = {"normal": "NORMAL", "reduce": "REDUCE", "flatten": "FLATTEN"}

    print("Macro Gate Status")
    print("=" * 80)
    header = f"{'':2}  {'Gate':<28}  {'State':<8}  {'SizeMult':>8}  {'Cooldown ends'}"
    print(header)
    print("-" * 80)

    state_order = {"normal": 0, "reduce": 1, "flatten": 2}
    worst_state = "normal"
    worst_mult = 1.0
    active_gates: list[str] = []

    for row in rows:
        m = row._mapping
        gate_id = str(m["gate_id"])
        state = str(m["gate_state"])
        size_mult = float(m["size_mult"])
        cooldown_ends_at = m["cooldown_ends_at"]

        if state != "normal":
            active_gates.append(gate_id)
            if state_order.get(state, 0) > state_order.get(worst_state, 0):
                worst_state = state
                worst_mult = size_mult
            elif state == worst_state and size_mult < worst_mult:
                worst_mult = size_mult

        indicator = state_indicators.get(state, "  ")
        state_label = state_labels.get(state, state.upper())
        display_name = _GATE_DISPLAY_NAMES.get(gate_id, gate_id)

        # Format cooldown timestamp
        if cooldown_ends_at is not None:
            if hasattr(cooldown_ends_at, "tzinfo") and cooldown_ends_at.tzinfo is None:
                cooldown_ends_at = cooldown_ends_at.replace(tzinfo=timezone.utc)
            cooldown_str = cooldown_ends_at.strftime("%Y-%m-%d %H:%M UTC")
        else:
            cooldown_str = "-"

        print(
            f"{indicator}  {display_name:<28}  {state_label:<8}  "
            f"{size_mult:>8.2f}  {cooldown_str}"
        )

    print("-" * 80)
    worst_label = state_labels.get(worst_state, worst_state.upper())
    print(f"Overall (worst-of): {worst_label}  size_mult={worst_mult:.2f}")
    if active_gates:
        print(f"Active gates: {', '.join(active_gates)}")
    else:
        print("Active gates: none")
    print("=" * 80)


def _print_overrides_table(overrides: list[dict], title: str = "Overrides") -> None:
    """Print overrides as a formatted table."""
    print(title)
    header = (
        f"{'UUID':<36}  {'Gate':<10}  {'Type':<14}  "
        f"{'Operator':<10}  {'Expires at':<20}  Reason"
    )
    separator = "-" * (len(header) + 4)
    print(separator)
    print(header)
    print(separator)

    for o in overrides:
        override_id = str(o.get("override_id", ""))
        gate_id = str(o.get("gate_id", ""))
        override_type = str(o.get("override_type", ""))
        operator = str(o.get("operator", ""))
        reason = str(o.get("reason", ""))
        expires_at = o.get("expires_at")
        reverted_at = o.get("reverted_at")

        # Show expiry or reverted status
        if reverted_at is not None:
            expires_str = "[reverted]"
        elif expires_at is not None:
            if hasattr(expires_at, "strftime"):
                expires_str = expires_at.strftime("%Y-%m-%d %H:%M UTC")
            else:
                expires_str = str(expires_at)
        else:
            expires_str = "-"

        # Truncate reason
        max_reason = 30
        if len(reason) > max_reason:
            reason = reason[: max_reason - 3] + "..."

        print(
            f"{override_id:<36}  {gate_id:<10}  {override_type:<14}  "
            f"{operator:<10}  {expires_str:<20}  {reason}"
        )

    print(separator)
    print(f"Total: {len(overrides)} override(s)")


def _get_all_overrides(engine, gate_id: str | None = None) -> list[dict]:
    """Return all overrides including expired and reverted ones."""
    base_sql = """
        SELECT override_id, gate_id, operator, reason,
               override_type, expires_at, created_at, reverted_at
        FROM public.dim_macro_gate_overrides
    """
    params: dict = {}

    if gate_id is not None:
        base_sql += " WHERE gate_id = :gate_id"
        params["gate_id"] = gate_id

    base_sql += " ORDER BY created_at DESC"

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(base_sql), params).fetchall()
    except Exception as exc:
        logger.error("Failed to query dim_macro_gate_overrides: %s", exc)
        return []

    results = []
    for row in rows:
        m = row._mapping
        results.append(
            {
                "override_id": str(m["override_id"]),
                "gate_id": str(m["gate_id"]),
                "operator": str(m["operator"]),
                "reason": str(m["reason"]),
                "override_type": str(m["override_type"]),
                "expires_at": m["expires_at"],
                "created_at": m["created_at"],
                "reverted_at": m.get("reverted_at"),
            }
        )
    return results


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="macro_gate_cli",
        description=(
            "Macro gate override management. Create, list, revert overrides "
            "or inspect current gate state."
        ),
    )
    parser.add_argument(
        "--db-url",
        metavar="URL",
        help="PostgreSQL connection URL (default: resolved from db_config.env or environment)",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: WARNING)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # -- create --
    create_parser = subparsers.add_parser(
        "create",
        help="Create a new gate override",
    )
    create_parser.add_argument(
        "--gate-id",
        required=True,
        metavar="GATE",
        choices=sorted(_VALID_GATE_IDS),
        help=f"Gate to override. Valid values: {', '.join(sorted(_VALID_GATE_IDS))}",
    )
    create_parser.add_argument(
        "--type",
        required=True,
        dest="type",
        metavar="TYPE",
        choices=sorted(_VALID_OVERRIDE_TYPES),
        help=(
            "Override type. "
            "disable_gate: prevent gate from triggering. "
            "force_normal: force gate to normal state. "
            "force_reduce: force gate to reduce state."
        ),
    )
    create_parser.add_argument(
        "--reason",
        required=True,
        metavar="TEXT",
        help="Mandatory justification for the override",
    )
    create_parser.add_argument(
        "--operator",
        required=True,
        metavar="NAME",
        help="Username of the operator creating the override",
    )
    create_parser.add_argument(
        "--expires-hours",
        type=float,
        default=24.0,
        metavar="HOURS",
        dest="expires_hours",
        help="Hours until the override auto-expires (default: 24.0)",
    )
    create_parser.set_defaults(func=cmd_create)

    # -- list --
    list_parser = subparsers.add_parser(
        "list",
        help="List gate overrides (active by default)",
    )
    list_parser.add_argument(
        "--gate-id",
        metavar="GATE",
        help="Filter to a specific gate ID (optional)",
    )
    list_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        dest="all",
        help="Include expired and reverted overrides (default: active only)",
    )
    list_parser.set_defaults(func=cmd_list)

    # -- revert --
    revert_parser = subparsers.add_parser(
        "revert",
        help="Revert an active override",
    )
    revert_parser.add_argument(
        "--override-id",
        required=True,
        metavar="UUID",
        dest="override_id",
        help="UUID of the override to revert",
    )
    revert_parser.add_argument(
        "--reason",
        required=True,
        metavar="TEXT",
        help="Reason for reverting the override",
    )
    revert_parser.add_argument(
        "--operator",
        required=True,
        metavar="NAME",
        help="Username of the operator reverting the override",
    )
    revert_parser.set_defaults(func=cmd_revert)

    # -- status --
    status_parser = subparsers.add_parser(
        "status",
        help="Print current state of all 8 macro gates from dim_macro_gate_state",
    )
    status_parser.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
