"""Evaluate all macro risk gates and print a formatted summary.

Reads current state from dim_macro_gate_state (via MacroGateEvaluator.check_order_gates)
and evaluates all 8 gates (7 individual + composite) via MacroGateEvaluator.evaluate().
Prints a formatted table and overall composite result.

Usage::

    python -m ta_lab2.scripts.risk.evaluate_macro_gates
    python -m ta_lab2.scripts.risk.evaluate_macro_gates --json
    python -m ta_lab2.scripts.risk.evaluate_macro_gates --dry-run

Options:
    --dry-run     Read current DB state without triggering a fresh evaluate() cycle.
    --json        Output structured JSON instead of a formatted table.
    --db-url URL  Override database connection URL.

Environment / config:
    Database URL is resolved via resolve_db_url() which checks:
    1. --db-url CLI flag (if provided)
    2. db_config.env file (searched up to 5 dirs up)
    3. TARGET_DB_URL environment variable
    4. MARKETDATA_DB_URL environment variable
"""

from __future__ import annotations

import argparse
import json as _json
import logging
import sys
from datetime import timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.risk.macro_gate_evaluator import MacroGateEvaluator, MacroGateResult
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# Gate display names for the table
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

# State -> display label
_STATE_LABELS: dict[str, str] = {
    "normal": "NORMAL",
    "reduce": "REDUCE",
    "flatten": "FLATTEN",
}

# State -> display char for colour hint (no ANSI in output -- keep compatible)
_STATE_INDICATOR: dict[str, str] = {
    "normal": "  ",
    "reduce": ">>",
    "flatten": "!!",
}


# ---------------------------------------------------------------------------
# Subcommand: read current gate state from DB (dry-run mode)
# ---------------------------------------------------------------------------


def _read_gate_states_from_db(engine) -> list[dict]:
    """Read current gate states directly from dim_macro_gate_state."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT gate_id, gate_state, size_mult,
                           trigger_reason, triggered_at, cleared_at, cooldown_ends_at
                    FROM public.dim_macro_gate_state
                    ORDER BY gate_id
                    """
                )
            ).fetchall()
    except Exception as exc:
        logger.error("Failed to read dim_macro_gate_state: %s", exc)
        return []

    results = []
    for row in rows:
        m = row._mapping
        cooldown_ends_at = m["cooldown_ends_at"]
        # Ensure tz-awareness for display
        if cooldown_ends_at is not None and hasattr(cooldown_ends_at, "tzinfo"):
            if cooldown_ends_at.tzinfo is None:
                cooldown_ends_at = cooldown_ends_at.replace(tzinfo=timezone.utc)

        results.append(
            {
                "gate_id": str(m["gate_id"]),
                "gate_state": str(m["gate_state"]),
                "size_mult": float(m["size_mult"]),
                "trigger_reason": m["trigger_reason"],
                "triggered_at": m["triggered_at"],
                "cleared_at": m["cleared_at"],
                "cooldown_ends_at": cooldown_ends_at,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _format_table(gate_states: list[dict], overall: MacroGateResult | None) -> str:
    """Format gate states as a human-readable table."""
    lines = []
    lines.append("Macro Gate States")
    lines.append("=" * 80)

    header = f"{'':2}  {'Gate':<28}  {'State':<8}  {'SizeMult':>8}  {'Reason'}"
    lines.append(header)
    lines.append("-" * 80)

    for gs in gate_states:
        gate_id = gs["gate_id"]
        state = gs["gate_state"]
        size_mult = gs["size_mult"]
        reason = gs.get("trigger_reason") or "-"
        # Truncate reason to fit in terminal
        max_reason_len = 80 - 2 - 1 - 28 - 1 - 8 - 1 - 8 - 2
        if len(reason) > max_reason_len:
            reason = reason[: max_reason_len - 3] + "..."

        indicator = _STATE_INDICATOR.get(state, "  ")
        state_label = _STATE_LABELS.get(state, state.upper())
        display_name = _GATE_DISPLAY_NAMES.get(gate_id, gate_id)

        lines.append(
            f"{indicator}  {display_name:<28}  {state_label:<8}  {size_mult:>8.2f}  {reason}"
        )

    lines.append("-" * 80)

    if overall is not None:
        lines.append(
            f"Overall (worst-of): {_STATE_LABELS.get(overall.state, overall.state.upper())}  "
            f"size_mult={overall.size_mult:.2f}"
        )
        if overall.active_gates:
            lines.append(f"Active gates: {', '.join(overall.active_gates)}")
        else:
            lines.append("Active gates: none")
        lines.append(f"Details: {overall.details}")
    else:
        # Dry-run mode: compute overall from DB state
        state_order = {"normal": 0, "reduce": 1, "flatten": 2}
        worst_state = "normal"
        worst_mult = 1.0
        active_gates = []

        for gs in gate_states:
            s = gs["gate_state"]
            m = gs["size_mult"]
            if s != "normal":
                active_gates.append(gs["gate_id"])
                if state_order.get(s, 0) > state_order.get(worst_state, 0):
                    worst_state = s
                    worst_mult = m
                elif s == worst_state and m < worst_mult:
                    worst_mult = m

        lines.append(
            f"Overall (worst-of from DB): {_STATE_LABELS.get(worst_state, worst_state.upper())}  "
            f"size_mult={worst_mult:.2f}"
        )
        if active_gates:
            lines.append(f"Active gates: {', '.join(active_gates)}")
        else:
            lines.append("Active gates: none")

    lines.append("=" * 80)
    return "\n".join(lines)


def _format_json(gate_states: list[dict], overall: MacroGateResult | None) -> str:
    """Format gate states as structured JSON."""

    # Serialize datetimes to ISO strings
    def _serialize(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    gate_list = []
    for gs in gate_states:
        gate_list.append(
            {
                "gate_id": gs["gate_id"],
                "gate_state": gs["gate_state"],
                "size_mult": gs["size_mult"],
                "trigger_reason": gs.get("trigger_reason"),
                "triggered_at": _serialize(gs["triggered_at"])
                if gs.get("triggered_at")
                else None,
                "cleared_at": _serialize(gs["cleared_at"])
                if gs.get("cleared_at")
                else None,
                "cooldown_ends_at": _serialize(gs["cooldown_ends_at"])
                if gs.get("cooldown_ends_at")
                else None,
            }
        )

    if overall is not None:
        overall_dict = {
            "state": overall.state,
            "size_mult": overall.size_mult,
            "active_gates": overall.active_gates,
            "details": overall.details,
        }
    else:
        # Compute overall from DB rows
        state_order = {"normal": 0, "reduce": 1, "flatten": 2}
        worst_state = "normal"
        worst_mult = 1.0
        active_gates = []

        for gs in gate_states:
            s = gs["gate_state"]
            m = gs["size_mult"]
            if s != "normal":
                active_gates.append(gs["gate_id"])
                if state_order.get(s, 0) > state_order.get(worst_state, 0):
                    worst_state = s
                    worst_mult = m
                elif s == worst_state and m < worst_mult:
                    worst_mult = m

        overall_dict = {
            "state": worst_state,
            "size_mult": worst_mult,
            "active_gates": active_gates,
            "details": "(read from DB -- dry-run mode)",
        }

    output = {
        "gates": gate_list,
        "overall": overall_dict,
    }
    return _json.dumps(output, indent=2, default=_serialize)


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Run gate evaluation and print results."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)

    evaluator = MacroGateEvaluator(engine)
    overall: MacroGateResult | None = None

    if args.dry_run:
        # Read current state from DB without triggering a fresh evaluate() cycle
        gate_states = _read_gate_states_from_db(engine)
        if not gate_states:
            print(
                "No gate states found in dim_macro_gate_state. "
                "Run without --dry-run to populate.",
                file=sys.stderr,
            )
            return 1
    else:
        # Full evaluation -- runs all gate logic and updates DB
        overall = evaluator.evaluate()
        gate_states = _read_gate_states_from_db(engine)

    if args.json:
        print(_format_json(gate_states, overall))
    else:
        print(_format_table(gate_states, overall))

    # Exit code 0 = normal, 1 = reduce, 2 = flatten
    if overall is not None:
        state = overall.state
    elif gate_states:
        state_order = {"normal": 0, "reduce": 1, "flatten": 2}
        worst = max(gate_states, key=lambda g: state_order.get(g["gate_state"], 0))
        state = worst["gate_state"]
    else:
        state = "normal"

    exit_codes = {"normal": 0, "reduce": 1, "flatten": 2}
    return exit_codes.get(state, 0)


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="evaluate_macro_gates",
        description=(
            "Evaluate all macro risk gates and print state summary. "
            "Exit code: 0=normal, 1=reduce, 2=flatten."
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Read current DB state without triggering a fresh evaluate() cycle",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="json",
        help="Output structured JSON instead of formatted table",
    )
    parser.set_defaults(func=cmd_evaluate)
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
