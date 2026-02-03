"""Data quality validation for economic data.

Provides comprehensive validation including null checks, type validation,
statistical outlier detection, and range validation based on historical norms.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any

import pandas as pd

from ta_lab2.integrations.economic.types import EconomicSeries

logger = logging.getLogger(__name__)


@dataclass
class QualityIssue:
    """A single data quality issue."""

    severity: str  # "error", "warning", "info"
    category: str  # "null", "type", "range", "outlier", "gap"
    message: str
    affected_dates: List[datetime] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityReport:
    """Quality validation report for a series."""

    series_id: str
    is_valid: bool
    issues: List[QualityIssue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    validated_at: datetime = field(default_factory=datetime.now)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


class QualityValidator:
    """Validator for economic time series data.

    Performs comprehensive quality checks:
    - Null/NaN value detection
    - Type validation (numeric)
    - Statistical outlier detection (IQR-based)
    - Range validation (configurable bounds)
    - Gap detection (missing dates)

    Attributes:
        null_threshold: Max proportion of nulls (default 0.05 = 5%)
        outlier_iqr_multiplier: IQR multiplier for outlier detection (default 3.0)

    Example:
        >>> validator = QualityValidator()
        >>> report = validator.validate(series)
        >>> if not report.is_valid:
        ...     for issue in report.issues:
        ...         print(f"{issue.severity}: {issue.message}")
    """

    # Known reasonable ranges for common economic series
    KNOWN_RANGES = {
        "FEDFUNDS": (-1.0, 25.0),  # Fed funds rate (can go slightly negative)
        "UNRATE": (0.0, 30.0),  # Unemployment rate
        "CPIAUCSL": (0.0, 500.0),  # CPI index
        "DGS10": (-2.0, 20.0),  # 10-year treasury
        "DGS2": (-2.0, 20.0),  # 2-year treasury
    }

    def __init__(
        self,
        null_threshold: float = 0.05,
        outlier_iqr_multiplier: float = 3.0,
        check_gaps: bool = True,
    ):
        """Initialize validator.

        Args:
            null_threshold: Max allowed null proportion (default 5%)
            outlier_iqr_multiplier: IQR multiplier for outliers (default 3.0)
            check_gaps: Whether to check for date gaps
        """
        self.null_threshold = null_threshold
        self.outlier_iqr_multiplier = outlier_iqr_multiplier
        self.check_gaps = check_gaps

    def validate(self, series: EconomicSeries) -> QualityReport:
        """Validate an economic series.

        Args:
            series: EconomicSeries to validate

        Returns:
            QualityReport with issues and statistics
        """
        issues: List[QualityIssue] = []
        data = series.data

        # Calculate basic stats
        stats = self._calculate_stats(data)

        # Check for empty data
        if len(data) == 0:
            issues.append(
                QualityIssue(
                    severity="error",
                    category="null",
                    message="Series has no data",
                )
            )
            return QualityReport(
                series_id=series.series_id,
                is_valid=False,
                issues=issues,
                stats=stats,
            )

        # Null checks
        null_issues = self._check_nulls(data)
        issues.extend(null_issues)

        # Type validation
        type_issues = self._check_types(data)
        issues.extend(type_issues)

        # Statistical outliers
        outlier_issues = self._check_outliers(data, series.series_id)
        issues.extend(outlier_issues)

        # Range validation (if known range exists)
        range_issues = self._check_range(data, series.series_id)
        issues.extend(range_issues)

        # Gap detection
        if self.check_gaps:
            gap_issues = self._check_gaps(data, series.frequency)
            issues.extend(gap_issues)

        # Determine overall validity (no errors)
        is_valid = not any(i.severity == "error" for i in issues)

        return QualityReport(
            series_id=series.series_id,
            is_valid=is_valid,
            issues=issues,
            stats=stats,
        )

    def _calculate_stats(self, data: pd.Series) -> Dict[str, Any]:
        """Calculate descriptive statistics."""
        if len(data) == 0:
            return {"count": 0}

        numeric_data = pd.to_numeric(data, errors="coerce")
        return {
            "count": len(data),
            "null_count": data.isna().sum(),
            "null_pct": data.isna().mean(),
            "min": numeric_data.min() if len(numeric_data.dropna()) > 0 else None,
            "max": numeric_data.max() if len(numeric_data.dropna()) > 0 else None,
            "mean": numeric_data.mean() if len(numeric_data.dropna()) > 0 else None,
            "std": numeric_data.std() if len(numeric_data.dropna()) > 0 else None,
        }

    def _check_nulls(self, data: pd.Series) -> List[QualityIssue]:
        """Check for null/NaN values."""
        issues = []
        null_pct = data.isna().mean()

        if null_pct > 0:
            null_dates = data.index[data.isna()].tolist()
            severity = "error" if null_pct > self.null_threshold else "warning"
            issues.append(
                QualityIssue(
                    severity=severity,
                    category="null",
                    message=f"{null_pct*100:.1f}% null values ({data.isna().sum()} of {len(data)})",
                    affected_dates=null_dates[:10],  # Limit to first 10
                    details={"null_percentage": null_pct},
                )
            )

        return issues

    def _check_types(self, data: pd.Series) -> List[QualityIssue]:
        """Check that values are numeric."""
        issues = []

        try:
            pd.to_numeric(data, errors="raise")
        except (ValueError, TypeError):
            # Find non-numeric values
            non_numeric = data[
                pd.to_numeric(data, errors="coerce").isna() & data.notna()
            ]
            if len(non_numeric) > 0:
                issues.append(
                    QualityIssue(
                        severity="error",
                        category="type",
                        message=f"{len(non_numeric)} non-numeric values found",
                        affected_dates=non_numeric.index.tolist()[:10],
                        details={"sample_values": non_numeric.head().tolist()},
                    )
                )

        return issues

    def _check_outliers(self, data: pd.Series, series_id: str) -> List[QualityIssue]:
        """Detect statistical outliers using IQR method."""
        issues = []
        numeric_data = pd.to_numeric(data, errors="coerce").dropna()

        if len(numeric_data) < 10:
            return issues

        q1 = numeric_data.quantile(0.25)
        q3 = numeric_data.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - self.outlier_iqr_multiplier * iqr
        upper_bound = q3 + self.outlier_iqr_multiplier * iqr

        outliers = numeric_data[
            (numeric_data < lower_bound) | (numeric_data > upper_bound)
        ]

        if len(outliers) > 0:
            issues.append(
                QualityIssue(
                    severity="warning",
                    category="outlier",
                    message=f"{len(outliers)} statistical outliers detected (IQR method)",
                    affected_dates=outliers.index.tolist()[:10],
                    details={
                        "lower_bound": lower_bound,
                        "upper_bound": upper_bound,
                        "outlier_values": outliers.head().tolist(),
                    },
                )
            )

        return issues

    def _check_range(self, data: pd.Series, series_id: str) -> List[QualityIssue]:
        """Check values against known reasonable ranges."""
        issues = []

        if series_id not in self.KNOWN_RANGES:
            return issues

        min_val, max_val = self.KNOWN_RANGES[series_id]
        numeric_data = pd.to_numeric(data, errors="coerce").dropna()

        out_of_range = numeric_data[(numeric_data < min_val) | (numeric_data > max_val)]

        if len(out_of_range) > 0:
            issues.append(
                QualityIssue(
                    severity="error",
                    category="range",
                    message=f"{len(out_of_range)} values outside expected range [{min_val}, {max_val}]",
                    affected_dates=out_of_range.index.tolist()[:10],
                    details={
                        "expected_min": min_val,
                        "expected_max": max_val,
                        "actual_values": out_of_range.head().tolist(),
                    },
                )
            )

        return issues

    def _check_gaps(self, data: pd.Series, frequency: str) -> List[QualityIssue]:
        """Check for unexpected gaps in the time series."""
        issues = []

        if len(data) < 2:
            return issues

        # Determine expected frequency
        freq_map = {
            "Daily": "D",
            "Weekly": "W",
            "Monthly": "MS",
            "Quarterly": "QS",
            "Annual": "YS",
        }
        expected_freq = freq_map.get(frequency, "D")

        try:
            expected_range = pd.date_range(
                start=data.index.min(), end=data.index.max(), freq=expected_freq
            )
            missing_dates = expected_range.difference(data.index)

            if len(missing_dates) > 0:
                issues.append(
                    QualityIssue(
                        severity="warning",
                        category="gap",
                        message=f"{len(missing_dates)} expected dates missing",
                        affected_dates=missing_dates.tolist()[:10],
                        details={"expected_frequency": frequency},
                    )
                )
        except Exception as e:
            logger.warning(f"Gap check failed: {e}")

        return issues
