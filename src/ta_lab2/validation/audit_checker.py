"""
audit_checker.py
~~~~~~~~~~~~~~~~
AuditChecker -- automated gap detection engine for V1 validation (VAL-05).

Runs 6 gap detection checks against the database and returns typed
AuditFinding results plus an AuditSummary.  Also generates a Markdown
audit report with a sign-off section.

Usage::

    from datetime import date
    from sqlalchemy import create_engine
    from ta_lab2.validation.audit_checker import AuditChecker

    engine = create_engine(db_url)
    checker = AuditChecker(engine)
    findings, summary = checker.run_audit(
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
    )
    report_path = checker.generate_report(
        findings=findings,
        summary=summary,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
        output_dir="reports/validation/audit",
    )
    print("Audit report written to:", report_path)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.validation.gate_framework import AuditSummary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AuditFinding:
    """Result from one gap detection check.

    Attributes:
        check_name: Human-readable name of the check.
        status:     "PASS" or "FAIL".
        count:      Number of anomalies detected (0 for PASS).
        details:    Rows of anomaly data (list of dicts).
    """

    check_name: str
    status: str
    count: int
    details: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Markdown helper (reuses pattern from drift_report.py)
# ---------------------------------------------------------------------------


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Convert DataFrame to GitHub-flavored Markdown table."""
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    rows_str = []
    for _, row in df.iterrows():
        cells = []
        for val in row:
            if pd.isna(val) if not isinstance(val, (str, bool)) else False:
                cells.append("N/A")
            elif isinstance(val, float):
                cells.append(f"{val:.4f}")
            else:
                cells.append(str(val))
        rows_str.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep] + rows_str)


# ---------------------------------------------------------------------------
# AuditChecker
# ---------------------------------------------------------------------------


class AuditChecker:
    """Automated gap detection engine for V1 validation log audit (VAL-05).

    Runs 6 checks:
      1. Missing executor run days
      2. Error runs (failed / stale_signal status)
      3. Orphaned orders (stuck in created/submitted > 2 days)
      4. Position/fill consistency (open position with no fill history)
      5. Stale price data (no 1D bar updated in last 28 hours)
      6. Drift metric gaps (executor ran but no drift metrics that day)

    Args:
        engine: SQLAlchemy engine connected to the project database.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_audit(
        self, start_date: date, end_date: date
    ) -> tuple[list[AuditFinding], AuditSummary]:
        """Run all 6 gap detection checks.

        Args:
            start_date: Inclusive start date for the audit period.
            end_date:   Inclusive end date for the audit period.

        Returns:
            Tuple of (findings list, AuditSummary).
            AuditSummary.n_anomalies = sum of all FAIL counts.
            AuditSummary.all_signed_off = True only when n_anomalies == 0.
        """
        findings: list[AuditFinding] = []

        findings.append(self._check_missing_run_days(start_date, end_date))
        findings.append(self._check_error_runs(start_date, end_date))
        findings.append(self._check_orphaned_orders())
        findings.append(self._check_position_fill_consistency())
        findings.append(self._check_stale_price_data())
        findings.append(self._check_drift_metric_gaps(start_date, end_date))

        n_anomalies = sum(f.count for f in findings if f.status == "FAIL")
        summary = AuditSummary(
            n_anomalies=n_anomalies,
            n_signed_off=0,
            all_signed_off=(n_anomalies == 0),
        )
        return findings, summary

    def generate_report(
        self,
        findings: list[AuditFinding],
        summary: AuditSummary,
        start_date: date,
        end_date: date,
        output_dir: str,
    ) -> str:
        """Write a Markdown audit report with summary and sign-off section.

        Args:
            findings:   List of AuditFinding from run_audit().
            summary:    AuditSummary from run_audit().
            start_date: Audit period start.
            end_date:   Audit period end.
            output_dir: Directory to write the report file.

        Returns:
            Absolute path to the written Markdown file.
        """
        os.makedirs(output_dir, exist_ok=True)
        generated_at = datetime.now(timezone.utc).isoformat()

        lines: list[str] = []

        # Header
        lines.append(f"# V1 Validation Audit Report: {start_date} to {end_date}")
        lines.append("")
        lines.append(f"**Generated:** {generated_at}")
        lines.append(
            f"**Anomalies detected:** {summary.n_anomalies} "
            f"| **Signed off:** {summary.n_signed_off}"
        )
        lines.append(
            f"**Overall status:** {'PASS' if summary.all_signed_off else 'FAIL -- anomalies require review'}"
        )
        lines.append("")

        # Summary table
        lines.append("## Summary")
        lines.append("")
        summary_rows = [
            {
                "Check": f.check_name,
                "Status": f.status,
                "Anomaly Count": f.count,
            }
            for f in findings
        ]
        summary_df = pd.DataFrame(summary_rows)
        lines.append(_df_to_markdown(summary_df))
        lines.append("")

        # Details per failed check
        failed = [f for f in findings if f.status == "FAIL"]
        if failed:
            lines.append("## Anomaly Details")
            lines.append("")
            for finding in failed:
                lines.append(f"### {finding.check_name}")
                lines.append(f"**Count:** {finding.count}")
                lines.append("")
                if finding.details:
                    detail_df = pd.DataFrame(finding.details)
                    lines.append(_df_to_markdown(detail_df))
                else:
                    lines.append("_No detail rows available._")
                lines.append("")

        # Sign-off section
        lines.append("## Sign-Off")
        lines.append("")
        if summary.n_anomalies == 0:
            lines.append(
                "> **No anomalies detected.** Automated gap detection passed all 6 checks."
            )
        else:
            lines.append(
                f"> **{summary.n_anomalies} anomalies detected.** "
                "Each must be reviewed and explained before sign-off."
            )
        lines.append("")
        lines.append("[ ] All anomalies reviewed and explained")
        lines.append("Operator: ___________ Date: ___________")
        lines.append("")

        # Footer
        lines.append("---")
        lines.append(
            f"*Generated at {generated_at} by AuditChecker (V1 Validation Phase 53)*"
        )

        content = "\n".join(lines)

        report_filename = f"audit_{end_date.isoformat()}.md"
        report_path = os.path.join(output_dir, report_filename)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        logger.info("Audit report written to: %s", report_path)
        return os.path.abspath(report_path)

    # ------------------------------------------------------------------
    # Check 1: Missing executor run days
    # ------------------------------------------------------------------

    def _check_missing_run_days(self, start_date: date, end_date: date) -> AuditFinding:
        """Check 1: Days in the period with no successful executor run.

        Uses generate_series to enumerate every calendar day then LEFT JOINs
        against executor_run_log (status IN ('success', 'no_signals')).
        """
        sql = text(
            """
            SELECT g.day::date AS missing_date
            FROM generate_series(
                :start_date::date,
                :end_date::date,
                '1 day'::interval
            ) AS g(day)
            LEFT JOIN (
                SELECT DISTINCT started_at::date AS run_date
                FROM executor_run_log
                WHERE status IN ('success', 'no_signals')
                  AND started_at::date BETWEEN :start_date AND :end_date
            ) r ON g.day::date = r.run_date
            WHERE r.run_date IS NULL
            ORDER BY g.day
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(
                    sql,
                    conn,
                    params={"start_date": start_date, "end_date": end_date},
                )
            count = len(df)
            return AuditFinding(
                check_name="Missing executor run days",
                status="FAIL" if count > 0 else "PASS",
                count=count,
                details=df.to_dict("records") if count > 0 else [],
            )
        except Exception as exc:
            logger.warning("_check_missing_run_days failed: %s", exc)
            return AuditFinding(
                check_name="Missing executor run days",
                status="FAIL",
                count=1,
                details=[{"error": str(exc)}],
            )

    # ------------------------------------------------------------------
    # Check 2: Error runs
    # ------------------------------------------------------------------

    def _check_error_runs(self, start_date: date, end_date: date) -> AuditFinding:
        """Check 2: Executor runs with error status (failed / stale_signal)."""
        sql = text(
            """
            SELECT run_id, started_at, status, error_message
            FROM executor_run_log
            WHERE status IN ('failed', 'stale_signal')
              AND started_at::date BETWEEN :start_date AND :end_date
            ORDER BY started_at DESC
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(
                    sql,
                    conn,
                    params={"start_date": start_date, "end_date": end_date},
                )
            count = len(df)
            return AuditFinding(
                check_name="Error runs (failed/stale_signal status)",
                status="FAIL" if count > 0 else "PASS",
                count=count,
                details=df.to_dict("records") if count > 0 else [],
            )
        except Exception as exc:
            logger.warning("_check_error_runs failed: %s", exc)
            return AuditFinding(
                check_name="Error runs (failed/stale_signal status)",
                status="FAIL",
                count=1,
                details=[{"error": str(exc)}],
            )

    # ------------------------------------------------------------------
    # Check 3: Orphaned orders
    # ------------------------------------------------------------------

    def _check_orphaned_orders(self) -> AuditFinding:
        """Check 3: Orders stuck in created/submitted status > 2 days with no fills."""
        sql = text(
            """
            SELECT order_id, asset_id, status, created_at
            FROM orders
            WHERE status IN ('created', 'submitted')
              AND created_at < now() - interval '2 days'
              AND NOT EXISTS (
                SELECT 1 FROM fills f WHERE f.order_id = orders.order_id
              )
            ORDER BY created_at ASC
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn)
            count = len(df)
            return AuditFinding(
                check_name="Orphaned orders (created/submitted > 2 days, no fills)",
                status="FAIL" if count > 0 else "PASS",
                count=count,
                details=df.to_dict("records") if count > 0 else [],
            )
        except Exception as exc:
            logger.warning("_check_orphaned_orders failed: %s", exc)
            return AuditFinding(
                check_name="Orphaned orders (created/submitted > 2 days, no fills)",
                status="FAIL",
                count=1,
                details=[{"error": str(exc)}],
            )

    # ------------------------------------------------------------------
    # Check 4: Position/fill consistency
    # ------------------------------------------------------------------

    def _check_position_fill_consistency(self) -> AuditFinding:
        """Check 4: Open positions with no fill history for the same asset.

        A non-zero position that has no corresponding fill records
        indicates a data inconsistency (manual DB edit, bug, or import).
        """
        sql = text(
            """
            SELECT p.asset_id, p.strategy_id, p.quantity, p.avg_cost_basis
            FROM positions p
            WHERE p.quantity != 0
              AND NOT EXISTS (
                SELECT 1
                FROM fills f
                JOIN orders o ON f.order_id = o.order_id
                WHERE o.asset_id = p.asset_id
              )
            ORDER BY p.asset_id, p.strategy_id
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn)
            count = len(df)
            return AuditFinding(
                check_name="Position/fill consistency (open position with no fill history)",
                status="FAIL" if count > 0 else "PASS",
                count=count,
                details=df.to_dict("records") if count > 0 else [],
            )
        except Exception as exc:
            logger.warning("_check_position_fill_consistency failed: %s", exc)
            return AuditFinding(
                check_name="Position/fill consistency (open position with no fill history)",
                status="FAIL",
                count=1,
                details=[{"error": str(exc)}],
            )

    # ------------------------------------------------------------------
    # Check 5: Stale price data
    # ------------------------------------------------------------------

    def _check_stale_price_data(self) -> AuditFinding:
        """Check 5: Assets with no 1D bar updated in the last 28 hours."""
        sql = text(
            """
            SELECT id, MAX(ts) AS latest_ts
            FROM price_bars_multi_tf_u
            WHERE tf = '1D'
            GROUP BY id
            HAVING MAX(ts) < now() - interval '28 hours'
            ORDER BY id
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn)
            count = len(df)
            return AuditFinding(
                check_name="Stale price data (1D bar older than 28 hours)",
                status="FAIL" if count > 0 else "PASS",
                count=count,
                details=df.to_dict("records") if count > 0 else [],
            )
        except Exception as exc:
            logger.warning("_check_stale_price_data failed: %s", exc)
            return AuditFinding(
                check_name="Stale price data (1D bar older than 28 hours)",
                status="FAIL",
                count=1,
                details=[{"error": str(exc)}],
            )

    # ------------------------------------------------------------------
    # Check 6: Drift metric gaps
    # ------------------------------------------------------------------

    def _check_drift_metric_gaps(
        self, start_date: date, end_date: date
    ) -> AuditFinding:
        """Check 6: Executor ran successfully but no drift metrics for that day.

        Uses a CTE to find successful executor run days then LEFT JOINs
        against drift_metrics.  A missing drift metric on a run day
        indicates the drift monitor did not run or failed silently.
        """
        sql = text(
            """
            WITH exec_days AS (
                SELECT DISTINCT started_at::date AS run_date
                FROM executor_run_log
                WHERE status IN ('success', 'no_signals')
                  AND started_at::date BETWEEN :start_date AND :end_date
            )
            SELECT e.run_date AS missing_drift_date
            FROM exec_days e
            LEFT JOIN (
                SELECT DISTINCT metric_date
                FROM drift_metrics
                WHERE metric_date BETWEEN :start_date AND :end_date
            ) dm ON e.run_date = dm.metric_date
            WHERE dm.metric_date IS NULL
            ORDER BY e.run_date
            """
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(
                    sql,
                    conn,
                    params={"start_date": start_date, "end_date": end_date},
                )
            count = len(df)
            return AuditFinding(
                check_name="Drift metric gaps (executor ran but no drift metrics)",
                status="FAIL" if count > 0 else "PASS",
                count=count,
                details=df.to_dict("records") if count > 0 else [],
            )
        except Exception as exc:
            logger.warning("_check_drift_metric_gaps failed: %s", exc)
            return AuditFinding(
                check_name="Drift metric gaps (executor ran but no drift metrics)",
                status="FAIL",
                count=1,
                details=[{"error": str(exc)}],
            )
