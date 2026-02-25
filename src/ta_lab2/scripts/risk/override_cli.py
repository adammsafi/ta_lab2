"""Discretionary position override management CLI.

Provides 3 subcommands for managing position overrides:

  create  -- Create a new override (sticky or non-sticky)
  revert  -- Revert an active override
  list    -- List active (non-reverted) overrides

Usage examples::

    python -m ta_lab2.scripts.risk.override_cli create \\
        --asset-id 1 --strategy-id 2 --action flat \\
        --reason "Weekend liquidity concern" --operator asafi

    python -m ta_lab2.scripts.risk.override_cli create \\
        --asset-id 1 --strategy-id 2 --action flat \\
        --reason "Manual risk reduction" --operator asafi --sticky

    python -m ta_lab2.scripts.risk.override_cli revert \\
        --override-id <uuid> --reason "Concern resolved" --operator asafi

    python -m ta_lab2.scripts.risk.override_cli list
    python -m ta_lab2.scripts.risk.override_cli list --asset-id 1

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

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.risk.override_manager import OverrideInfo, OverrideManager
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    """Handle 'create' subcommand -- create a new override."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)
    mgr = OverrideManager(engine)

    override_id = mgr.create_override(
        asset_id=args.asset_id,
        strategy_id=args.strategy_id,
        operator=args.operator,
        reason=args.reason,
        system_signal=args.system_signal,
        override_action=args.action,
        sticky=args.sticky,
    )

    sticky_label = "STICKY" if args.sticky else "non-sticky"
    print(f"Override created ({sticky_label}): {override_id}")
    print(f"  Asset:    {args.asset_id}")
    print(f"  Strategy: {args.strategy_id}")
    print(f"  Action:   {args.action}")
    print(f"  Reason:   {args.reason}")
    print(f"  Operator: {args.operator}")
    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    """Handle 'revert' subcommand -- revert an active override."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)
    mgr = OverrideManager(engine)

    mgr.revert_override(
        override_id=args.override_id,
        reason=args.reason,
        operator=args.operator,
    )
    print(f"Override reverted: {args.override_id}")
    print(f"  Reason:   {args.reason}")
    print(f"  Operator: {args.operator}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Handle 'list' subcommand -- list active overrides."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)
    mgr = OverrideManager(engine)

    asset_id = getattr(args, "asset_id", None)
    strategy_id = getattr(args, "strategy_id", None)
    overrides = mgr.get_active_overrides(asset_id=asset_id, strategy_id=strategy_id)

    if not overrides:
        print("No active overrides.")
        return 0

    _print_overrides_table(overrides)
    return 0


def _print_overrides_table(overrides: list[OverrideInfo]) -> None:
    """Print overrides in a human-readable table format."""
    header = f"{'ID':<36}  {'Asset':>5}  {'Strategy':>8}  {'Action':<12}  {'Sticky':>6}  {'Operator':<10}  Created"
    print("Active Overrides")
    print("-" * (len(header) + 4))
    print(header)
    print("-" * (len(header) + 4))
    for o in overrides:
        sticky_str = "YES" if o.sticky else "NO"
        created_str = o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else ""
        print(
            f"{o.override_id:<36}  {o.asset_id:>5}  {o.strategy_id:>8}  "
            f"{o.override_action:<12}  {sticky_str:>6}  {o.operator:<10}  {created_str}"
        )
    print("-" * (len(header) + 4))
    print(f"Total: {len(overrides)} active override(s)")


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="override_cli",
        description="Discretionary position override management. Create, revert, or list overrides.",
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
        help="Create a new position override",
    )
    create_parser.add_argument(
        "--asset-id",
        required=True,
        type=int,
        metavar="ID",
        help="Asset ID (integer)",
    )
    create_parser.add_argument(
        "--strategy-id",
        required=True,
        type=int,
        metavar="ID",
        help="Strategy ID (integer)",
    )
    create_parser.add_argument(
        "--action",
        required=True,
        metavar="ACTION",
        help='Override action, e.g. "flat", "long_10_pct", "short_5_pct"',
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
        "--system-signal",
        default="unknown",
        metavar="SIGNAL",
        help='System signal at override time (default: "unknown"; executor fills this programmatically)',
    )
    create_parser.add_argument(
        "--sticky",
        action="store_true",
        default=False,
        help="If set, override persists until explicitly reverted. Otherwise snaps back after one signal cycle.",
    )
    create_parser.set_defaults(func=cmd_create)

    # -- revert --
    revert_parser = subparsers.add_parser(
        "revert",
        help="Revert an active override",
    )
    revert_parser.add_argument(
        "--override-id",
        required=True,
        metavar="UUID",
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

    # -- list --
    list_parser = subparsers.add_parser(
        "list",
        help="List active (non-reverted) overrides",
    )
    list_parser.add_argument(
        "--asset-id",
        type=int,
        metavar="ID",
        help="Filter to a specific asset ID (optional)",
    )
    list_parser.add_argument(
        "--strategy-id",
        type=int,
        metavar="ID",
        help="Filter to a specific strategy ID (optional)",
    )
    list_parser.set_defaults(func=cmd_list)

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
