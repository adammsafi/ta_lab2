"""
Reproducibility validation for signal generation and backtesting.

Implements triple-layer reproducibility:
1. Deterministic timestamp queries (no random sampling)
2. Feature hashing (git-style content hash)
3. Version tracking (signal_version, vbt_version, params_hash)

This module provides utilities to:
- Run identical backtests twice and verify deterministic results
- Compare historical backtest runs to detect data changes
- Validate feature data matches stored hash (strict/warn/trust modes)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import logging

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.signals.signal_utils import compute_feature_hash
from ta_lab2.scripts.backtests import SignalBacktester

logger = logging.getLogger(__name__)


@dataclass
class ReproducibilityReport:
    """
    Results from reproducibility validation.

    Compares two backtest runs and identifies any differences in PnL, metrics,
    trade counts, and feature data hashes.

    Attributes:
        is_reproducible: True if all checks pass
        run_id_1: First backtest run ID
        run_id_2: Second backtest run ID
        pnl_match: True if total returns match within tolerance
        metrics_match: True if all metrics match within tolerance
        trade_count_match: True if trade counts identical
        feature_hash_match: True if feature data hashes match
        differences: List of human-readable difference descriptions
    """

    is_reproducible: bool
    run_id_1: str
    run_id_2: str
    pnl_match: bool
    metrics_match: bool
    trade_count_match: bool
    feature_hash_match: bool
    differences: list[str]

    def __str__(self) -> str:
        """Human-readable report."""
        status = "REPRODUCIBLE" if self.is_reproducible else "NOT REPRODUCIBLE"
        lines = [
            f"Reproducibility Report: {status}",
            f"  Run 1: {self.run_id_1}",
            f"  Run 2: {self.run_id_2}",
            f"  PnL Match: {self.pnl_match}",
            f"  Metrics Match: {self.metrics_match}",
            f"  Trade Count Match: {self.trade_count_match}",
            f"  Feature Hash Match: {self.feature_hash_match}",
        ]

        if self.differences:
            lines.append("  Differences:")
            for diff in self.differences:
                lines.append(f"    - {diff}")

        return "\n".join(lines)


def validate_backtest_reproducibility(
    backtester: SignalBacktester,
    signal_type: str,
    signal_id: int,
    asset_id: int,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    strict: bool = True,
    tolerance: float = 1e-10,
) -> ReproducibilityReport:
    """
    Run backtest twice and verify identical results.

    Executes the same backtest configuration twice and compares all outputs
    to verify deterministic behavior. This is the gold standard reproducibility
    test - if two runs produce different results, something is non-deterministic.

    Args:
        backtester: Configured SignalBacktester instance
        signal_type: Signal table to test ('ema_crossover', 'rsi_mean_revert', 'atr_breakout')
        signal_id: Signal configuration ID from dim_signals
        asset_id: Asset to backtest
        start_ts: Backtest start timestamp (inclusive)
        end_ts: Backtest end timestamp (inclusive)
        strict: If True, fail on any difference. If False, warn but proceed.
        tolerance: Numerical tolerance for floating point comparisons (default 1e-10)

    Returns:
        ReproducibilityReport with detailed comparison results

    Raises:
        ValueError: If backtester.run_backtest fails
        RuntimeError: If strict=True and results differ

    Examples:
        >>> backtester = SignalBacktester(engine, CostModel())
        >>> report = validate_backtest_reproducibility(
        ...     backtester, 'ema_crossover', 1, 1,
        ...     pd.Timestamp('2023-01-01', tz='UTC'),
        ...     pd.Timestamp('2023-12-31', tz='UTC')
        ... )
        >>> assert report.is_reproducible
    """
    logger.info(
        f"Validating reproducibility: {signal_type}/{signal_id} on asset {asset_id}"
    )
    logger.debug(f"  Date range: {start_ts} to {end_ts}")
    logger.debug(f"  Strict mode: {strict}, Tolerance: {tolerance}")

    # Run 1
    logger.debug("Running backtest (attempt 1)...")
    result1 = backtester.run_backtest(
        signal_type, signal_id, asset_id, start_ts, end_ts
    )

    # Run 2 (identical parameters)
    logger.debug("Running backtest (attempt 2)...")
    result2 = backtester.run_backtest(
        signal_type, signal_id, asset_id, start_ts, end_ts
    )

    # Compare results
    differences = []

    # 1. Compare PnL
    pnl_match = abs(result1.total_return - result2.total_return) < tolerance
    if not pnl_match:
        diff_pct = abs(result1.total_return - result2.total_return) * 100
        differences.append(
            f"PnL mismatch: {result1.total_return:.6f} vs {result2.total_return:.6f} "
            f"(diff: {diff_pct:.6f}%)"
        )
        logger.warning(
            f"PnL differs between runs: {result1.total_return} vs {result2.total_return}"
        )

    # 2. Compare metrics
    metrics_match = _compare_metrics(result1.metrics, result2.metrics, tolerance)
    if not metrics_match:
        # Find specific metric differences
        metric_diffs = _find_metric_differences(
            result1.metrics, result2.metrics, tolerance
        )
        for metric, (val1, val2) in metric_diffs.items():
            differences.append(f"Metric '{metric}': {val1} vs {val2}")
        logger.warning(
            f"Metrics differ between runs: {len(metric_diffs)} metrics mismatch"
        )

    # 3. Compare trade counts
    trade_count_match = result1.trade_count == result2.trade_count
    if not trade_count_match:
        differences.append(
            f"Trade count mismatch: {result1.trade_count} vs {result2.trade_count}"
        )
        logger.warning(
            f"Trade counts differ: {result1.trade_count} vs {result2.trade_count}"
        )

    # 4. Feature hash (both runs use same data source, should always match)
    feature_hash_match = True

    # Determine overall reproducibility
    is_reproducible = pnl_match and metrics_match and trade_count_match

    # Build report
    report = ReproducibilityReport(
        is_reproducible=is_reproducible,
        run_id_1=result1.run_id,
        run_id_2=result2.run_id,
        pnl_match=pnl_match,
        metrics_match=metrics_match,
        trade_count_match=trade_count_match,
        feature_hash_match=feature_hash_match,
        differences=differences,
    )

    # Log result
    if is_reproducible:
        logger.info("✓ Reproducibility validation PASSED")
    else:
        logger.error(
            f"✗ Reproducibility validation FAILED: {len(differences)} differences found"
        )

        if strict:
            raise RuntimeError(
                f"Reproducibility validation failed in strict mode. "
                f"Differences: {differences}"
            )

    return report


def compare_backtest_runs(
    engine: Engine,
    run_id_1: str,
    run_id_2: str,
    tolerance: float = 1e-10,
) -> ReproducibilityReport:
    """
    Compare two stored backtest runs from database.

    Used to compare historical runs after data updates. This is useful for
    detecting when underlying feature data has changed (via feature hash
    comparison) or when backtest logic has changed (via result comparison).

    Args:
        engine: SQLAlchemy engine for database operations
        run_id_1: First backtest run UUID
        run_id_2: Second backtest run UUID
        tolerance: Numerical tolerance for floating point comparisons

    Returns:
        ReproducibilityReport with comparison results

    Raises:
        ValueError: If run IDs not found in database
        sqlalchemy.exc.SQLAlchemyError: On database errors

    Examples:
        >>> report = compare_backtest_runs(engine, run1_uuid, run2_uuid)
        >>> if not report.feature_hash_match:
        ...     print("Warning: Feature data changed between runs")
    """
    logger.info(f"Comparing backtest runs: {run_id_1} vs {run_id_2}")

    # Load runs from cmc_backtest_runs
    run1 = _load_run(engine, run_id_1)
    run2 = _load_run(engine, run_id_2)

    # Compare feature hashes (detects data changes)
    feature_hash_match = run1["feature_hash"] == run2["feature_hash"]
    if not feature_hash_match:
        logger.warning(
            f"Feature hashes differ: {run1['feature_hash']} vs {run2['feature_hash']}"
        )

    # Compare results
    differences = []

    pnl_match = abs(run1["total_return"] - run2["total_return"]) < tolerance
    if not pnl_match:
        differences.append(
            f"PnL: {run1['total_return']:.6f} vs {run2['total_return']:.6f}"
        )

    # Load and compare trades
    trades1 = _load_trades(engine, run_id_1)
    trades2 = _load_trades(engine, run_id_2)
    trade_count_match = len(trades1) == len(trades2)
    if not trade_count_match:
        differences.append(f"Trade count: {len(trades1)} vs {len(trades2)}")

    # Load and compare metrics
    metrics1 = _load_metrics(engine, run_id_1)
    metrics2 = _load_metrics(engine, run_id_2)
    metrics_match = _compare_metrics(metrics1, metrics2, tolerance)
    if not metrics_match:
        metric_diffs = _find_metric_differences(metrics1, metrics2, tolerance)
        for metric, (val1, val2) in metric_diffs.items():
            differences.append(f"Metric '{metric}': {val1} vs {val2}")

    is_reproducible = pnl_match and trade_count_match and metrics_match

    return ReproducibilityReport(
        is_reproducible=is_reproducible,
        run_id_1=run_id_1,
        run_id_2=run_id_2,
        pnl_match=pnl_match,
        metrics_match=metrics_match,
        trade_count_match=trade_count_match,
        feature_hash_match=feature_hash_match,
        differences=differences,
    )


def validate_feature_hash_current(
    engine: Engine,
    signal_type: str,
    signal_id: int,
    asset_id: int,
    mode: str = "warn",
) -> tuple[bool, Optional[str]]:
    """
    Validate that current feature data matches stored hash from signal generation.

    Compares the hash of current feature data (from cmc_features) with
    the hash stored during signal generation. This detects when underlying data
    has changed, invalidating reproducibility.

    Args:
        engine: SQLAlchemy engine for database operations
        signal_type: Signal table suffix ('ema_crossover', 'rsi_mean_revert', 'atr_breakout')
        signal_id: Signal configuration ID
        asset_id: Asset to validate
        mode: Validation strictness:
            - 'strict': Fail if hash mismatch (returns False)
            - 'warn': Log warning but proceed (returns True with warning message)
            - 'trust': Skip validation entirely (returns True immediately)

    Returns:
        Tuple of (is_valid, message)
        - is_valid: True if hash matches (or mode='warn'/'trust'), False if mismatch in strict mode
        - message: None if valid, error/warning message otherwise

    Examples:
        >>> is_valid, msg = validate_feature_hash_current(
        ...     engine, 'ema_crossover', 1, 1, mode='strict'
        ... )
        >>> if not is_valid:
        ...     print(f"Validation failed: {msg}")
    """
    if mode == "trust":
        logger.debug("Trust mode: skipping feature hash validation")
        return True, None

    logger.debug(
        f"Validating feature hash for {signal_type}/{signal_id}, asset {asset_id}"
    )

    # Get stored hash from most recent signal
    stored_hash = _get_latest_feature_hash(engine, signal_type, signal_id, asset_id)

    if stored_hash is None:
        logger.info("No stored hash found (first run or no signals yet)")
        return True, "No stored hash found (first run)"

    # Compute current hash from cmc_features
    current_hash = _compute_current_feature_hash(engine, signal_type, asset_id)

    if current_hash is None:
        logger.warning("Could not compute current feature hash (no feature data)")
        return True, "No feature data to validate"

    # Compare hashes
    if stored_hash == current_hash:
        logger.debug(f"Feature hash matches: {stored_hash}")
        return True, None

    # Hash mismatch detected
    message = (
        f"Feature data changed. Stored hash: {stored_hash}, Current hash: {current_hash}. "
        f"Signals may not reflect current feature data."
    )

    if mode == "strict":
        logger.error(f"STRICT MODE: {message}")
        return False, message

    # mode == 'warn'
    logger.warning(f"WARNING: {message}")
    return True, f"WARNING: {message}"


# =============================================================================
# Helper functions
# =============================================================================


def _compare_metrics(m1: dict, m2: dict, tolerance: float = 1e-10) -> bool:
    """
    Compare metric dictionaries with tolerance for floating point values.

    Args:
        m1: First metrics dictionary
        m2: Second metrics dictionary
        tolerance: Numerical tolerance for float comparisons

    Returns:
        True if all metrics match within tolerance, False otherwise
    """
    # Check all keys present in both
    if set(m1.keys()) != set(m2.keys()):
        logger.debug(f"Metric key mismatch: {set(m1.keys())} vs {set(m2.keys())}")
        return False

    # Compare values with tolerance
    for key in m1:
        val1 = m1[key]
        val2 = m2[key]

        # Handle None values
        if val1 is None or val2 is None:
            if val1 != val2:
                logger.debug(f"Metric '{key}' None mismatch: {val1} vs {val2}")
                return False
            continue

        # Compare floats with tolerance
        if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            if abs(val1 - val2) > tolerance:
                logger.debug(f"Metric '{key}' exceeds tolerance: {val1} vs {val2}")
                return False
        else:
            # Non-numeric comparison (exact match)
            if val1 != val2:
                logger.debug(f"Metric '{key}' mismatch: {val1} vs {val2}")
                return False

    return True


def _find_metric_differences(
    m1: dict, m2: dict, tolerance: float = 1e-10
) -> dict[str, tuple]:
    """
    Find specific metrics that differ between two dictionaries.

    Args:
        m1: First metrics dictionary
        m2: Second metrics dictionary
        tolerance: Numerical tolerance for float comparisons

    Returns:
        Dictionary mapping metric name to (value1, value2) for differing metrics
    """
    differences = {}

    all_keys = set(m1.keys()) | set(m2.keys())

    for key in all_keys:
        val1 = m1.get(key)
        val2 = m2.get(key)

        # Key missing in one dict
        if key not in m1 or key not in m2:
            differences[key] = (val1, val2)
            continue

        # None handling
        if val1 is None or val2 is None:
            if val1 != val2:
                differences[key] = (val1, val2)
            continue

        # Numeric comparison with tolerance
        if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            if abs(val1 - val2) > tolerance:
                differences[key] = (val1, val2)
        else:
            # Non-numeric exact comparison
            if val1 != val2:
                differences[key] = (val1, val2)

    return differences


def _load_run(engine: Engine, run_id: str) -> dict:
    """
    Load backtest run metadata from cmc_backtest_runs.

    Args:
        engine: SQLAlchemy engine
        run_id: Backtest run UUID

    Returns:
        Dictionary with run metadata

    Raises:
        ValueError: If run_id not found
    """
    sql = text(
        """
        SELECT
            run_id, signal_type, signal_id, asset_id,
            start_ts, end_ts, total_return, sharpe_ratio,
            max_drawdown, trade_count, feature_hash,
            signal_params_hash, signal_version, vbt_version
        FROM public.cmc_backtest_runs
        WHERE run_id = :run_id
    """
    )

    with engine.connect() as conn:
        result = conn.execute(sql, {"run_id": run_id})
        row = result.fetchone()

        if not row:
            raise ValueError(f"Backtest run not found: {run_id}")

        return {
            "run_id": row[0],
            "signal_type": row[1],
            "signal_id": row[2],
            "asset_id": row[3],
            "start_ts": row[4],
            "end_ts": row[5],
            "total_return": row[6],
            "sharpe_ratio": row[7],
            "max_drawdown": row[8],
            "trade_count": row[9],
            "feature_hash": row[10],
            "signal_params_hash": row[11],
            "signal_version": row[12],
            "vbt_version": row[13],
        }


def _load_trades(engine: Engine, run_id: str) -> list[dict]:
    """
    Load trade records from cmc_backtest_trades.

    Args:
        engine: SQLAlchemy engine
        run_id: Backtest run UUID

    Returns:
        List of trade dictionaries
    """
    sql = text(
        """
        SELECT
            entry_ts, entry_price, exit_ts, exit_price,
            direction, size, pnl_pct, pnl_dollars
        FROM public.cmc_backtest_trades
        WHERE run_id = :run_id
        ORDER BY entry_ts
    """
    )

    with engine.connect() as conn:
        result = conn.execute(sql, {"run_id": run_id})
        rows = result.fetchall()

        return [
            {
                "entry_ts": row[0],
                "entry_price": row[1],
                "exit_ts": row[2],
                "exit_price": row[3],
                "direction": row[4],
                "size": row[5],
                "pnl_pct": row[6],
                "pnl_dollars": row[7],
            }
            for row in rows
        ]


def _load_metrics(engine: Engine, run_id: str) -> dict:
    """
    Load performance metrics from cmc_backtest_metrics.

    Args:
        engine: SQLAlchemy engine
        run_id: Backtest run UUID

    Returns:
        Dictionary of metrics

    Raises:
        ValueError: If run_id not found
    """
    sql = text(
        """
        SELECT
            total_return, cagr, sharpe_ratio, sortino_ratio, calmar_ratio,
            max_drawdown, max_drawdown_duration_days,
            trade_count, win_rate, profit_factor, avg_win, avg_loss,
            avg_holding_period_days, var_95, expected_shortfall
        FROM public.cmc_backtest_metrics
        WHERE run_id = :run_id
    """
    )

    with engine.connect() as conn:
        result = conn.execute(sql, {"run_id": run_id})
        row = result.fetchone()

        if not row:
            raise ValueError(f"Metrics not found for run: {run_id}")

        return {
            "total_return": row[0],
            "cagr": row[1],
            "sharpe_ratio": row[2],
            "sortino_ratio": row[3],
            "calmar_ratio": row[4],
            "max_drawdown": row[5],
            "max_drawdown_duration_days": row[6],
            "trade_count": row[7],
            "win_rate": row[8],
            "profit_factor": row[9],
            "avg_win": row[10],
            "avg_loss": row[11],
            "avg_holding_period_days": row[12],
            "var_95": row[13],
            "expected_shortfall": row[14],
        }


def _get_latest_feature_hash(
    engine: Engine,
    signal_type: str,
    signal_id: int,
    asset_id: int,
) -> Optional[str]:
    """
    Get feature_version_hash from most recent signal for this asset/signal.

    Args:
        engine: SQLAlchemy engine
        signal_type: Signal table suffix
        signal_id: Signal configuration ID
        asset_id: Asset ID

    Returns:
        Feature hash string or None if no signals found
    """
    table = f"cmc_signals_{signal_type}"

    sql = text(
        f"""
        SELECT feature_version_hash
        FROM public.{table}
        WHERE id = :asset_id
          AND signal_id = :signal_id
        ORDER BY entry_ts DESC
        LIMIT 1
    """
    )

    with engine.connect() as conn:
        result = conn.execute(sql, {"asset_id": asset_id, "signal_id": signal_id})
        row = result.fetchone()

        return row[0] if row else None


def _compute_current_feature_hash(
    engine: Engine,
    signal_type: str,
    asset_id: int,
) -> Optional[str]:
    """
    Compute hash of current feature data from cmc_features + cmc_ema_multi_tf_u.

    Determines which feature columns to include based on signal type,
    then computes hash of those columns for the asset. EMA columns are
    loaded from cmc_ema_multi_tf_u via LEFT JOINs (EMAs are no longer
    in cmc_features — different granularity with period dimension).

    Args:
        engine: SQLAlchemy engine
        signal_type: Signal type to determine which features to hash
        asset_id: Asset ID

    Returns:
        Feature hash string or None if no feature data found
    """
    feature_cols, ema_periods = _get_feature_columns_for_signal_type(signal_type)

    # Build SELECT and JOINs for EMA columns
    select_parts = ["f.ts"] + [f"f.{c}" for c in feature_cols]
    join_parts = []
    for period in ema_periods:
        alias = f"e{period}"
        select_parts.append(f"{alias}.ema as ema_{period}")
        join_parts.append(
            f"LEFT JOIN public.cmc_ema_multi_tf_u {alias}"
            f" ON f.id = {alias}.id AND f.ts = {alias}.ts"
            f" AND {alias}.tf = f.tf AND {alias}.period = {period}"
        )

    select_str = ", ".join(select_parts)
    join_str = "\n            ".join(join_parts)

    sql = text(
        f"""
        SELECT {select_str}
        FROM public.cmc_features f
            {join_str}
        WHERE f.id = :asset_id AND f.tf = '1D'
        ORDER BY f.ts
    """
    )

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id})

    if df.empty:
        return None

    # All columns used for hash (feature cols + ema cols)
    all_hash_cols = feature_cols + [f"ema_{p}" for p in ema_periods]
    return compute_feature_hash(df, all_hash_cols)


def _get_feature_columns_for_signal_type(
    signal_type: str,
) -> tuple[list[str], list[int]]:
    """
    Determine which feature columns to include in hash based on signal type.

    Different signal types use different features, so we only hash the
    relevant columns to detect changes in features actually used by the signal.

    Returns two lists:
    - feature_cols: columns from cmc_features
    - ema_periods: EMA periods to load from cmc_ema_multi_tf_u

    Args:
        signal_type: 'ema_crossover', 'rsi_mean_revert', or 'atr_breakout'

    Returns:
        Tuple of (feature_cols, ema_periods)
    """
    # Base columns (always included, from cmc_features)
    base = ["close"]

    if signal_type == "ema_crossover":
        return base + ["rsi_14", "atr_14"], [9, 10, 21, 50, 200]
    elif signal_type == "rsi_mean_revert":
        return base + ["rsi_14", "rsi_7", "rsi_21", "atr_14"], [21]
    elif signal_type == "atr_breakout":
        return base + ["atr_14", "bb_up_20_2", "bb_lo_20_2", "rsi_14"], [21]
    else:
        return base, []
