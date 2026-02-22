#!/usr/bin/env python
"""
Weekly QC digest script.

Aggregates PASS/WARN/FAIL counts across all stats tables with week-over-week
delta comparison. Delivers a human-readable summary via Telegram and stdout.

Run standalone:
    python -m ta_lab2.scripts.stats.weekly_digest
    python -m ta_lab2.scripts.stats.weekly_digest --no-telegram
    python -m ta_lab2.scripts.stats.weekly_digest --dry-run

Or via orchestrator:
    python -m ta_lab2.scripts.run_daily_refresh --weekly-digest
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# Tables queried for weekly digest (label, fully-qualified table name)
DIGEST_TABLES = [
    ("bars", "public.price_bars_multi_tf_stats"),
    ("ema_multi_tf", "public.ema_multi_tf_stats"),
    ("ema_cal", "public.ema_multi_tf_cal_stats"),
    ("ema_cal_anchor", "public.ema_multi_tf_cal_anchor_stats"),
    ("returns_ema", "public.returns_ema_stats"),
    ("features", "public.cmc_features_stats"),
    ("audit", "public.audit_results"),
]

# Telegram 4096-char limit; leave headroom for HTML formatting
TELEGRAM_MAX_CHARS = 4000


def query_period_status(
    engine,
    table: str,
    interval_start: datetime,
    interval_end: datetime,
) -> dict[str, int]:
    """
    Query PASS/WARN/FAIL counts for a stats table within a time window.

    Args:
        engine: SQLAlchemy engine connected to the database
        table: Fully-qualified table name (e.g. "public.price_bars_multi_tf_stats")
        interval_start: Start of the window (inclusive)
        interval_end: End of the window (exclusive)

    Returns:
        dict mapping status -> count, e.g. {"PASS": 100, "FAIL": 3}
        Returns empty dict if table doesn't exist or has no checked_at column.
    """
    try:
        with engine.connect() as conn:
            # Use parametrized timestamps to avoid SQL injection
            query = text(
                f"SELECT status, COUNT(*) AS n "  # noqa: S608
                f"FROM {table} "
                f"WHERE checked_at >= :interval_start AND checked_at < :interval_end "
                f"GROUP BY status"
            )
            rows = conn.execute(
                query,
                {
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                },
            ).fetchall()
            return {row[0]: int(row[1]) for row in rows}
    except Exception as e:
        logger.debug(f"Could not query {table}: {e}")
        return {}


def build_weekly_summary(engine) -> tuple[list[dict], dict[str, int], dict[str, int]]:
    """
    Query this week and last week status for all digest tables.

    Args:
        engine: SQLAlchemy engine

    Returns:
        (table_rows, this_week_totals, last_week_totals)
        table_rows: list of dicts with label, this_week, last_week, status_icon
        this_week_totals: {"PASS": N, "WARN": N, "FAIL": N}
        last_week_totals: {"PASS": N, "WARN": N, "FAIL": N}
    """
    now = datetime.now(timezone.utc)
    # This week: last 7 days
    this_week_end = now
    this_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Go back 7 full days from today's midnight
    from datetime import timedelta

    this_week_start = this_week_start - timedelta(days=7)
    # Last week: 7-14 days ago
    last_week_end = this_week_start
    last_week_start = this_week_start - timedelta(days=7)

    table_rows = []
    this_week_totals: dict[str, int] = {"PASS": 0, "WARN": 0, "FAIL": 0}
    last_week_totals: dict[str, int] = {"PASS": 0, "WARN": 0, "FAIL": 0}

    for label, table in DIGEST_TABLES:
        this_week = query_period_status(engine, table, this_week_start, this_week_end)
        last_week = query_period_status(engine, table, last_week_start, last_week_end)

        n_pass = this_week.get("PASS", 0)
        n_warn = this_week.get("WARN", 0)
        n_fail = this_week.get("FAIL", 0)

        # Accumulate totals
        this_week_totals["PASS"] += n_pass
        this_week_totals["WARN"] += n_warn
        this_week_totals["FAIL"] += n_fail
        last_week_totals["PASS"] += last_week.get("PASS", 0)
        last_week_totals["WARN"] += last_week.get("WARN", 0)
        last_week_totals["FAIL"] += last_week.get("FAIL", 0)

        # Determine table-level status icon
        if n_fail > 0:
            status_icon = "FAIL"
        elif n_warn > 0:
            status_icon = "WARN"
        elif n_pass == 0:
            status_icon = "NO_DATA"
        else:
            status_icon = "PASS"

        table_rows.append(
            {
                "label": label,
                "table": table,
                "n_pass": n_pass,
                "n_warn": n_warn,
                "n_fail": n_fail,
                "status_icon": status_icon,
                "this_week": this_week,
                "last_week": last_week,
            }
        )

    return table_rows, this_week_totals, last_week_totals


def build_weekly_delta(
    this_week_totals: dict[str, int],
    last_week_totals: dict[str, int],
) -> str:
    """
    Build week-over-week delta summary string.

    Compares aggregate FAIL and WARN counts this week vs last week.
    Uses aggregate totals (NOT row-level comparison) because the delete-before-insert
    pattern means old rows for un-impacted keys may not be present last week.

    Args:
        this_week_totals: Aggregate {"PASS": N, "WARN": N, "FAIL": N} this week
        last_week_totals: Aggregate {"PASS": N, "WARN": N, "FAIL": N} last week

    Returns:
        Human-readable delta summary string (2-3 lines)
    """
    lines = []

    # FAIL delta
    fail_this = this_week_totals.get("FAIL", 0)
    fail_last = last_week_totals.get("FAIL", 0)
    fail_delta = fail_this - fail_last

    if fail_delta > 0:
        lines.append(f"Delta: +{fail_delta} new FAILs since last week")
    elif fail_delta < 0:
        lines.append(f"Delta: {fail_delta} fewer FAILs since last week")
    else:
        lines.append("Delta: No change in FAIL count")

    # WARN delta (secondary info)
    warn_this = this_week_totals.get("WARN", 0)
    warn_last = last_week_totals.get("WARN", 0)
    warn_delta = warn_this - warn_last

    if warn_delta > 0:
        lines.append(f"       +{warn_delta} new WARNs since last week")
    elif warn_delta < 0:
        lines.append(f"       {warn_delta} fewer WARNs since last week")

    return "\n".join(lines)


def format_digest(
    table_rows: list[dict],
    this_week_totals: dict[str, int],
    delta_str: str,
    timestamp: str,
    verbose: bool = False,
) -> tuple[str, str | None]:
    """
    Format the digest into one or two Telegram messages.

    Keeps each message under TELEGRAM_MAX_CHARS. If the full digest is too long,
    returns a split: (summary_message, detail_message).

    Args:
        table_rows: Per-table rows from build_weekly_summary()
        this_week_totals: Aggregate totals for overall summary line
        delta_str: Output of build_weekly_delta()
        timestamp: ISO timestamp string for the digest header
        verbose: Include extra per-test detail (not implemented at table level)

    Returns:
        (primary_message, secondary_message_or_None)
        primary_message: Top-level summary + delta (always under limit)
        secondary_message: Per-table breakdown (None if fits in primary)
    """
    total_pass = this_week_totals.get("PASS", 0)
    total_warn = this_week_totals.get("WARN", 0)
    total_fail = this_week_totals.get("FAIL", 0)

    # Overall status icon
    if total_fail > 0:
        overall_icon = "[FAIL]"
    elif total_warn > 0:
        overall_icon = "[WARN]"
    else:
        overall_icon = "[PASS]"

    # Build primary message (header + overall + delta)
    primary_lines = [
        "<b>Weekly QC Digest</b>",
        f"Generated: {timestamp}",
        "",
        f"<b>Overall: {overall_icon}</b>",
        f"  {total_pass} pass / {total_warn} warn / {total_fail} fail",
        "",
        delta_str,
    ]
    primary_msg = "\n".join(primary_lines)

    # Build per-table detail section
    detail_lines = ["<b>Per-table breakdown:</b>"]
    for row in table_rows:
        icon = row["status_icon"]
        label = row["label"]
        n_pass = row["n_pass"]
        n_warn = row["n_warn"]
        n_fail = row["n_fail"]

        if row["status_icon"] == "NO_DATA":
            detail_lines.append(f"  [{icon}] {label}: no data this week")
        else:
            detail_lines.append(
                f"  [{icon}] {label}: {n_pass} pass / {n_warn} warn / {n_fail} fail"
            )

    detail_msg = "\n".join(detail_lines)

    # Try to fit everything in one message
    combined = primary_msg + "\n\n" + detail_msg
    if len(combined) <= TELEGRAM_MAX_CHARS:
        return combined, None

    # Too long -- try truncating to top 5 tables by FAIL count
    top5 = sorted(table_rows, key=lambda r: r["n_fail"], reverse=True)[:5]
    short_detail_lines = [
        "<b>Top tables by FAIL (5 of 7):</b>",
    ]
    for row in top5:
        icon = row["status_icon"]
        label = row["label"]
        n_fail = row["n_fail"]
        short_detail_lines.append(f"  [{icon}] {label}: {n_fail} fail")
    short_detail = "\n".join(short_detail_lines)

    combined_short = primary_msg + "\n\n" + short_detail
    if len(combined_short) <= TELEGRAM_MAX_CHARS:
        return combined_short, None

    # Still too long -- split into two messages
    # Primary: summary + delta, Secondary: full per-table breakdown
    return primary_msg, detail_msg


def send_digest(engine, no_telegram: bool = False, verbose: bool = False) -> int:
    """
    Build and deliver the weekly QC digest.

    Queries DB for this week and last week status across all digest tables,
    builds a human-readable summary with week-over-week delta, prints to stdout,
    and optionally sends via Telegram.

    Args:
        engine: SQLAlchemy engine connected to the database
        no_telegram: Skip Telegram delivery, stdout only
        verbose: Show per-test detail (currently reserved)

    Returns:
        0 on success, 1 on error
    """
    try:
        table_rows, this_week_totals, last_week_totals = build_weekly_summary(engine)
    except Exception as e:
        print(f"[ERROR] Failed to build weekly summary: {e}")
        logger.exception("Failed to build weekly summary")
        return 1

    delta_str = build_weekly_delta(this_week_totals, last_week_totals)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    primary_msg, secondary_msg = format_digest(
        table_rows=table_rows,
        this_week_totals=this_week_totals,
        delta_str=delta_str,
        timestamp=timestamp,
        verbose=verbose,
    )

    # Always print to stdout
    print("\n" + "=" * 70)
    print("WEEKLY QC DIGEST")
    print("=" * 70)
    print(f"\nGenerated: {timestamp}")
    print()

    total_pass = this_week_totals.get("PASS", 0)
    total_warn = this_week_totals.get("WARN", 0)
    total_fail = this_week_totals.get("FAIL", 0)

    if total_fail > 0:
        overall_icon = "[FAIL]"
    elif total_warn > 0:
        overall_icon = "[WARN]"
    else:
        overall_icon = "[PASS]"

    print(
        f"Overall: {overall_icon}  {total_pass} pass / {total_warn} warn / {total_fail} fail"
    )
    print()
    print(delta_str)
    print()
    print("Per-table breakdown:")
    for row in table_rows:
        icon = row["status_icon"]
        label = row["label"]
        n_pass = row["n_pass"]
        n_warn = row["n_warn"]
        n_fail = row["n_fail"]
        if icon == "NO_DATA":
            print(f"  [{icon}] {label}: no data this week")
        else:
            print(f"  [{icon}] {label}: {n_pass} pass / {n_warn} warn / {n_fail} fail")

    print("\n" + "=" * 70)

    # Determine overall severity for Telegram
    if total_fail > 0:
        overall_severity = "critical"
    elif total_warn > 0:
        overall_severity = "warning"
    else:
        overall_severity = "info"

    # Send via Telegram
    if no_telegram:
        print("\n[INFO] Telegram delivery skipped (--no-telegram)")
        return 0

    try:
        from ta_lab2.notifications import telegram

        if not telegram.is_configured():
            logger.debug("Telegram not configured -- skipping weekly digest delivery")
            print("\n[INFO] Telegram not configured -- digest printed to stdout only")
            return 0

        # Send primary message
        success1 = telegram.send_alert(
            title="Weekly QC Digest",
            message=primary_msg,
            severity=overall_severity,
        )

        # Send secondary message if digest was split
        if secondary_msg is not None:
            success2 = telegram.send_message(secondary_msg)
            if not success2:
                logger.warning("Failed to send secondary digest message via Telegram")
        else:
            success2 = True

        if success1:
            print("\n[OK] Weekly digest sent via Telegram")
        else:
            print("\n[WARNING] Failed to send digest via Telegram")

    except ImportError:
        logger.debug("Telegram module not available -- skipping digest delivery")
        print("\n[INFO] Telegram not available -- digest printed to stdout only")
    except Exception as e:
        logger.warning(f"Failed to send weekly digest via Telegram: {e}")
        print(f"\n[WARNING] Telegram delivery failed: {e}")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    p = argparse.ArgumentParser(
        description="Weekly QC digest: PASS/WARN/FAIL summary across all stats tables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run weekly digest (prints to stdout + Telegram if configured)
  python -m ta_lab2.scripts.stats.weekly_digest

  # Dry run (list tables that would be queried, no DB connection)
  python -m ta_lab2.scripts.stats.weekly_digest --dry-run

  # Skip Telegram delivery (stdout only)
  python -m ta_lab2.scripts.stats.weekly_digest --no-telegram

  # Via orchestrator
  python -m ta_lab2.scripts.run_daily_refresh --weekly-digest
        """,
    )

    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Skip DB queries and Telegram delivery; "
            "print list of tables that would be queried and exit 0"
        ),
    )
    p.add_argument(
        "--no-telegram",
        action="store_true",
        help="Skip Telegram delivery, print digest to stdout only",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-test detail (currently reserved for future use)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Dry-run: print table list and exit without DB connection
    if args.dry_run:
        print("[DRY RUN] Weekly QC digest would query the following tables:")
        for label, table in DIGEST_TABLES:
            print(f"  - {label}: {table}")
        print(
            "\n[DRY RUN] Week windows:"
            "\n  This week:  last 7 days"
            "\n  Last week:  7-14 days ago"
        )
        print("\n[DRY RUN] Telegram delivery would be attempted if configured.")
        return 0

    # Resolve database URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    # Create engine and run digest
    try:
        engine = create_engine(db_url)
        return send_digest(engine, no_telegram=args.no_telegram, verbose=args.verbose)
    except Exception as e:
        print(f"[ERROR] Failed to connect to database: {e}")
        logger.exception("Database connection failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
