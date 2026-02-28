"""Expression engine for Qlib-style $col factor definitions.

Parses and evaluates config-driven factor expressions using a registry of
financial operators (EMA, Ref, Delta, Mean, Std, WMA, Rank, etc.) against
a pandas DataFrame. No Python code changes are required per experiment --
expressions are defined entirely in YAML.

Public API
----------
OPERATOR_REGISTRY : dict
    Mapping of operator name -> callable for use in evaluate_expression().
evaluate_expression(expression, df) -> pd.Series
    Evaluate a $col-syntax expression against a DataFrame.
validate_expression(expression, allowed_columns) -> None
    Validate expression syntax and optionally check column allowlist.

Example
-------
    >>> import pandas as pd
    >>> from ta_lab2.ml.expression_engine import evaluate_expression
    >>> df = pd.DataFrame({'close': [100.0, 102.0, 101.0, 103.0, 105.0]})
    >>> result = evaluate_expression("EMA($close, 3) / Ref($close, 1) - 1", df)
    >>> assert len(result) == 5
"""

from __future__ import annotations

import ast
import re
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Operator implementations
# ---------------------------------------------------------------------------


def _wma(series: pd.Series, n: int) -> pd.Series:
    """Weighted moving average: weights are 1, 2, ..., n (linear)."""
    n = int(n)
    weights = np.arange(1, n + 1, dtype=float)

    def _apply_wma(window: np.ndarray) -> float:
        if len(window) < n:
            valid = weights[-len(window) :]
            return float(np.dot(window, valid) / valid.sum())
        return float(np.dot(window, weights) / weights.sum())

    return series.rolling(window=n, min_periods=1).apply(_apply_wma, raw=True)


def _slope(series: pd.Series, n: int) -> pd.Series:
    """Linear regression slope over rolling window of n bars."""
    n = int(n)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_denom = ((x - x_mean) ** 2).sum()

    def _apply_slope(window: np.ndarray) -> float:
        if len(window) < n:
            xi = np.arange(len(window), dtype=float)
            xi_mean = xi.mean()
            xi_denom = ((xi - xi_mean) ** 2).sum()
            if xi_denom == 0:
                return float("nan")
            return float(np.dot(window - window.mean(), xi - xi_mean) / xi_denom)
        y_mean = window.mean()
        return float(np.dot(window - y_mean, x - x_mean) / x_denom)

    return series.rolling(window=n, min_periods=2).apply(_apply_slope, raw=True)


# ---------------------------------------------------------------------------
# OPERATOR_REGISTRY: 16 operators mapped to callables
# ---------------------------------------------------------------------------

OPERATOR_REGISTRY: dict[str, Any] = {
    # Exponential moving average (EWM span-based)
    "EMA": lambda series, n: series.ewm(span=int(n), adjust=False).mean(),
    # Lag (shift) by n bars
    "Ref": lambda series, n: series.shift(int(n)),
    # Difference from n bars ago
    "Delta": lambda series, n: series - series.shift(int(n)),
    # Simple rolling mean
    "Mean": lambda series, n: series.rolling(int(n), min_periods=1).mean(),
    # Rolling standard deviation
    "Std": lambda series, n: series.rolling(int(n), min_periods=1).std(),
    # Weighted moving average (linear weights)
    "WMA": _wma,
    # Rolling maximum
    "Max": lambda series, n: series.rolling(int(n), min_periods=1).max(),
    # Rolling minimum
    "Min": lambda series, n: series.rolling(int(n), min_periods=1).min(),
    # Percentile rank (cross-sectional)
    "Rank": lambda series: series.rank(pct=True),
    # Absolute value
    "Abs": lambda series: series.abs(),
    # Sign (-1, 0, +1)
    "Sign": lambda series: np.sign(series),
    # Natural log (clipped to avoid log(0))
    "Log": lambda series: np.log(series.clip(lower=1e-10)),
    # Rolling Pearson correlation between two series
    "Corr": lambda series1, series2, n: series1.rolling(int(n)).corr(series2),
    # Linear regression slope over rolling window
    "Slope": _slope,
    # Rolling skewness
    "Skew": lambda series, n: series.rolling(int(n)).skew(),
    # Rolling excess kurtosis
    "Kurt": lambda series, n: series.rolling(int(n)).kurt(),
}


# ---------------------------------------------------------------------------
# Expression parsing helpers
# ---------------------------------------------------------------------------

_COL_PATTERN = re.compile(r"\$(\w+)")


def _replace_col_references(expression: str, template: str) -> str:
    """Replace $col references in expression using the given template.

    Parameters
    ----------
    expression:
        Expression string containing $col references.
    template:
        Python format string with one placeholder ``{col}``.
        e.g. ``"_df_['{col}']"`` or ``"_placeholder_"``

    Returns
    -------
    Substituted expression string.
    """
    return _COL_PATTERN.sub(lambda m: template.format(col=m.group(1)), expression)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_expression(
    expression: str,
    allowed_columns: list[str] | None = None,
) -> None:
    """Validate an expression string at load time.

    Replaces ``$col`` references with a safe placeholder, then checks
    syntax with ``ast.parse``. Optionally validates that all column
    references appear in ``allowed_columns``.

    Parameters
    ----------
    expression:
        Factor expression string, e.g. ``"EMA($close, 12) / EMA($close, 26) - 1"``.
    allowed_columns:
        If provided, every ``$col`` reference must be in this list.

    Raises
    ------
    ValueError
        If the expression has a syntax error, or if a column reference is
        not in ``allowed_columns`` when the allowlist is specified.
    """
    # Check column allowlist before syntax check
    if allowed_columns is not None:
        referenced = _COL_PATTERN.findall(expression)
        disallowed = [c for c in referenced if c not in allowed_columns]
        if disallowed:
            raise ValueError(
                f"Expression references disallowed column(s): {disallowed!r}. "
                f"Allowed: {sorted(allowed_columns)}"
            )

    # Replace $col with a valid Python identifier for syntax check
    parsed = _replace_col_references(expression, "_placeholder_")
    try:
        ast.parse(parsed, mode="eval")
    except SyntaxError as exc:
        raise ValueError(
            f"Invalid expression syntax: {exc}\n  Expression: {expression!r}"
        ) from exc


def evaluate_expression(expression: str, df: pd.DataFrame) -> pd.Series:
    """Evaluate a $col-syntax expression against a DataFrame.

    Replaces ``$col`` references with ``_df_['col']`` lookups, then
    evaluates the expression with a restricted set of globals (no
    builtins, only numpy/pandas and OPERATOR_REGISTRY).

    Parameters
    ----------
    expression:
        Factor expression string, e.g. ``"EMA($close, 3) / Ref($close, 1) - 1"``.
    df:
        DataFrame whose columns are the available data sources.
        Column names must match the ``$col`` references in the expression.

    Returns
    -------
    pd.Series
        Computed factor values, same length as ``df``.

    Raises
    ------
    ValueError
        If evaluation fails (missing column, type error, etc.) with a
        descriptive error message.
    """
    # Replace $col -> _df_['col']
    parsed = _replace_col_references(expression, "_df_['{col}']")

    # Restricted globals: no builtins, only safe numeric libraries + operators
    safe_globals: dict[str, Any] = {
        "__builtins__": {},
        "np": np,
        "pd": pd,
    }
    safe_globals.update(OPERATOR_REGISTRY)

    # Local vars: DataFrame reference + all columns by name for convenience
    local_vars: dict[str, Any] = {"_df_": df}
    local_vars.update({col: df[col] for col in df.columns})

    try:
        result = eval(parsed, safe_globals, local_vars)  # noqa: S307
    except Exception as exc:
        raise ValueError(
            f"Expression evaluation failed: {exc}\n"
            f"  Expression: {expression!r}\n"
            f"  Parsed as:  {parsed!r}\n"
            f"  Available columns: {list(df.columns)}"
        ) from exc

    # Coerce to pd.Series if needed
    if isinstance(result, pd.Series):
        return result.reset_index(drop=True)
    return pd.Series(result, index=df.index)
