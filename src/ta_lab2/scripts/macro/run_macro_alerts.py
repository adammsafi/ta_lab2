"""run_macro_alerts.py

CLI script for macro regime transition alerting.

Detects dimension-level and composite regime-key changes in macro_regimes and
dispatches throttled Telegram alerts via MacroAlertManager. Logs all alert activity
(including throttled alerts) to macro_alert_log for audit and dashboard visibility.

Follows the same patterns as refresh_macro_regimes.py:
- argparse CLI with --profile, --dry-run, --verbose
- Engine from db_config.env / TARGET_DB_URL
- Structured print output with elapsed time

Usage:
    python -m ta_lab2.scripts.macro.run_macro_alerts              # live alert check
    python -m ta_lab2.scripts.macro.run_macro_alerts --dry-run    # detect only, no sends
    python -m ta_lab2.scripts.macro.run_macro_alerts --verbose    # DEBUG logging
    python -m ta_lab2.scripts.macro.run_macro_alerts --profile conservative
    python -m ta_lab2.scripts.macro.run_macro_alerts --cooldown 12
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from ta_lab2.io import get_engine
from ta_lab2.notifications.macro_alerts import (
    MacroAlertManager,
    check_and_alert_transitions,
)

logger = logging.getLogger(__name__)

# Default throttle window (hours) -- matches MacroAlertManager default
DEFAULT_COOLDOWN_HOURS = 6


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for macro regime alert checking."""
    p = argparse.ArgumentParser(
        description=(
            "Detect macro regime transitions in macro_regimes and dispatch "
            "throttled Telegram alerts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Live check: detect transitions and send Telegram alerts
  python -m ta_lab2.scripts.macro.run_macro_alerts

  # Dry run: detect transitions but do NOT send Telegram alerts
  python -m ta_lab2.scripts.macro.run_macro_alerts --dry-run

  # Use conservative profile
  python -m ta_lab2.scripts.macro.run_macro_alerts --profile conservative

  # Custom cooldown window (hours)
  python -m ta_lab2.scripts.macro.run_macro_alerts --cooldown 12

  # Verbose / debug logging
  python -m ta_lab2.scripts.macro.run_macro_alerts --verbose
        """,
    )
    p.add_argument(
        "--profile",
        metavar="PROFILE",
        default="default",
        help="Macro regime profile to check (default: default).",
    )
    p.add_argument(
        "--cooldown",
        metavar="HOURS",
        type=int,
        default=DEFAULT_COOLDOWN_HOURS,
        help=f"Throttle window in hours (default: {DEFAULT_COOLDOWN_HOURS}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run transition detection but skip Telegram sends. "
            "Prints what would be alerted. Still queries the database."
        ),
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    args = p.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    t0 = time.perf_counter()

    print(f"\n{'=' * 70}")
    print("MACRO REGIME ALERT CHECK")
    print(f"{'=' * 70}")
    if args.dry_run:
        print(
            "[DRY RUN] Transitions will be detected but Telegram alerts will NOT be sent"
        )
    print(f"[INFO] Profile: {args.profile}")
    print(f"[INFO] Cooldown: {args.cooldown} hours")

    # Connect to DB
    try:
        engine = get_engine()
    except Exception as exc:
        print(f"[ERROR] Could not create DB engine: {exc}")
        return 1

    if args.dry_run:
        # Dry-run: run detection, print results, but suppress Telegram sends
        # by using MacroAlertManager with Telegram check bypassed via monkeypatching
        import ta_lab2.notifications.telegram as _tg

        _orig_is_configured = _tg.is_configured

        def _dry_run_is_configured() -> bool:
            return False

        _tg.is_configured = _dry_run_is_configured  # type: ignore[assignment]
        try:
            manager = MacroAlertManager(engine, cooldown_hours=args.cooldown)
            transitions = manager.check_and_alert(profile=args.profile)
        finally:
            _tg.is_configured = _orig_is_configured  # type: ignore[assignment]

        elapsed = time.perf_counter() - t0
        n_total = len(transitions)

        if n_total == 0:
            print("\n[INFO] No macro regime transitions detected -- system is stable")
        else:
            print(f"\n[DRY RUN] Would send alerts for {n_total} transition(s):")
            for i, t in enumerate(transitions, 1):
                ttype = t.get("type", "?")
                dim = t.get("dimension") or "composite"
                old_label = t.get("old_label", "?")
                new_label = t.get("new_label", "?")
                throttled_flag = "[THROTTLED]" if t.get("throttled") else ""
                print(
                    f"  {i}. [{ttype}] {dim}: {old_label} -> {new_label} {throttled_flag}"
                )

        print(
            f"\n[DRY RUN DONE] Elapsed: {elapsed:.1f}s ({n_total} transition(s) found, 0 alerts sent)"
        )
        return 0

    # Live path: detect transitions and send Telegram alerts
    try:
        transitions = check_and_alert_transitions(engine, args.profile, args.cooldown)
    except Exception as exc:
        print(f"[ERROR] Alert check failed: {exc}")
        logger.exception("check_and_alert_transitions() raised an exception")
        return 1

    elapsed = time.perf_counter() - t0
    n_total = len(transitions)
    n_sent = sum(1 for t in transitions if t.get("sent"))
    n_throttled = sum(1 for t in transitions if t.get("throttled"))

    if n_total == 0:
        print("\n[INFO] No macro regime transitions detected -- system is stable")
        print(f"\n[DONE] Elapsed: {elapsed:.1f}s (0 transitions, 0 alerts sent)")
    else:
        print(f"\n[OK] Alert check complete in {elapsed:.1f}s:")
        print(f"  Transitions found: {n_total}")
        print(f"  Alerts sent:       {n_sent}")
        print(f"  Throttled:         {n_throttled}")
        for i, t in enumerate(transitions, 1):
            ttype = t.get("type", "?")
            dim = t.get("dimension") or "composite"
            old_label = t.get("old_label", "?")
            new_label = t.get("new_label", "?")
            status = (
                "THROTTLED"
                if t.get("throttled")
                else ("SENT" if t.get("sent") else "NO-TELEGRAM")
            )
            print(f"  {i}. [{ttype}] {dim}: {old_label} -> {new_label} [{status}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
