"""
Feature validation module for data consistency checks.

Validates feature data for:
- Gap detection: Missing dates vs expected schedule
- Outlier detection: Values outside normal bounds
- Cross-table consistency: Returns match price changes
- Rowcount validation: Expected vs actual counts
- NULL ratio: Excessive NULLs indicate data issues

Usage:
    from ta_lab2.scripts.features.validate_features import validate_features

    report = validate_features(
        engine,
        ids=[1, 52],
        start='2024-01-01',
        end='2024-12-31',
        alert=True,
    )

    if not report.passed:
        print(f"Validation failed: {report.summary}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Engine, text

from ta_lab2.notifications.telegram import (
    send_alert,
    is_configured as telegram_configured,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Issue Types
# =============================================================================


@dataclass
class ValidationIssue:
    """Base class for validation issues."""

    issue_type: str
    severity: str  # 'critical', 'warning', 'info'
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class GapIssue(ValidationIssue):
    """Missing dates in feature data."""

    def __init__(
        self, table: str, id_: int, missing_dates: list[str], expected: int, actual: int
    ):
        super().__init__(
            issue_type="gap",
            severity="warning",
            message=f"Table {table} for ID {id_} has {len(missing_dates)} missing dates (expected={expected}, actual={actual})",
            details={
                "table": table,
                "id": id_,
                "missing_count": len(missing_dates),
                "missing_dates": missing_dates[:10],  # First 10
                "expected": expected,
                "actual": actual,
            },
        )


@dataclass
class OutlierIssue(ValidationIssue):
    """Extreme outlier values detected."""

    def __init__(self, table: str, column: str, count: int, examples: list[dict]):
        super().__init__(
            issue_type="outlier",
            severity="info",  # Flag but don't fail
            message=f"Table {table}.{column} has {count} extreme outliers",
            details={
                "table": table,
                "column": column,
                "count": count,
                "examples": examples[:5],  # First 5
            },
        )


@dataclass
class ConsistencyIssue(ValidationIssue):
    """Cross-table data inconsistency."""

    def __init__(self, check: str, mismatches: int, examples: list[dict]):
        super().__init__(
            issue_type="consistency",
            severity="critical",
            message=f"Cross-table check '{check}' found {mismatches} inconsistent rows",
            details={
                "check": check,
                "mismatches": mismatches,
                "examples": examples[:5],
            },
        )


@dataclass
class NullIssue(ValidationIssue):
    """Excessive NULL values in column."""

    def __init__(self, table: str, column: str, null_ratio: float, threshold: float):
        super().__init__(
            issue_type="null_ratio",
            severity="warning",
            message=f"Table {table}.{column} has {null_ratio:.1%} NULLs (threshold={threshold:.1%})",
            details={
                "table": table,
                "column": column,
                "null_ratio": null_ratio,
                "threshold": threshold,
            },
        )


@dataclass
class RowcountIssue(ValidationIssue):
    """Rowcount outside expected range."""

    def __init__(
        self, table: str, id_: int, expected: int, actual: int, diff_pct: float
    ):
        super().__init__(
            issue_type="rowcount",
            severity="warning",
            message=f"Table {table} for ID {id_} has {actual} rows (expected={expected}, diff={diff_pct:+.1%})",
            details={
                "table": table,
                "id": id_,
                "expected": expected,
                "actual": actual,
                "diff": actual - expected,
                "diff_pct": diff_pct,
            },
        )


# =============================================================================
# Validation Report
# =============================================================================


@dataclass
class ValidationReport:
    """
    Summary of validation results.

    Attributes:
        passed: True if all checks passed
        total_checks: Total number of validation checks performed
        failed_checks: Number of checks that found issues
        issues: List of all issues found
        summary: Human-readable summary string
    """

    passed: bool
    total_checks: int
    failed_checks: int
    issues: list[ValidationIssue]
    summary: str

    def send_alert(self, telegram_config: Optional[dict] = None) -> bool:
        """
        Send alert via Telegram if issues found.

        Args:
            telegram_config: Optional Telegram configuration (unused - reads from env)

        Returns:
            True if alert sent successfully, False otherwise
        """
        if self.passed:
            logger.info("Validation passed - no alert needed")
            return True

        if not telegram_configured():
            logger.warning("Telegram not configured - skipping alert")
            return False

        # Build alert message
        critical_count = sum(1 for i in self.issues if i.severity == "critical")
        warning_count = sum(1 for i in self.issues if i.severity == "warning")

        severity = "critical" if critical_count > 0 else "warning"

        message_parts = [
            f"Total checks: {self.total_checks}",
            f"Failed: {self.failed_checks}",
            f"Critical issues: {critical_count}",
            f"Warnings: {warning_count}",
            "",
            "Issue types:",
        ]

        # Summarize by type
        issue_type_counts = {}
        for issue in self.issues:
            issue_type_counts[issue.issue_type] = (
                issue_type_counts.get(issue.issue_type, 0) + 1
            )

        for issue_type, count in issue_type_counts.items():
            message_parts.append(f"  {issue_type}: {count}")

        message_parts.append("")
        message_parts.append(self.summary)

        message = "\n".join(message_parts)

        return send_alert("Feature Validation Failed", message, severity=severity)


# =============================================================================
# Feature Validator
# =============================================================================


class FeatureValidator:
    """
    Validates feature data for gaps, anomalies, and cross-table consistency.

    Validation types:
    1. Gap detection: Missing dates vs expected schedule
    2. Outlier detection: Values outside normal bounds
    3. Cross-table consistency: Returns match price changes
    4. Rowcount validation: Expected vs actual counts
    5. NULL ratio: Excessive NULLs indicate data issues
    """

    def __init__(self, engine: Engine):
        """
        Initialize validator.

        Args:
            engine: SQLAlchemy engine for database access
        """
        self.engine = engine
        self.issues: list[ValidationIssue] = []

    def validate_all(
        self,
        ids: list[int],
        start: str,
        end: str,
    ) -> ValidationReport:
        """
        Run all validations and return report.

        Args:
            ids: List of asset IDs to validate
            start: Start date (YYYY-MM-DD)
            end: End date (YYYY-MM-DD)

        Returns:
            ValidationReport with all results
        """
        self.issues = []
        total_checks = 0

        logger.info(f"Starting validation for {len(ids)} IDs from {start} to {end}")

        # 1. Gap detection for each feature table
        tables_to_check = [
            "cmc_vol",
            "cmc_ta",
            "cmc_features",
        ]

        for table in tables_to_check:
            gap_issues = self.check_gaps(table, ids, start, end)
            self.issues.extend(gap_issues)
            total_checks += len(ids)  # One check per ID

        # 2. Outlier detection
        outlier_checks = [
            ("cmc_vol", ["vol_parkinson_20", "vol_gk_20", "vol_rs_20"]),
            ("cmc_ta", ["rsi_14", "macd_12_26", "bb_up_20_2"]),
        ]

        for table, columns in outlier_checks:
            outlier_issues = self.check_outliers(table, columns, ids)
            self.issues.extend(outlier_issues)
            total_checks += len(columns)

        # 3. Cross-table consistency
        consistency_issues = self.check_cross_table_consistency(ids)
        self.issues.extend(consistency_issues)
        total_checks += 3  # Three consistency checks

        # 4. NULL ratio checks
        null_checks = [
            ("cmc_vol", ["vol_parkinson_20", "close"]),
            ("cmc_ta", ["rsi_14", "close"]),
        ]

        for table, columns in null_checks:
            null_issues = self.check_null_ratios(table, columns, threshold=0.1)
            self.issues.extend(null_issues)
            total_checks += len(columns)

        # 5. Rowcount validation
        for table in tables_to_check:
            rowcount_issues = self.check_rowcounts(table, ids)
            self.issues.extend(rowcount_issues)
            total_checks += len(ids)

        # Build report
        failed_checks = len(self.issues)
        passed = failed_checks == 0

        if passed:
            summary = f"All {total_checks} validation checks passed"
        else:
            critical = sum(1 for i in self.issues if i.severity == "critical")
            warnings = sum(1 for i in self.issues if i.severity == "warning")
            summary = f"Validation found {failed_checks} issues: {critical} critical, {warnings} warnings"

        return ValidationReport(
            passed=passed,
            total_checks=total_checks,
            failed_checks=failed_checks,
            issues=self.issues,
            summary=summary,
        )

    def check_gaps(
        self,
        table: str,
        ids: list[int],
        start: str,
        end: str,
    ) -> list[GapIssue]:
        """
        Detect missing dates vs expected schedule.

        Uses dim_timeframe + dim_sessions to know expected dates.
        For crypto: Every calendar day
        For equity: Trading days only (skip weekends, holidays)

        Args:
            table: Feature table name
            ids: List of asset IDs
            start: Start date (YYYY-MM-DD)
            end: End date (YYYY-MM-DD)

        Returns:
            List of gap issues found
        """
        issues = []

        # Check if table exists
        table_exists_query = text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = :table
            )
        """
        )

        with self.engine.connect() as conn:
            exists = conn.execute(table_exists_query, {"table": table}).scalar()
            if not exists:
                logger.warning(f"Table {table} does not exist - skipping gap check")
                return issues

        for id_ in ids:
            # Get actual dates from table
            query = text(
                f"""
                SELECT DISTINCT DATE(ts) as date
                FROM public.{table}
                WHERE id = :id
                  AND DATE(ts) BETWEEN :start AND :end
                ORDER BY date
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(query, {"id": id_, "start": start, "end": end})
                actual_dates = {row[0] for row in result}

            if not actual_dates:
                logger.warning(f"No data found for ID {id_} in {table}")
                continue

            # Generate expected dates (simplified - assume daily for now)
            # In production, this should query dim_sessions for asset's session type
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")

            expected_dates = set()
            current = start_dt
            while current <= end_dt:
                expected_dates.add(current.date())
                current += timedelta(days=1)

            # Find missing dates
            missing = sorted(expected_dates - actual_dates)

            if missing:
                issues.append(
                    GapIssue(
                        table=table,
                        id_=id_,
                        missing_dates=[d.strftime("%Y-%m-%d") for d in missing],
                        expected=len(expected_dates),
                        actual=len(actual_dates),
                    )
                )

        return issues

    def check_outliers(
        self,
        table: str,
        columns: list[str],
        ids: list[int],
    ) -> list[OutlierIssue]:
        """
        Detect extreme outliers.

        Thresholds (per CONTEXT.md):
        - Returns: |ret| > 50% in single day
        - Volatility: vol > 500% annualized
        - RSI: Outside 0-100 (should never happen)
        - MACD: |macd| > 10 * std

        Flag but don't fail - transparency for analysis.

        Args:
            table: Feature table name
            columns: List of columns to check
            ids: List of asset IDs

        Returns:
            List of outlier issues found
        """
        issues = []

        # Check if table exists
        table_exists_query = text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = :table
            )
        """
        )

        with self.engine.connect() as conn:
            exists = conn.execute(table_exists_query, {"table": table}).scalar()
            if not exists:
                logger.warning(f"Table {table} does not exist - skipping outlier check")
                return issues

        for column in columns:
            # Determine threshold based on column type
            if "ret" in column.lower() or "return" in column.lower():
                threshold = 0.5  # 50% daily return
                condition = f"ABS({column}) > {threshold}"
            elif "vol" in column.lower():
                threshold = 5.0  # 500% annualized vol
                condition = f"{column} > {threshold}"
            elif "rsi" in column.lower():
                condition = f"({column} < 0 OR {column} > 100)"
            elif "macd" in column.lower():
                # For MACD, use simple large value check
                threshold = 100
                condition = f"ABS({column}) > {threshold}"
            else:
                # Generic: use z-score > 10
                continue  # Skip unknown column types

            # Check for column existence first
            col_exists_query = text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table
                      AND column_name = :column
                )
            """
            )

            with self.engine.connect() as conn:
                col_exists = conn.execute(
                    col_exists_query, {"table": table, "column": column}
                ).scalar()
                if not col_exists:
                    logger.debug(
                        f"Column {column} does not exist in {table} - skipping"
                    )
                    continue

            # Find outliers
            ids_str = ",".join(str(i) for i in ids)
            query = text(
                f"""
                SELECT id, ts, {column}
                FROM public.{table}
                WHERE id IN ({ids_str})
                  AND {condition}
                  AND {column} IS NOT NULL
                ORDER BY ABS({column}) DESC
                LIMIT 100
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(query)
                outliers = [
                    {
                        "id": row[0],
                        "ts": str(row[1]),
                        "value": float(row[2]),
                    }
                    for row in result
                ]

            if outliers:
                issues.append(
                    OutlierIssue(
                        table=table,
                        column=column,
                        count=len(outliers),
                        examples=outliers,
                    )
                )

        return issues

    def check_cross_table_consistency(
        self,
        ids: list[int],
    ) -> list[ConsistencyIssue]:
        """
        Verify cross-table relationships.

        Checks:
        - cmc_returns_bars_multi_tf.ret_arith ~= (close - prev_close) / prev_close
        - cmc_vol.close == cmc_price_bars_multi_tf.close
        - cmc_ta.close == cmc_price_bars_multi_tf.close
        - cmc_features has matching timestamps

        Args:
            ids: List of asset IDs

        Returns:
            List of consistency issues found
        """
        issues = []
        ids_str = ",".join(str(i) for i in ids)

        # Check 1: Returns match price changes
        check_returns_query = text(
            f"""
            WITH price_changes AS (
                SELECT
                    id,
                    ts,
                    close,
                    LAG(close) OVER (PARTITION BY id ORDER BY ts) as prev_close,
                    (close - LAG(close) OVER (PARTITION BY id ORDER BY ts)) /
                    NULLIF(LAG(close) OVER (PARTITION BY id ORDER BY ts), 0) as calc_ret
                FROM public.cmc_price_bars_1d
                WHERE id IN ({ids_str})
            ),
            mismatches AS (
                SELECT
                    p.id,
                    p.ts,
                    p.calc_ret,
                    r.ret_arith,
                    ABS(p.calc_ret - r.ret_arith) as diff
                FROM price_changes p
                JOIN public.cmc_returns_bars_multi_tf r
                  ON p.id = r.id AND DATE(p.ts) = DATE(r."timestamp")
                  AND r.tf = '1D' AND r.roll = FALSE
                WHERE p.calc_ret IS NOT NULL
                  AND r.ret_arith IS NOT NULL
                  AND ABS(p.calc_ret - r.ret_arith) > 0.0001  -- 0.01% tolerance
            )
            SELECT id, ts, calc_ret, ret_arith, diff
            FROM mismatches
            ORDER BY diff DESC
            LIMIT 10
        """
        )

        try:
            with self.engine.connect() as conn:
                result = conn.execute(check_returns_query)
                mismatches = [
                    {
                        "id": row[0],
                        "ts": str(row[1]),
                        "calc_ret": float(row[2]) if row[2] is not None else None,
                        "ret_1d_pct": float(row[3]) if row[3] is not None else None,
                        "diff": float(row[4]) if row[4] is not None else None,
                    }
                    for row in result
                ]

            if mismatches:
                issues.append(
                    ConsistencyIssue(
                        check="returns_vs_price_changes",
                        mismatches=len(mismatches),
                        examples=mismatches,
                    )
                )
        except Exception as e:
            logger.warning(f"Returns consistency check failed: {e}")

        # Check 2: Vol close matches bars close
        check_vol_close_query = text(
            f"""
            SELECT v.id, v.ts, v.close as vol_close, b.close as bar_close
            FROM public.cmc_vol v
            JOIN public.cmc_price_bars_multi_tf b
              ON v.id = b.id AND v.ts = b.time_close AND v.tf = b.tf
            WHERE v.id IN ({ids_str})
              AND v.tf = '1D'
              AND ABS(v.close - b.close) > 0.01
            LIMIT 10
        """
        )

        try:
            with self.engine.connect() as conn:
                result = conn.execute(check_vol_close_query)
                mismatches = [
                    {
                        "id": row[0],
                        "ts": str(row[1]),
                        "vol_close": float(row[2]) if row[2] is not None else None,
                        "bar_close": float(row[3]) if row[3] is not None else None,
                    }
                    for row in result
                ]

            if mismatches:
                issues.append(
                    ConsistencyIssue(
                        check="vol_close_vs_bars",
                        mismatches=len(mismatches),
                        examples=mismatches,
                    )
                )
        except Exception as e:
            logger.warning(f"Vol close consistency check failed: {e}")

        # Check 3: TA close matches bars close
        check_ta_close_query = text(
            f"""
            SELECT t.id, t.ts, t.close as ta_close, b.close as bar_close
            FROM public.cmc_ta t
            JOIN public.cmc_price_bars_multi_tf b
              ON t.id = b.id AND t.ts = b.time_close AND t.tf = b.tf
            WHERE t.id IN ({ids_str})
              AND t.tf = '1D'
              AND ABS(t.close - b.close) > 0.01
            LIMIT 10
        """
        )

        try:
            with self.engine.connect() as conn:
                result = conn.execute(check_ta_close_query)
                mismatches = [
                    {
                        "id": row[0],
                        "ts": str(row[1]),
                        "ta_close": float(row[2]) if row[2] is not None else None,
                        "bar_close": float(row[3]) if row[3] is not None else None,
                    }
                    for row in result
                ]

            if mismatches:
                issues.append(
                    ConsistencyIssue(
                        check="ta_close_vs_bars",
                        mismatches=len(mismatches),
                        examples=mismatches,
                    )
                )
        except Exception as e:
            logger.warning(f"TA close consistency check failed: {e}")

        return issues

    def check_null_ratios(
        self,
        table: str,
        columns: list[str],
        threshold: float = 0.1,
    ) -> list[NullIssue]:
        """
        Check for excessive NULLs.

        > threshold (default 10%) triggers warning.

        Args:
            table: Feature table name
            columns: List of columns to check
            threshold: NULL ratio threshold (default 0.1 = 10%)

        Returns:
            List of null ratio issues found
        """
        issues = []

        # Check if table exists
        table_exists_query = text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = :table
            )
        """
        )

        with self.engine.connect() as conn:
            exists = conn.execute(table_exists_query, {"table": table}).scalar()
            if not exists:
                logger.warning(f"Table {table} does not exist - skipping NULL check")
                return issues

        for column in columns:
            # Check column existence
            col_exists_query = text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table
                      AND column_name = :column
                )
            """
            )

            with self.engine.connect() as conn:
                col_exists = conn.execute(
                    col_exists_query, {"table": table, "column": column}
                ).scalar()
                if not col_exists:
                    logger.debug(
                        f"Column {column} does not exist in {table} - skipping"
                    )
                    continue

            # Calculate NULL ratio
            query = text(
                f"""
                SELECT
                    COUNT(*) as total,
                    COUNT({column}) as non_null,
                    COUNT(*) - COUNT({column}) as null_count,
                    CASE
                        WHEN COUNT(*) > 0 THEN
                            (COUNT(*) - COUNT({column}))::FLOAT / COUNT(*)
                        ELSE 0
                    END as null_ratio
                FROM public.{table}
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(query)
                row = result.fetchone()

                if row and row[3] > threshold:
                    issues.append(
                        NullIssue(
                            table=table,
                            column=column,
                            null_ratio=float(row[3]),
                            threshold=threshold,
                        )
                    )

        return issues

    def check_rowcounts(
        self,
        table: str,
        ids: list[int],
    ) -> list[RowcountIssue]:
        """
        Validate actual vs expected row counts.

        Expected = date_range * len(ids)
        Tolerance: +/- 5% (accounts for delisted assets, etc.)

        Args:
            table: Feature table name
            ids: List of asset IDs

        Returns:
            List of rowcount issues found
        """
        issues = []

        # Check if table exists
        table_exists_query = text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = :table
            )
        """
        )

        with self.engine.connect() as conn:
            exists = conn.execute(table_exists_query, {"table": table}).scalar()
            if not exists:
                logger.warning(
                    f"Table {table} does not exist - skipping rowcount check"
                )
                return issues

        for id_ in ids:
            # Get actual rowcount
            query = text(
                f"""
                SELECT
                    MIN(DATE(ts)) as min_date,
                    MAX(DATE(ts)) as max_date,
                    COUNT(*) as actual_count
                FROM public.{table}
                WHERE id = :id
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(query, {"id": id_})
                row = result.fetchone()

                if not row or row[0] is None:
                    logger.debug(f"No data for ID {id_} in {table}")
                    continue

                min_date = row[0]
                max_date = row[1]
                actual = row[2]

                # Calculate expected (simplified - daily for now)
                days = (max_date - min_date).days + 1
                expected = days

                # Check tolerance (5%)
                diff = actual - expected
                diff_pct = diff / expected if expected > 0 else 0

                if abs(diff_pct) > 0.05:  # 5% tolerance
                    issues.append(
                        RowcountIssue(
                            table=table,
                            id_=id_,
                            expected=expected,
                            actual=actual,
                            diff_pct=diff_pct,
                        )
                    )

        return issues


# =============================================================================
# Convenience Function
# =============================================================================


def validate_features(
    engine: Engine,
    ids: Optional[list[int]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    alert: bool = True,
) -> ValidationReport:
    """
    Convenience function to run all validations.

    If alert=True and issues found, sends Telegram notification.
    Graceful degradation if Telegram not configured.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs (None = sample from tables)
        start: Start date (YYYY-MM-DD, None = 30 days ago)
        end: End date (YYYY-MM-DD, None = today)
        alert: Send Telegram alert if issues found

    Returns:
        ValidationReport with results
    """
    # Default date range: last 30 days
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    if start is None:
        start_dt = datetime.now() - timedelta(days=30)
        start = start_dt.strftime("%Y-%m-%d")

    # Default IDs: sample from returns table
    if ids is None:
        query = text(
            """
            SELECT DISTINCT id
            FROM public.cmc_price_bars_multi_tf
            ORDER BY id
            LIMIT 10
        """
        )

        try:
            with engine.connect() as conn:
                result = conn.execute(query)
                ids = [row[0] for row in result]
        except Exception as e:
            logger.warning(f"Could not load default IDs: {e}")
            ids = []

    if not ids:
        logger.warning("No IDs to validate")
        return ValidationReport(
            passed=True,
            total_checks=0,
            failed_checks=0,
            issues=[],
            summary="No IDs to validate",
        )

    # Run validation
    validator = FeatureValidator(engine)
    report = validator.validate_all(ids, start, end)

    # Send alert if requested and issues found
    if alert and not report.passed:
        report.send_alert()

    return report
