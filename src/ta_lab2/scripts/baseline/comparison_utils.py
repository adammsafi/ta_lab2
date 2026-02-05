"""
Epsilon-aware comparison utilities for baseline validation.

Provides hybrid tolerance comparison (absolute + relative) using NumPy allclose
semantics to detect calculation drift after refactoring.

Pattern from Phase 25 RESEARCH.md:
- Combine rtol (relative tolerance for large values) + atol (absolute tolerance for small values)
- Handle NaN values correctly (NaN == NaN is match)
- Column-specific tolerances for different data types (price vs volume)
- Comprehensive mismatch reporting (collect ALL mismatches, don't stop early)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


# Column-specific tolerances from RESEARCH.md Pattern 2
# Formula: abs(baseline - rebuilt) <= max(rtol * max(abs(baseline), abs(rebuilt)), atol)
COLUMN_TOLERANCES: dict[str, dict[str, float]] = {
    # Price columns (OHLC): tight tolerance for financial data
    "open": {"atol": 1e-6, "rtol": 1e-5},
    "high": {"atol": 1e-6, "rtol": 1e-5},
    "low": {"atol": 1e-6, "rtol": 1e-5},
    "close": {"atol": 1e-6, "rtol": 1e-5},
    # Volume columns: lower precision acceptable
    "volume": {"atol": 1e-2, "rtol": 1e-4},
    "market_cap": {"atol": 1e-2, "rtol": 1e-4},
    # EMA values: same as prices (derived from OHLC)
    "ema": {"atol": 1e-6, "rtol": 1e-5},
}


@dataclass
class ComparisonResult:
    """
    Result of table comparison.

    Attributes:
        passed: True if all values match within tolerance
        summary: Statistical summary dict
        mismatches: DataFrame of mismatch details (empty if passed=True)
    """

    passed: bool
    summary: dict[str, Any]
    mismatches: pd.DataFrame


def compare_with_hybrid_tolerance(
    baseline_df: pd.DataFrame,
    rebuilt_df: pd.DataFrame,
    *,
    key_columns: list[str],
    float_columns: list[str],
    rtol: float = 1e-5,
    atol: float = 1e-6,
) -> pd.DataFrame:
    """
    Compare floating-point columns using NumPy allclose tolerance.

    Uses hybrid tolerance formula from numpy.allclose:
        abs(baseline - rebuilt) <= max(rtol * max(abs(baseline), abs(rebuilt)), atol)

    For OHLCV data (prices in dollars):
        - atol=1e-6: Absolute tolerance ~0.000001 USD (catches exact equality)
        - rtol=1e-5: Relative tolerance 0.001% (catches floating-point rounding)

    Args:
        baseline_df: Baseline data (snapshot before truncate/rebuild)
        rebuilt_df: Rebuilt data (after truncate/rebuild)
        key_columns: Columns to merge on (e.g., ["id", "tf", "bar_seq", "time_close"])
        float_columns: Columns to compare with epsilon tolerance
        rtol: Relative tolerance (default: 1e-5 = 0.001%)
        atol: Absolute tolerance (default: 1e-6 = 0.000001)

    Returns:
        DataFrame with mismatch details (empty if all match).
        Columns: key_columns + column_name, baseline_value, rebuilt_value, abs_diff, rel_diff, within_tolerance

    Note:
        Uses equal_nan=True to treat NaN == NaN as match (RESEARCH.md Pitfall 1).
    """
    if baseline_df.empty and rebuilt_df.empty:
        return pd.DataFrame()

    # Merge on key columns
    merged = baseline_df.merge(
        rebuilt_df,
        on=key_columns,
        suffixes=("_baseline", "_rebuilt"),
        how="outer",
        indicator=True,
    )

    # Check for row count mismatches
    if (merged["_merge"] != "both").any():
        row_mismatches = merged[merged["_merge"] != "both"].copy()
        # Log row count mismatches separately
        print(
            f"WARNING: Row count mismatch - {len(row_mismatches)} rows only in one dataset"
        )

    # Keep only rows present in both for value comparison
    merged = merged[merged["_merge"] == "both"].drop("_merge", axis=1)

    if merged.empty:
        return pd.DataFrame()

    mismatches = []
    for col in float_columns:
        baseline_col = f"{col}_baseline"
        rebuilt_col = f"{col}_rebuilt"

        # Skip if columns don't exist in merged data
        if baseline_col not in merged.columns or rebuilt_col not in merged.columns:
            continue

        baseline_vals = merged[baseline_col].values
        rebuilt_vals = merged[rebuilt_col].values

        # Handle NaN values: both NaN = match, one NaN = mismatch
        both_nan = np.isnan(baseline_vals) & np.isnan(rebuilt_vals)

        # Compute absolute difference
        abs_diff = np.abs(baseline_vals - rebuilt_vals)

        # Compute tolerance threshold (NumPy allclose formula)
        max_val = np.maximum(np.abs(baseline_vals), np.abs(rebuilt_vals))
        tolerance_threshold = np.maximum(rtol * max_val, atol)

        # Within tolerance: passes threshold OR both are NaN
        within_tolerance = (abs_diff <= tolerance_threshold) | both_nan

        # Flag mismatches
        mismatch_mask = ~within_tolerance
        if mismatch_mask.any():
            mismatch_rows = merged[mismatch_mask].copy()

            # Add comparison metadata
            mismatch_rows["column_name"] = col
            mismatch_rows["baseline_value"] = baseline_vals[mismatch_mask]
            mismatch_rows["rebuilt_value"] = rebuilt_vals[mismatch_mask]
            mismatch_rows["abs_diff"] = abs_diff[mismatch_mask]

            # Compute relative difference (avoid division by zero)
            rel_diff = abs_diff[mismatch_mask] / np.maximum(
                np.abs(baseline_vals[mismatch_mask]), 1e-10
            )
            mismatch_rows["rel_diff"] = rel_diff
            mismatch_rows["within_tolerance"] = False

            # Keep only relevant columns
            keep_cols = key_columns + [
                "column_name",
                "baseline_value",
                "rebuilt_value",
                "abs_diff",
                "rel_diff",
                "within_tolerance",
            ]
            mismatch_rows = mismatch_rows[
                [c for c in keep_cols if c in mismatch_rows.columns]
            ]

            mismatches.append(mismatch_rows)

    if not mismatches:
        return pd.DataFrame()  # All matched

    return pd.concat(mismatches, ignore_index=True)


def summarize_comparison(
    mismatch_df: pd.DataFrame,
    total_rows: int,
) -> dict[str, Any]:
    """
    Generate statistical summary from mismatch DataFrame.

    Returns summary with:
    - match_rate: Percentage of rows matching within tolerance
    - mismatch_count: Number of rows with mismatches
    - max_diff: Maximum absolute difference
    - mean_diff: Mean absolute difference
    - std_diff: Standard deviation of absolute differences
    - severity: CRITICAL (>1% diff), WARNING (>epsilon but <1%), INFO (expected)

    Args:
        mismatch_df: DataFrame from compare_with_hybrid_tolerance
        total_rows: Total number of rows compared (for match rate calculation)

    Returns:
        Dictionary with summary statistics and severity assessment
    """
    if mismatch_df.empty:
        return {
            "match_rate": 1.0,
            "mismatch_count": 0,
            "max_diff": 0.0,
            "mean_diff": 0.0,
            "std_diff": 0.0,
            "severity": "INFO",
        }

    mismatch_count = len(mismatch_df)
    match_rate = 1.0 - (mismatch_count / total_rows) if total_rows > 0 else 0.0

    # Compute statistics on absolute differences
    abs_diffs = mismatch_df["abs_diff"].values
    max_diff = np.nanmax(abs_diffs) if len(abs_diffs) > 0 else 0.0
    mean_diff = np.nanmean(abs_diffs) if len(abs_diffs) > 0 else 0.0
    std_diff = np.nanstd(abs_diffs) if len(abs_diffs) > 0 else 0.0

    # Severity classification per CONTEXT.md
    # CRITICAL: >1% relative difference, WARNING: >epsilon but <1%, INFO: expected
    rel_diffs = mismatch_df["rel_diff"].values
    max_rel_diff = np.nanmax(rel_diffs) if len(rel_diffs) > 0 else 0.0

    if max_rel_diff > 0.01:  # >1% difference
        severity = "CRITICAL"
    elif max_rel_diff > 1e-5:  # >epsilon but <1%
        severity = "WARNING"
    else:
        severity = "INFO"

    return {
        "match_rate": match_rate,
        "mismatch_count": mismatch_count,
        "max_diff": float(max_diff),
        "mean_diff": float(mean_diff),
        "std_diff": float(std_diff),
        "max_rel_diff": float(max_rel_diff),
        "severity": severity,
    }


def compare_tables(
    baseline_df: pd.DataFrame,
    rebuilt_df: pd.DataFrame,
    *,
    key_columns: list[str],
    float_columns: list[str],
    column_tolerances: dict[str, dict[str, float]] | None = None,
) -> ComparisonResult:
    """
    High-level table comparison with per-column tolerances.

    Merges on key columns, compares all float columns with their specific tolerances,
    and returns comprehensive comparison result.

    Args:
        baseline_df: Baseline snapshot data
        rebuilt_df: Rebuilt data after truncate/rebuild
        key_columns: Columns to merge on (e.g., ["id", "tf", "bar_seq", "time_close"])
        float_columns: Columns to compare (e.g., ["open", "high", "low", "close", "volume"])
        column_tolerances: Optional dict mapping column name to {"atol": ..., "rtol": ...}
                          If None, uses COLUMN_TOLERANCES defaults

    Returns:
        ComparisonResult with passed flag, summary statistics, and mismatch details
    """
    if column_tolerances is None:
        column_tolerances = COLUMN_TOLERANCES

    total_rows = len(baseline_df)

    # Compare each column group (may have different tolerances)
    all_mismatches = []

    for col in float_columns:
        if col not in baseline_df.columns or col not in rebuilt_df.columns:
            continue

        # Get column-specific tolerances or use defaults
        tol = column_tolerances.get(col, {"atol": 1e-6, "rtol": 1e-5})

        # Compare this column
        col_mismatches = compare_with_hybrid_tolerance(
            baseline_df,
            rebuilt_df,
            key_columns=key_columns,
            float_columns=[col],
            rtol=tol["rtol"],
            atol=tol["atol"],
        )

        if not col_mismatches.empty:
            all_mismatches.append(col_mismatches)

    # Combine all mismatches
    if all_mismatches:
        mismatch_df = pd.concat(all_mismatches, ignore_index=True)
    else:
        mismatch_df = pd.DataFrame()

    # Generate summary
    summary = summarize_comparison(mismatch_df, total_rows)

    # Pass/fail determination
    passed = mismatch_df.empty

    return ComparisonResult(
        passed=passed,
        summary=summary,
        mismatches=mismatch_df,
    )
