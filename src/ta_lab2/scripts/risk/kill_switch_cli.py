"""
Kill switch CLI for paper trading risk control.

Provides 3 subcommands to control and inspect the trading kill switch:

  activate  -- Halt all trading (requires --reason)
  disable   -- Re-enable trading (requires --reason and --operator)
  status    -- Print current kill switch state

Usage examples::

    python -m ta_lab2.scripts.risk.kill_switch_cli status

    python -m ta_lab2.scripts.risk.kill_switch_cli activate \\
        --reason "Unusual market volatility detected"

    python -m ta_lab2.scripts.risk.kill_switch_cli disable \\
        --reason "Volatility normalised -- resuming paper trading" \\
        --operator "asafi"

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

from ta_lab2.risk.kill_switch import (
    activate_kill_switch,
    print_kill_switch_status,
    re_enable_trading,
)
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_activate(args: argparse.Namespace) -> int:
    """Handle 'activate' subcommand -- halt all trading."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)

    activate_kill_switch(
        engine=engine,
        reason=args.reason,
        trigger_source="manual",
        operator=getattr(args, "operator", None),
    )
    print(f"Kill switch ACTIVATED: {args.reason}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    """Handle 'disable' subcommand -- re-enable trading."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)

    try:
        re_enable_trading(
            engine=engine,
            reason=args.reason,
            operator=args.operator,
        )
        print(f"Trading RE-ENABLED by {args.operator}: {args.reason}")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Handle 'status' subcommand -- print current state."""
    db_url = resolve_db_url(getattr(args, "db_url", None))
    engine = create_engine(db_url, poolclass=NullPool)

    print_kill_switch_status(engine)
    return 0


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="kill_switch_cli",
        description="Paper trading kill switch control. Halt, re-enable, or inspect trading state.",
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

    # -- activate --
    activate_parser = subparsers.add_parser(
        "activate",
        help="Halt all paper trading immediately",
    )
    activate_parser.add_argument(
        "--reason",
        required=True,
        metavar="TEXT",
        help="Human-readable reason for the halt (required)",
    )
    activate_parser.add_argument(
        "--operator",
        metavar="NAME",
        help="Operator identity (optional; defaults to 'manual')",
    )
    activate_parser.set_defaults(func=cmd_activate)

    # -- disable --
    disable_parser = subparsers.add_parser(
        "disable",
        help="Re-enable paper trading (requires reason and operator)",
    )
    disable_parser.add_argument(
        "--reason",
        required=True,
        metavar="TEXT",
        help="Human-readable reason for re-enabling (required)",
    )
    disable_parser.add_argument(
        "--operator",
        required=True,
        metavar="NAME",
        help="Operator authorising the re-enable (required)",
    )
    disable_parser.set_defaults(func=cmd_disable)

    # -- status --
    status_parser = subparsers.add_parser(
        "status",
        help="Print current kill switch state",
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
