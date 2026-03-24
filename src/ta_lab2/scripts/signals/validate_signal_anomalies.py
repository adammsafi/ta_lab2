# src/ta_lab2/scripts/signals/validate_signal_anomalies.py
"""
Signal Anomaly Gate: detect anomalous signal patterns and block them from the executor.

Checks two anomaly types before allowing signals to proceed to the executor:

  1. Count anomaly -- today's signal count deviates >2 sigma from the 90-day
     rolling baseline (excluding today's partial-day data).

  2. Crowded signal -- >40% of all open signals agree on the same (asset_id,
     direction), which may indicate a regime shift or data issue.

Anomalous signals are BLOCKED from the executor (return code 2, not a soft
warning). Every gate decision is logged to signal_anomaly_log. Throttled
CRITICAL Telegram alerts fire via pipeline_alert_log with a 4-hour cooldown.

Design notes:
- Baseline query uses DATE(ts) < CURRENT_DATE to exclude today's partial day.
- Crowded check filters position_state = 'open' to exclude closed signals.
- Returns 0 (clean), 1 (script error), or 2 (anomalies detected).
- DB inserts are wrapped in try/except (OperationalError, ProgrammingError) --
  tables may not exist if the Phase 87 Alembic migration has not run yet.
- Does NOT trip the kill switch (dim_risk_state). Pre-execution gate only.

Phase 87, Plan 02.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError

from ta_lab2.notifications import telegram

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal table names checked by the gate
# ---------------------------------------------------------------------------

_SIGNAL_TABLES = [
    "signals_ema_crossover",
    "signals_rsi",
    "signals_atr_breakout",
]

# Minimum days of baseline history required before applying z-score gate.
# If fewer than this many days of data exist, gate still runs but logs a note.
_MIN_BASELINE_DAYS = 30

# Alert type stored in pipeline_alert_log (used for throttle key lookup)
_ALERT_TYPE = "signal_gate_blocked"


# ---------------------------------------------------------------------------
# resolve_db_url / get_engine  (local copies -- avoids circular imports from
# common_snapshot_contract which lives in scripts.bars)
# ---------------------------------------------------------------------------


def _resolve_db_url(db_url: str | None) -> str:
    """Resolve DB URL from explicit value, db_config.env, or env variable."""
    if db_url:
        return db_url

    try:
        from pathlib import Path

        current = Path.cwd()
        for _ in range(5):
            env_file = current / "db_config.env"
            if env_file.exists():
                with open(env_file, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key in ("TARGET_DB_URL", "MARKETDATA_DB_URL"):
                                return value
            current = current.parent
    except Exception:
        pass

    val = os.environ.get("TARGET_DB_URL")
    if val:
        return val
    val = os.environ.get("MARKETDATA_DB_URL")
    if val:
        return val

    raise ValueError(
        "Missing DB URL. Either:\n"
        "  1. Pass --db-url argument\n"
        "  2. Create db_config.env with TARGET_DB_URL=postgresql://...\n"
        "  3. Set TARGET_DB_URL or MARKETDATA_DB_URL environment variable"
    )


def _get_engine(db_url: str) -> Engine:
    """Create a SQLAlchemy engine."""
    return create_engine(db_url, future=True)


# ---------------------------------------------------------------------------
# SignalAnomalyGate
# ---------------------------------------------------------------------------


class SignalAnomalyGate:
    """
    Detect anomalous signal patterns and block them from reaching the executor.

    Args:
        engine: SQLAlchemy engine connected to the ta_lab2 database.
        lookback_days: Rolling history window for baseline (default 90).
        zscore_threshold: Sigma threshold for count anomaly flag (default 2.0).
        crowded_pct: Fraction of open signals to flag as crowded (default 0.40).
        cooldown_hours: Telegram alert throttle window in hours (default 4).
        dry_run: If True, compute checks but skip all DB writes and Telegram.
    """

    def __init__(
        self,
        engine: Engine,
        lookback_days: int = 90,
        zscore_threshold: float = 2.0,
        crowded_pct: float = 0.40,
        cooldown_hours: int = 4,
        dry_run: bool = False,
    ) -> None:
        self._engine = engine
        self._lookback_days = lookback_days
        self._zscore_threshold = zscore_threshold
        self._crowded_pct = crowded_pct
        self._cooldown_hours = cooldown_hours
        self._dry_run = dry_run

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_gate(self) -> tuple[bool, list[dict[str, Any]]]:
        """
        Orchestrate count-anomaly and crowded-signal checks.

        Returns:
            (has_anomalies, anomaly_details)

            has_anomalies is True if ANY check detected an anomaly.
            anomaly_details is a list of dicts describing each anomaly found.
        """
        count_anomalies = self.check_signal_count_anomalies()
        crowded_anomalies = self.check_crowded_signals()

        all_anomalies = count_anomalies + crowded_anomalies
        has_anomalies = bool(all_anomalies)

        if has_anomalies:
            for anomaly in all_anomalies:
                self._send_throttled_alert(anomaly)
        else:
            logger.info(
                "Signal anomaly gate: all checks passed -- no anomalies detected"
            )

        return has_anomalies, all_anomalies

    def check_signal_count_anomalies(self) -> list[dict[str, Any]]:
        """
        For each of the 3 signal tables, compare today's signal count against
        the 90-day rolling baseline and flag if abs(z-score) > zscore_threshold.

        Baseline excludes today's signals (DATE(ts) < CURRENT_DATE) to avoid
        partial-day inflation.

        Returns:
            List of anomaly dicts (one per flagged table).
        """
        anomalies: list[dict[str, Any]] = []

        for table in _SIGNAL_TABLES:
            try:
                anomaly = self._check_one_table_count(table)
                if anomaly:
                    anomalies.append(anomaly)
            except Exception as exc:
                logger.warning("Count anomaly check failed for %s: %s", table, exc)

        return anomalies

    def check_crowded_signals(self) -> list[dict[str, Any]]:
        """
        Query all open signals from TODAY across all 3 tables (UNION ALL).
        Flag any (asset_id, direction) group that accounts for >crowded_pct of
        total open signals today.

        Returns:
            List of anomaly dicts (one per flagged asset+direction group).
        """
        sql = text("""
            WITH today_signals AS (
                SELECT id AS asset_id, direction
                FROM signals_ema_crossover
                WHERE ts >= CURRENT_DATE
                  AND position_state = 'open'
                UNION ALL
                SELECT id AS asset_id, direction
                FROM signals_rsi
                WHERE ts >= CURRENT_DATE
                  AND position_state = 'open'
                UNION ALL
                SELECT id AS asset_id, direction
                FROM signals_atr_breakout
                WHERE ts >= CURRENT_DATE
                  AND position_state = 'open'
            ),
            grouped AS (
                SELECT asset_id, direction, COUNT(*) AS group_cnt
                FROM today_signals
                GROUP BY asset_id, direction
            ),
            totals AS (
                SELECT SUM(group_cnt) AS total_cnt FROM grouped
            )
            SELECT
                g.asset_id,
                g.direction,
                g.group_cnt,
                t.total_cnt,
                CASE WHEN t.total_cnt > 0
                     THEN g.group_cnt::NUMERIC / t.total_cnt
                     ELSE 0
                END AS pct
            FROM grouped g
            CROSS JOIN totals t
            WHERE t.total_cnt > 0
            ORDER BY pct DESC
        """)

        anomalies: list[dict[str, Any]] = []

        try:
            with self._engine.connect() as conn:
                rows = conn.execute(sql).fetchall()
        except Exception as exc:
            logger.warning("Crowded signal query failed: %s", exc)
            return anomalies

        for row in rows:
            mapping = dict(row._mapping)
            pct = float(mapping.get("pct") or 0.0)
            asset_id = mapping.get("asset_id")
            direction = mapping.get("direction")
            group_cnt = int(mapping.get("group_cnt") or 0)
            total_cnt = int(mapping.get("total_cnt") or 0)

            logger.debug(
                "Crowded check: asset_id=%s direction=%s pct=%.1f%% (%d/%d)",
                asset_id,
                direction,
                pct * 100,
                group_cnt,
                total_cnt,
            )

            if pct > self._crowded_pct:
                msg = (
                    f"Crowded signal: asset_id={asset_id} direction={direction} "
                    f"accounts for {pct * 100:.1f}% of {total_cnt} open signals "
                    f"(threshold: {self._crowded_pct * 100:.0f}%)"
                )
                logger.warning(msg)

                anomaly: dict[str, Any] = {
                    "anomaly_type": "crowded_signal",
                    "signal_type": f"asset_{asset_id}_{direction}",
                    "severity": "critical",
                    "count_today": group_cnt,
                    "count_mean": None,
                    "count_zscore": None,
                    "blocked": True,
                    "notes": msg,
                    "asset_id": asset_id,
                    "direction": direction,
                    "pct": pct,
                    "total_cnt": total_cnt,
                }

                self._log_signal_anomaly(anomaly)
                anomalies.append(anomaly)

        if not anomalies:
            logger.info(
                "Crowded signal check: no groups exceed %.0f%% threshold",
                self._crowded_pct * 100,
            )

        return anomalies

    # ------------------------------------------------------------------
    # Private helpers -- count anomaly per table
    # ------------------------------------------------------------------

    def _check_one_table_count(self, table: str) -> dict[str, Any] | None:
        """
        Check signal count anomaly for a single signal table.

        Returns anomaly dict if flagged, None otherwise.
        """
        # Step 1: query historical baseline (exclude today)
        baseline_sql = text(f"""
            SELECT DATE(ts) AS day, COUNT(*) AS cnt
            FROM {table}
            WHERE ts >= CURRENT_DATE - INTERVAL ':days days'
              AND ts < CURRENT_DATE
              AND position_state = 'open'
            GROUP BY DATE(ts)
            ORDER BY day
        """)  # noqa: S608 (table name is from a hardcoded whitelist)

        with self._engine.connect() as conn:
            rows = conn.execute(baseline_sql, {"days": self._lookback_days}).fetchall()

        day_counts = [int(r._mapping["cnt"]) for r in rows]

        # Fallback: if fewer than 30 days, use full history
        if len(day_counts) < _MIN_BASELINE_DAYS:
            logger.info(
                "%s: only %d days of baseline data (< %d), fetching full history",
                table,
                len(day_counts),
                _MIN_BASELINE_DAYS,
            )
            full_sql = text(f"""
                SELECT DATE(ts) AS day, COUNT(*) AS cnt
                FROM {table}
                WHERE ts < CURRENT_DATE
                  AND position_state = 'open'
                GROUP BY DATE(ts)
                ORDER BY day
            """)
            with self._engine.connect() as conn:
                rows = conn.execute(full_sql).fetchall()
            day_counts = [int(r._mapping["cnt"]) for r in rows]

        if not day_counts:
            logger.info(
                "%s: no baseline history -- skipping count anomaly check", table
            )
            return None

        n = len(day_counts)
        mean = sum(day_counts) / n
        variance = sum((x - mean) ** 2 for x in day_counts) / max(n - 1, 1)
        std = variance**0.5

        logger.debug("%s: baseline days=%d mean=%.1f std=%.1f", table, n, mean, std)

        # Step 2: query today's count
        today_sql = text(f"""
            SELECT COUNT(*) AS cnt
            FROM {table}
            WHERE ts >= CURRENT_DATE
              AND position_state = 'open'
        """)

        with self._engine.connect() as conn:
            today_row = conn.execute(today_sql).fetchone()

        today_count = int(today_row._mapping["cnt"]) if today_row else 0

        # Step 3: compute z-score
        zscore = (today_count - mean) / max(std, 1e-6)

        logger.info(
            "%s: today_count=%d  baseline_mean=%.1f  std=%.1f  z=%.2f  "
            "(threshold=%.1f)",
            table,
            today_count,
            mean,
            std,
            zscore,
            self._zscore_threshold,
        )

        is_anomaly = abs(zscore) > self._zscore_threshold

        anomaly: dict[str, Any] = {
            "anomaly_type": "count_anomaly",
            "signal_type": table,
            "severity": "critical" if is_anomaly else "info",
            "count_today": today_count,
            "count_mean": mean,
            "count_std": std,
            "count_zscore": zscore,
            "baseline_days": n,
            "blocked": is_anomaly,
            "notes": (
                f"{table}: today={today_count} mean={mean:.1f} std={std:.1f} z={zscore:.2f}"
                f" (threshold={self._zscore_threshold:.1f})"
            ),
        }

        if is_anomaly:
            logger.warning(
                "COUNT ANOMALY: %s  today=%d  mean=%.1f  std=%.1f  z=%.2f  BLOCKED",
                table,
                today_count,
                mean,
                std,
                zscore,
            )
            self._log_signal_anomaly(anomaly)
            return anomaly
        else:
            # Log the clean check too (audit trail)
            self._log_signal_anomaly(anomaly)
            return None

    # ------------------------------------------------------------------
    # Private helpers -- DB logging
    # ------------------------------------------------------------------

    def _log_signal_anomaly(self, anomaly: dict[str, Any]) -> None:
        """Insert a row into signal_anomaly_log (non-fatal if table missing)."""
        if self._dry_run:
            logger.debug("DRY-RUN: skip signal_anomaly_log insert for %s", anomaly)
            return

        sql = text("""
            INSERT INTO signal_anomaly_log
                (signal_type, anomaly_type, severity, count_today, count_mean,
                 count_zscore, blocked, notes)
            VALUES
                (:signal_type, :anomaly_type, :severity, :count_today, :count_mean,
                 :count_zscore, :blocked, :notes)
        """)

        count_mean_val = anomaly.get("count_mean")
        count_mean_float: float | None = (
            float(count_mean_val) if count_mean_val is not None else None
        )
        count_zscore_val = anomaly.get("count_zscore")
        count_zscore_float: float | None = (
            float(count_zscore_val) if count_zscore_val is not None else None
        )

        try:
            with self._engine.begin() as conn:
                conn.execute(
                    sql,
                    {
                        "signal_type": str(anomaly.get("signal_type", "")),
                        "anomaly_type": str(anomaly.get("anomaly_type", "")),
                        "severity": str(anomaly.get("severity", "info")),
                        "count_today": anomaly.get("count_today"),
                        "count_mean": count_mean_float,
                        "count_zscore": count_zscore_float,
                        "blocked": bool(anomaly.get("blocked", False)),
                        "notes": str(anomaly.get("notes", "")),
                    },
                )
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "signal_anomaly_log not accessible (migration pending?): %s", exc
            )
        except Exception as exc:
            logger.error("Failed to log to signal_anomaly_log: %s", exc)

    def _is_alert_throttled(self, signal_type: str) -> bool:
        """
        Return True if an unthrottled alert of type signal_gate_blocked for
        this signal_type was sent within the cooldown window.
        """
        sql = text("""
            SELECT 1
            FROM pipeline_alert_log
            WHERE alert_type = :alert_type
              AND alert_key = :key
              AND sent_at > NOW() - (INTERVAL '1 hour' * :hours)
              AND throttled = FALSE
            LIMIT 1
        """)
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    sql,
                    {
                        "alert_type": _ALERT_TYPE,
                        "key": signal_type,
                        "hours": self._cooldown_hours,
                    },
                ).fetchone()
            return row is not None
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "pipeline_alert_log not accessible (migration pending?): %s", exc
            )
            return False
        except Exception as exc:
            logger.error("Error checking pipeline_alert_log throttle: %s", exc)
            return False

    def _log_pipeline_alert(
        self,
        signal_type: str,
        severity: str,
        message_preview: str,
        throttled: bool,
    ) -> None:
        """Persist alert row to pipeline_alert_log (non-fatal if table missing)."""
        if self._dry_run:
            logger.debug(
                "DRY-RUN: skip pipeline_alert_log insert  throttled=%s  %s",
                throttled,
                signal_type,
            )
            return

        sql = text("""
            INSERT INTO pipeline_alert_log
                (alert_type, alert_key, severity, message_preview, throttled)
            VALUES
                (:alert_type, :alert_key, :severity, :message_preview, :throttled)
        """)
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    sql,
                    {
                        "alert_type": _ALERT_TYPE,
                        "alert_key": signal_type,
                        "severity": severity,
                        "message_preview": message_preview[:500],
                        "throttled": throttled,
                    },
                )
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "pipeline_alert_log not accessible (migration pending?): %s", exc
            )
        except Exception as exc:
            logger.error("Failed to log to pipeline_alert_log: %s", exc)

    # ------------------------------------------------------------------
    # Private helpers -- alert dispatch
    # ------------------------------------------------------------------

    def _send_throttled_alert(self, anomaly: dict[str, Any]) -> None:
        """
        Send a throttled CRITICAL Telegram alert for a detected anomaly.

        Checks pipeline_alert_log for a recent alert within the cooldown window.
        If not throttled, sends via telegram.send_alert() with severity="critical".
        Always logs the alert attempt (throttled or not) to pipeline_alert_log.
        """
        signal_type = str(anomaly.get("signal_type", "unknown"))
        notes = str(anomaly.get("notes", ""))

        is_throttled = self._is_alert_throttled(signal_type)

        if is_throttled:
            logger.info(
                "Alert throttled: signal_gate_blocked/%s within %d-hour cooldown",
                signal_type,
                self._cooldown_hours,
            )
            self._log_pipeline_alert(
                signal_type=signal_type,
                severity="critical",
                message_preview=notes,
                throttled=True,
            )
            return

        # Build Telegram message based on anomaly type
        anomaly_type = anomaly.get("anomaly_type", "unknown")

        if anomaly_type == "count_anomaly":
            today = anomaly.get("count_today", "N/A")
            mean = anomaly.get("count_mean")
            std = anomaly.get("count_std")
            zscore = anomaly.get("count_zscore")
            mean_str = f"{mean:.1f}" if mean is not None else "N/A"
            std_str = f"{std:.1f}" if std is not None else "N/A"
            z_str = f"{zscore:.2f}" if zscore is not None else "N/A"
            message = (
                f"Signal table: {signal_type}\n"
                f"Today's count: {today}\n"
                f"Baseline mean: {mean_str} (std: {std_str})\n"
                f"Z-score: {z_str} (threshold: {self._zscore_threshold:.1f})\n\n"
                f"Signals are BLOCKED from executor until anomaly is resolved."
            )
        elif anomaly_type == "crowded_signal":
            asset_id = anomaly.get("asset_id", "N/A")
            direction = anomaly.get("direction", "N/A")
            pct = anomaly.get("pct", 0.0)
            total = anomaly.get("total_cnt", 0)
            count = anomaly.get("count_today", 0)
            message = (
                f"Crowded signal detected:\n"
                f"Asset ID: {asset_id}  Direction: {direction}\n"
                f"Group count: {count} / {total} total "
                f"({pct * 100:.1f}% -- threshold: {self._crowded_pct * 100:.0f}%)\n\n"
                f"Signals are BLOCKED from executor until anomaly is resolved."
            )
        else:
            message = notes

        title = "Signal Gate Blocked"
        sent = False

        if self._dry_run:
            logger.info(
                "DRY-RUN: would send Telegram CRITICAL alert: %s | %s", title, message
            )
        elif not telegram.is_configured():
            logger.warning(
                "Telegram not configured -- skipping send for signal gate alert: %s",
                signal_type,
            )
        else:
            try:
                sent = telegram.send_alert(title, message, severity="critical")
                if sent:
                    logger.info("Telegram CRITICAL alert sent for %s", signal_type)
                else:
                    logger.warning("Telegram send returned False for %s", signal_type)
            except Exception as exc:
                logger.error("Telegram send failed for %s: %s", signal_type, exc)

        preview = f"{title}: {message[:200]}"
        self._log_pipeline_alert(
            signal_type=signal_type,
            severity="critical",
            message_preview=preview,
            throttled=False,
        )

        if not self._dry_run and not sent and telegram.is_configured():
            logger.warning("Alert not sent (Telegram failed) for %s", signal_type)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Signal anomaly gate: detect anomalous signal patterns and "
            "block them from reaching the executor."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0 = all signals clean, safe to proceed to executor\n"
            "  1 = script error (DB failure, import error)\n"
            "  2 = anomalies detected, signals BLOCKED\n"
        ),
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLAlchemy database URL (default: TARGET_DB_URL env var or db_config.env)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="Days of rolling history for baseline computation (default: 90)",
    )
    parser.add_argument(
        "--zscore-threshold",
        type=float,
        default=2.0,
        help="Z-score threshold for count anomaly flag (default: 2.0)",
    )
    parser.add_argument(
        "--crowded-pct",
        type=float,
        default=0.40,
        help=(
            "Fraction of open signals to flag as crowded agreement "
            "(default: 0.40 = 40%%)"
        ),
    )
    parser.add_argument(
        "--cooldown-hours",
        type=int,
        default=4,
        help="Telegram alert cooldown window in hours (default: 4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute checks but skip DB writes and Telegram alerts",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Entry point for the signal anomaly gate.

    Returns:
        0 = all signals clean
        1 = script error
        2 = anomalies detected, signals blocked
    """
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # ------------------------------------------------------------------
    # DB connection
    # ------------------------------------------------------------------
    try:
        db_url = _resolve_db_url(args.db_url)
    except ValueError as exc:
        logger.error("DB URL resolution failed: %s", exc)
        return 1

    try:
        engine = _get_engine(db_url)
    except Exception as exc:
        logger.error("Engine creation failed: %s", exc)
        return 1

    # ------------------------------------------------------------------
    # Run gate
    # ------------------------------------------------------------------
    try:
        gate = SignalAnomalyGate(
            engine=engine,
            lookback_days=args.lookback_days,
            zscore_threshold=args.zscore_threshold,
            crowded_pct=args.crowded_pct,
            cooldown_hours=args.cooldown_hours,
            dry_run=args.dry_run,
        )
        has_anomalies, details = gate.run_gate()
    except Exception as exc:
        logger.error("Signal anomaly gate encountered an unexpected error: %s", exc)
        return 1

    # ------------------------------------------------------------------
    # Summary output
    # ------------------------------------------------------------------
    if has_anomalies:
        logger.warning(
            "SIGNAL GATE: %d anomal%s detected -- signals BLOCKED from executor",
            len(details),
            "y" if len(details) == 1 else "ies",
        )
        for a in details:
            logger.warning("  [%s] %s", a.get("anomaly_type"), a.get("notes"))
        if args.dry_run:
            logger.info("DRY-RUN: would return exit code 2 (blocked)")
            return 2
        return 2
    else:
        logger.info("SIGNAL GATE: all checks passed -- signals cleared for executor")
        return 0


if __name__ == "__main__":
    sys.exit(main())
