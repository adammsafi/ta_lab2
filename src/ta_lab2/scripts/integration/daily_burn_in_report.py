#!/usr/bin/env python
"""
Daily burn-in status report script.

Queries paper trading health metrics and delivers a formatted status report
via stdout and optionally via Telegram. Designed to be run once per day
during the 7-day burn-in period to provide visibility into pipeline health,
fill counts, risk state, drift metrics, and cumulative PnL.

Run standalone:
    python -m ta_lab2.scripts.integration.daily_burn_in_report --burn-in-start 2026-03-24
    python -m ta_lab2.scripts.integration.daily_burn_in_report --burn-in-start 2026-03-24 --no-telegram
    python -m ta_lab2.scripts.integration.daily_burn_in_report --burn-in-start 2026-03-24 --dry-run

Exit codes:
    0: Success (report produced; individual query failures are WARN not errors)
    1: Fatal error (DB connection failure)
"""

from __future__ import annotations

# ASCII-only file -- no UTF-8 box-drawing characters (Windows cp1252 safety)

import argparse
import logging
import sys
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# Telegram character limit with headroom for HTML formatting
TELEGRAM_MAX_CHARS = 4000

# Burn-in duration (days)
BURN_IN_DAYS = 7

# Tracking error threshold for WARNING verdict (percent)
TRACKING_ERROR_WARNING_THRESHOLD = 5.0


# ---------------------------------------------------------------------------
# Individual metric queries (each returns a dict of collected values)
# ---------------------------------------------------------------------------


def _query_pipeline_status(conn, today: date) -> dict:
    """Query today's pipeline run from pipeline_run_log."""
    try:
        row = conn.execute(
            text(
                """
                SELECT status, started_at, completed_at, stages_completed,
                       total_duration_sec
                FROM pipeline_run_log
                WHERE DATE(started_at) = :today
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"today": today},
        ).fetchone()

        if row is None:
            return {"status": "NO_RUN", "stages": 0, "duration_sec": None}

        status = row[0] or "unknown"
        stages_completed = row[3]
        duration_sec = row[4]

        # stages_completed is JSONB -- psycopg2 deserialises to Python list/dict
        if isinstance(stages_completed, list):
            stage_count = len(stages_completed)
        elif stages_completed is None:
            stage_count = 0
        else:
            # Unexpected type: coerce to 0
            stage_count = 0

        return {
            "status": status,
            "stages": stage_count,
            "duration_sec": duration_sec,
        }

    except Exception as exc:
        logger.warning("pipeline_run_log query failed: %s", exc)
        return {
            "status": "UNAVAILABLE",
            "stages": 0,
            "duration_sec": None,
            "error": str(exc),
        }


def _query_order_count(conn, burn_in_start: date, today: date) -> dict:
    """Query today's order count from orders table."""
    try:
        row = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM orders
                WHERE created_at >= :burn_in_start
                  AND DATE(created_at) = :today
                """
            ),
            {"burn_in_start": burn_in_start, "today": today},
        ).fetchone()
        return {"orders_today": int(row[0]) if row else 0}
    except Exception as exc:
        logger.warning("orders query failed: %s", exc)
        return {"orders_today": "UNAVAILABLE", "error": str(exc)}


def _query_fill_counts(conn, burn_in_start: date, today: date) -> dict:
    """Query today's fill count and cumulative fills since burn-in start."""
    result = {"fills_today": "UNAVAILABLE", "fills_total": "UNAVAILABLE"}
    try:
        row_today = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM fills
                WHERE filled_at >= :burn_in_start
                  AND DATE(filled_at) = :today
                """
            ),
            {"burn_in_start": burn_in_start, "today": today},
        ).fetchone()
        result["fills_today"] = int(row_today[0]) if row_today else 0
    except Exception as exc:
        logger.warning("fills today query failed: %s", exc)
        result["fills_today"] = "UNAVAILABLE"
        result["error_today"] = str(exc)

    try:
        row_total = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM fills
                WHERE filled_at >= :burn_in_start
                """
            ),
            {"burn_in_start": burn_in_start},
        ).fetchone()
        result["fills_total"] = int(row_total[0]) if row_total else 0
    except Exception as exc:
        logger.warning("fills total query failed: %s", exc)
        result["fills_total"] = "UNAVAILABLE"
        result["error_total"] = str(exc)

    return result


def _query_risk_state(conn) -> dict:
    """Query trading state and drift pause from dim_risk_state."""
    try:
        row = conn.execute(
            text(
                """
                SELECT trading_state, drift_paused
                FROM dim_risk_state
                WHERE state_id = 1
                """
            )
        ).fetchone()
        if row is None:
            return {"trading_state": "UNKNOWN", "drift_paused": False}
        return {
            "trading_state": (row[0] or "unknown").upper(),
            "drift_paused": bool(row[1]),
        }
    except Exception as exc:
        logger.warning("dim_risk_state query failed: %s", exc)
        return {
            "trading_state": "UNAVAILABLE",
            "drift_paused": False,
            "error": str(exc),
        }


def _query_drift_metrics(conn) -> dict:
    """Query latest tracking error from drift_metrics."""
    try:
        row = conn.execute(
            text(
                """
                SELECT tracking_error_5d, tracking_error_30d, metric_date
                FROM drift_metrics
                ORDER BY metric_date DESC
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return {"te_5d": None, "te_30d": None, "metric_date": None}
        return {
            "te_5d": float(row[0]) if row[0] is not None else None,
            "te_30d": float(row[1]) if row[1] is not None else None,
            "metric_date": row[2],
        }
    except Exception as exc:
        logger.warning("drift_metrics query failed: %s", exc)
        return {"te_5d": None, "te_30d": None, "metric_date": None, "error": str(exc)}


def _query_cumulative_pnl(conn, burn_in_start: date) -> dict:
    """
    Query cumulative paper PnL since burn-in start from positions table.

    Falls back to assets_traded count from orders if realized_pnl is unavailable.
    """
    # Try positions.realized_pnl first
    try:
        row = conn.execute(
            text(
                """
                SELECT COALESCE(SUM(realized_pnl), 0)
                FROM positions
                WHERE updated_at >= :burn_in_start
                """
            ),
            {"burn_in_start": burn_in_start},
        ).fetchone()
        return {"total_pnl": float(row[0]) if row else 0.0, "pnl_source": "positions"}
    except Exception as exc_positions:
        logger.debug("positions.realized_pnl not available: %s", exc_positions)

    # Fallback: count distinct assets from orders
    try:
        row = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT asset_id)
                FROM orders
                WHERE created_at >= :burn_in_start
                """
            ),
            {"burn_in_start": burn_in_start},
        ).fetchone()
        return {
            "total_pnl": None,
            "assets_traded": int(row[0]) if row else 0,
            "pnl_source": "orders_fallback",
        }
    except Exception as exc_orders:
        logger.warning("PnL fallback query also failed: %s", exc_orders)
        return {
            "total_pnl": None,
            "assets_traded": "UNAVAILABLE",
            "pnl_source": "unavailable",
            "error": str(exc_orders),
        }


def _query_signal_anomalies(conn, burn_in_start: date) -> dict:
    """Query signal anomaly gate counts from signal_anomaly_log."""
    try:
        row = conn.execute(
            text(
                """
                SELECT COUNT(*) AS anomaly_count,
                       SUM(CASE WHEN blocked THEN 1 ELSE 0 END) AS flagged
                FROM signal_anomaly_log
                WHERE checked_at >= :burn_in_start
                """
            ),
            {"burn_in_start": burn_in_start},
        ).fetchone()
        if row is None:
            return {"anomaly_count": 0, "flagged": 0}
        return {
            "anomaly_count": int(row[0]) if row[0] is not None else 0,
            "flagged": int(row[1]) if row[1] is not None else 0,
        }
    except Exception as exc:
        logger.warning("signal_anomaly_log query failed: %s", exc)
        return {
            "anomaly_count": "UNAVAILABLE",
            "flagged": "UNAVAILABLE",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _compute_day_number(burn_in_start: date, today: date) -> int:
    """Compute the burn-in day number (Day 1 = burn_in_start)."""
    delta = (today - burn_in_start).days
    return max(1, delta + 1)


def _determine_verdict(
    risk: dict,
    drift: dict,
) -> tuple[str, str]:
    """
    Determine burn-in verdict and Telegram severity.

    Returns:
        (verdict_label, severity_str) where severity is "info"/"warning"/"critical"
    """
    trading_state = risk.get("trading_state", "UNKNOWN")
    drift_paused = risk.get("drift_paused", False)

    # STOP conditions: kill switch (halted) OR drift paused
    if trading_state == "HALTED" or drift_paused:
        return "STOP", "critical"

    # WARNING: high tracking error
    te_5d = drift.get("te_5d")
    te_30d = drift.get("te_30d")
    if te_5d is not None and te_5d > TRACKING_ERROR_WARNING_THRESHOLD:
        return "WARNING", "warning"
    if te_30d is not None and te_30d > TRACKING_ERROR_WARNING_THRESHOLD:
        return "WARNING", "warning"

    return "ON TRACK", "info"


def build_report(
    burn_in_start: date,
    today: date,
    pipeline: dict,
    orders: dict,
    fills: dict,
    risk: dict,
    drift: dict,
    pnl: dict,
    anomalies: dict,
) -> tuple[str, str, str]:
    """
    Build the ASCII-only report text.

    Returns:
        (stdout_text, telegram_html, verdict_label)
    """
    day_num = _compute_day_number(burn_in_start, today)
    verdict, severity = _determine_verdict(risk, drift)

    # --- PIPELINE section ---
    pipe_status = pipeline.get("status", "UNKNOWN")
    pipe_stages = pipeline.get("stages", 0)
    pipe_dur = pipeline.get("duration_sec")
    if pipe_dur is not None:
        pipe_detail = f"{pipe_status} ({pipe_stages} stages, {int(pipe_dur)}s)"
    else:
        pipe_detail = f"{pipe_status} ({pipe_stages} stages)"
    if "error" in pipeline:
        pipe_detail = f"UNAVAILABLE ({pipeline['error']})"

    # --- TRADING section ---
    orders_today = orders.get("orders_today", "UNAVAILABLE")
    fills_today = fills.get("fills_today", "UNAVAILABLE")
    fills_total = fills.get("fills_total", "UNAVAILABLE")

    pnl_source = pnl.get("pnl_source", "unavailable")
    if pnl_source == "positions":
        total_pnl = pnl.get("total_pnl")
        if total_pnl is not None:
            pnl_line = f"Cumulative PnL: {total_pnl:+.2f} USD"
        else:
            pnl_line = "Cumulative PnL: 0.00 USD"
        assets_line = ""
    elif pnl_source == "orders_fallback":
        assets_traded = pnl.get("assets_traded", "UNAVAILABLE")
        pnl_line = "Cumulative PnL: UNAVAILABLE (positions table missing realized_pnl)"
        assets_line = f"  Assets traded: {assets_traded}"
    else:
        pnl_line = "Cumulative PnL: UNAVAILABLE"
        assets_line = ""

    # --- RISK section ---
    trading_state = risk.get("trading_state", "UNKNOWN")
    drift_paused = risk.get("drift_paused", False)
    kill_switch = trading_state == "HALTED"
    drift_err = risk.get("error")

    te_5d = drift.get("te_5d")
    te_30d = drift.get("te_30d")
    metric_date = drift.get("metric_date")
    drift_err2 = drift.get("error")

    te_5d_str = f"{te_5d:.2f}%" if te_5d is not None else "N/A"
    te_30d_str = f"{te_30d:.2f}%" if te_30d is not None else "N/A"
    metric_date_str = str(metric_date) if metric_date else "N/A"

    # --- SIGNAL QUALITY section ---
    anomaly_count = anomalies.get("anomaly_count", "UNAVAILABLE")
    flagged = anomalies.get("flagged", "UNAVAILABLE")
    anomaly_err = anomalies.get("error")

    # Build stdout report (plain ASCII)
    sep = "=" * 60
    lines = [
        sep,
        f"DAILY BURN-IN STATUS (Day {day_num}/{BURN_IN_DAYS})",
        sep,
        f"Date:           {today}",
        f"Burn-in start:  {burn_in_start}",
        "",
        "PIPELINE",
        f"  Status: {pipe_detail}",
        "",
        "TRADING",
        f"  Orders today:    {orders_today}",
        f"  Fills today:     {fills_today}",
        f"  Cumulative fills: {fills_total}",
    ]
    if pnl_line:
        lines.append(f"  {pnl_line}")
    if assets_line:
        lines.append(assets_line)
    lines += [
        "",
        "RISK",
    ]
    if drift_err:
        lines.append(f"  Trading state:  UNAVAILABLE ({drift_err})")
    else:
        lines.append(f"  Trading state:  {trading_state}")
        lines.append(f"  Drift paused:   {'Yes' if drift_paused else 'No'}")
        lines.append(f"  Kill switch:    {'YES' if kill_switch else 'No'}")

    if drift_err2:
        lines.append(f"  Tracking error: UNAVAILABLE ({drift_err2})")
    else:
        lines.append(f"  Tracking error (5d):  {te_5d_str}")
        lines.append(f"  Tracking error (30d): {te_30d_str}")
        lines.append(f"  Drift as of:    {metric_date_str}")

    lines += [
        "",
        "SIGNAL QUALITY",
    ]
    if anomaly_err:
        lines.append(f"  Anomaly checks: UNAVAILABLE ({anomaly_err})")
    else:
        lines.append(f"  Anomaly checks: {anomaly_count}, Blocked: {flagged}")

    lines += [
        "",
        f"BURN-IN VERDICT: {verdict}",
        sep,
    ]

    stdout_text = "\n".join(lines)

    # Build Telegram HTML (still ASCII-only characters, just HTML tags for formatting)
    html_lines = [
        f"<b>Daily Burn-In Status (Day {day_num}/{BURN_IN_DAYS})</b>",
        f"Date: {today} | Burn-in start: {burn_in_start}",
        "",
        "<b>PIPELINE</b>",
        f"  Status: {pipe_detail}",
        "",
        "<b>TRADING</b>",
        f"  Orders today: {orders_today}",
        f"  Fills today: {fills_today}",
        f"  Cumulative fills: {fills_total}",
    ]
    if pnl_line:
        html_lines.append(f"  {pnl_line}")
    if assets_line:
        html_lines.append(assets_line)
    html_lines += [
        "",
        "<b>RISK</b>",
        f"  Trading state: {trading_state}",
        f"  Drift paused: {'Yes' if drift_paused else 'No'}",
        f"  Kill switch: {'YES' if kill_switch else 'No'}",
        f"  Tracking error (5d): {te_5d_str}",
        f"  Tracking error (30d): {te_30d_str}",
        "",
        "<b>SIGNAL QUALITY</b>",
        f"  Anomaly checks: {anomaly_count}, Blocked: {flagged}",
        "",
        f"<b>VERDICT: {verdict}</b>",
    ]
    telegram_html = "\n".join(html_lines)

    # Truncate if over limit
    if len(telegram_html) > TELEGRAM_MAX_CHARS:
        telegram_html = telegram_html[: TELEGRAM_MAX_CHARS - 20] + "\n...[truncated]"

    return stdout_text, telegram_html, verdict


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------


def collect_metrics(engine, burn_in_start: date, today: date) -> dict:
    """Run all metric queries and return collected results dict."""
    with engine.connect() as conn:
        pipeline = _query_pipeline_status(conn, today)
        orders = _query_order_count(conn, burn_in_start, today)
        fills = _query_fill_counts(conn, burn_in_start, today)
        risk = _query_risk_state(conn)
        drift = _query_drift_metrics(conn)
        pnl = _query_cumulative_pnl(conn, burn_in_start)
        anomalies = _query_signal_anomalies(conn, burn_in_start)

    return {
        "pipeline": pipeline,
        "orders": orders,
        "fills": fills,
        "risk": risk,
        "drift": drift,
        "pnl": pnl,
        "anomalies": anomalies,
    }


def run_report(
    engine,
    burn_in_start: date,
    no_telegram: bool = False,
    dry_run: bool = False,
) -> int:
    """
    Collect metrics, print report to stdout, and optionally send via Telegram.

    Args:
        engine: SQLAlchemy engine
        burn_in_start: Start date of the burn-in period
        no_telegram: Skip Telegram delivery if True
        dry_run: Alias for no_telegram (print only, no send)

    Returns:
        0 on success, 1 on fatal error
    """
    today = datetime.now(timezone.utc).date()

    try:
        metrics = collect_metrics(engine, burn_in_start, today)
    except Exception as exc:
        print(f"[ERROR] Failed to collect metrics: {exc}", file=sys.stderr)
        logger.exception("Metric collection failed")
        return 1

    stdout_text, telegram_html, verdict = build_report(
        burn_in_start=burn_in_start,
        today=today,
        pipeline=metrics["pipeline"],
        orders=metrics["orders"],
        fills=metrics["fills"],
        risk=metrics["risk"],
        drift=metrics["drift"],
        pnl=metrics["pnl"],
        anomalies=metrics["anomalies"],
    )

    # Always print to stdout
    print(stdout_text)

    # Determine Telegram severity
    severity_map = {
        "ON TRACK": "info",
        "WARNING": "warning",
        "STOP": "critical",
    }
    severity = severity_map.get(verdict, "warning")

    # Skip Telegram if requested
    if no_telegram or dry_run:
        if dry_run:
            print("\n[DRY RUN] Telegram delivery skipped.")
        else:
            print("\n[INFO] Telegram delivery skipped (--no-telegram).")
        return 0

    # Attempt Telegram delivery
    try:
        from ta_lab2.notifications import telegram

        if not telegram.is_configured():
            logger.debug("Telegram not configured -- skipping burn-in report delivery")
            print("\n[INFO] Telegram not configured -- report printed to stdout only.")
            return 0

        day_num = _compute_day_number(burn_in_start, today)
        success = telegram.send_alert(
            title=f"Burn-In Day {day_num}/{BURN_IN_DAYS}: {verdict}",
            message=telegram_html,
            severity=severity,
        )

        if success:
            print("\n[OK] Burn-in report sent via Telegram.")
        else:
            print("\n[WARNING] Failed to send burn-in report via Telegram.")

    except ImportError:
        logger.debug("Telegram module not available -- skipping delivery")
        print("\n[INFO] Telegram not available -- report printed to stdout only.")
    except Exception as exc:
        logger.warning("Failed to send burn-in report via Telegram: %s", exc)
        print(f"\n[WARNING] Telegram delivery failed: {exc}")

    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Main entry point for daily burn-in report."""
    p = argparse.ArgumentParser(
        description=(
            "Daily burn-in status report: queries paper trading health metrics "
            "and delivers a formatted report via stdout and Telegram."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run daily burn-in report (stdout + Telegram if configured)
  python -m ta_lab2.scripts.integration.daily_burn_in_report --burn-in-start 2026-03-24

  # Stdout only (no Telegram)
  python -m ta_lab2.scripts.integration.daily_burn_in_report --burn-in-start 2026-03-24 --no-telegram

  # Dry run (print report, skip Telegram)
  python -m ta_lab2.scripts.integration.daily_burn_in_report --burn-in-start 2026-03-24 --dry-run
        """,
    )

    p.add_argument(
        "--burn-in-start",
        required=True,
        metavar="DATE",
        help="Burn-in start date in YYYY-MM-DD format (required)",
    )
    p.add_argument(
        "--db-url",
        help="Database URL override (default: from db_config.env or TARGET_DB_URL env var)",
    )
    p.add_argument(
        "--no-telegram",
        action="store_true",
        help="Skip Telegram delivery; print report to stdout only",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report but do not send Telegram (alias for --no-telegram)",
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

    # Parse burn-in start date
    try:
        burn_in_start = date.fromisoformat(args.burn_in_start)
    except ValueError:
        print(
            f"[ERROR] Invalid --burn-in-start date: {args.burn_in_start!r}. "
            "Expected YYYY-MM-DD format.",
            file=sys.stderr,
        )
        return 1

    # Resolve database URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Create NullPool engine (project convention for CLI scripts)
    try:
        engine = create_engine(db_url, poolclass=NullPool)
    except Exception as exc:
        print(f"[ERROR] Failed to create database engine: {exc}", file=sys.stderr)
        logger.exception("Engine creation failed")
        return 1

    return run_report(
        engine=engine,
        burn_in_start=burn_in_start,
        no_telegram=args.no_telegram,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
