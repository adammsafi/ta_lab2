"""
Composite scoring and sensitivity analysis for strategy bake-off.

Normalizes OOS metrics from strategy_bakeoff_results and ranks strategies
under multiple weighting schemes to ensure selection robustness. Includes V1
hard gates, turnover incorporation, and sensitivity analysis across 4 schemes.

Exports
-------
WEIGHT_SCHEMES         - 4 weighting scheme definitions (balanced, risk_focus,
                         quality_focus, low_cost)
V1_GATES               - Hard gate thresholds: min_sharpe=1.0, max_drawdown_pct=15.0
compute_composite_score - Min-max normalize + weighted blend
apply_v1_gates         - Flag strategies that fail hard gates
rank_strategies        - Score + sort + add rank column
sensitivity_analysis   - Rank under all 4 schemes, compute robustness
blend_signals          - Majority-vote ensemble from position series
load_bakeoff_metrics   - Load OOS metrics from strategy_bakeoff_results
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Four weighting schemes for sensitivity analysis.
#: Each scheme is a dict of {metric: weight} where weights sum to 1.0.
#: Metrics: sharpe_mean (higher=better), max_drawdown_worst (higher=worse,
#: normalized inverted), psr (higher=better), turnover (higher=worse,
#: normalized inverted).
WEIGHT_SCHEMES: Dict[str, Dict[str, float]] = {
    "balanced": {
        "sharpe_mean": 0.30,
        "max_drawdown_worst": 0.30,
        "psr": 0.25,
        "turnover": 0.15,
    },
    "risk_focus": {
        "sharpe_mean": 0.20,
        "max_drawdown_worst": 0.45,
        "psr": 0.25,
        "turnover": 0.10,
    },
    "quality_focus": {
        "sharpe_mean": 0.35,
        "max_drawdown_worst": 0.20,
        "psr": 0.35,
        "turnover": 0.10,
    },
    "low_cost": {
        "sharpe_mean": 0.30,
        "max_drawdown_worst": 0.25,
        "psr": 0.20,
        "turnover": 0.25,
    },
}

#: V1 hard gates. Strategies failing either gate are flagged (not eliminated).
#: Thresholds apply to OOS purged_kfold results under baseline cost scenario.
V1_GATES: Dict[str, float] = {
    "min_sharpe": 1.0,  # Minimum OOS Sharpe (annualized)
    "max_drawdown_pct": 15.0,  # Maximum allowed drawdown as a positive percentage
}

# Default baseline cost scenario for primary analysis
_DEFAULT_COST_SCENARIO = "spot_maker_10bps"
_FALLBACK_COST_SCENARIOS = [
    "spot_fee16_slip10",  # Kraken spot maker 16bps + 10bps slippage
    "spot_fee16_slip5",  # Kraken spot maker 16bps + 5bps slippage
    "spot_fee26_slip10",  # Kraken spot taker 26bps + 10bps slippage
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_composite_score(
    metrics_df: pd.DataFrame,
    weights: Dict[str, float],
) -> pd.DataFrame:
    """
    Min-max normalize OOS metrics and compute a weighted composite score.

    Normalization direction:
    - sharpe_mean: higher=better (normalize ascending)
    - max_drawdown_worst: more negative=worse (normalize descending;
      less negative draws score closer to 1.0)
    - psr: higher=better (normalize ascending; NaN replaced with 0.0)
    - turnover: higher=worse (normalize descending; lower turnover=higher score)

    Edge case: if only one strategy (all metrics identical), all norms=0.5
    so the composite score is neutral.

    Parameters
    ----------
    metrics_df : pd.DataFrame
        One row per strategy variant. Required columns:
        strategy_name, sharpe_mean, max_drawdown_worst, psr, turnover.
        Optional: strategy_label (used as display name if present).
    weights : dict
        {metric_name: weight} where weights should sum to 1.0.

    Returns
    -------
    pd.DataFrame
        Input df with added columns: norm_sharpe, norm_max_drawdown,
        norm_psr, norm_turnover, composite_score.
    """
    df = metrics_df.copy()

    # Handle NaN psr -> 0.0
    df["psr"] = df["psr"].fillna(0.0)

    # --- Min-max normalization helpers ---
    def _minmax_norm(series: pd.Series, invert: bool = False) -> pd.Series:
        """Normalize series to [0, 1]. Invert for metrics where lower=better."""
        s = series.astype(float)
        lo = s.min()
        hi = s.max()
        if hi == lo:
            # Single value or all identical -> neutral 0.5
            return pd.Series(0.5, index=s.index)
        norm = (s - lo) / (hi - lo)
        if invert:
            norm = 1.0 - norm
        return norm

    # sharpe_mean: higher=better
    df["norm_sharpe"] = _minmax_norm(df["sharpe_mean"], invert=False)

    # max_drawdown_worst: values are negative (e.g., -0.70 = -70%).
    # Less negative is better. We invert so that -0.10 scores near 1.0
    # and -0.70 scores near 0.0.
    df["norm_max_drawdown"] = _minmax_norm(df["max_drawdown_worst"], invert=True)

    # psr: higher=better
    df["norm_psr"] = _minmax_norm(df["psr"], invert=False)

    # turnover: lower=better (invert so low turnover = high score)
    df["norm_turnover"] = _minmax_norm(df["turnover"], invert=True)

    # --- Weighted composite score ---
    norm_col_map = {
        "sharpe_mean": "norm_sharpe",
        "max_drawdown_worst": "norm_max_drawdown",
        "psr": "norm_psr",
        "turnover": "norm_turnover",
    }

    score = pd.Series(0.0, index=df.index)
    for metric, weight in weights.items():
        if metric in norm_col_map:
            score += weight * df[norm_col_map[metric]]

    df["composite_score"] = score
    return df


def apply_v1_gates(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply V1 hard gates to each strategy and add gate columns.

    Parameters
    ----------
    metrics_df : pd.DataFrame
        One row per strategy. Requires sharpe_mean and max_drawdown_worst.

    Returns
    -------
    pd.DataFrame
        Input df with two added columns:
        - passes_v1_gates (bool): True if both gates pass
        - gate_failures (list[str]): list of gate names that failed
    """
    df = metrics_df.copy()

    gate_failures: List[List[str]] = []
    for _, row in df.iterrows():
        failures: List[str] = []
        # Sharpe gate
        sharpe = row.get("sharpe_mean", float("nan"))
        if pd.isna(sharpe) or sharpe < V1_GATES["min_sharpe"]:
            failures.append(
                f"sharpe<{V1_GATES['min_sharpe']:.1f} (got {sharpe:.3f})"
                if not pd.isna(sharpe)
                else "sharpe=NaN"
            )
        # Drawdown gate: max_drawdown_worst is negative, e.g. -0.15 = -15%
        dd = row.get("max_drawdown_worst", float("nan"))
        if not pd.isna(dd):
            dd_pct = abs(dd) * 100.0
            if dd_pct > V1_GATES["max_drawdown_pct"]:
                failures.append(
                    f"dd>{V1_GATES['max_drawdown_pct']:.0f}% (got {dd_pct:.1f}%)"
                )
        else:
            failures.append("max_drawdown=NaN")
        gate_failures.append(failures)

    df["gate_failures"] = gate_failures
    df["passes_v1_gates"] = df["gate_failures"].apply(lambda x: len(x) == 0)
    return df


def rank_strategies(
    metrics_df: pd.DataFrame,
    weights: Dict[str, float],
) -> pd.DataFrame:
    """
    Compute composite score and rank strategies.

    Parameters
    ----------
    metrics_df : pd.DataFrame
        OOS metrics from load_bakeoff_metrics or manual construction.
    weights : dict
        Weighting scheme dict (see WEIGHT_SCHEMES).

    Returns
    -------
    pd.DataFrame
        Scored df sorted by composite_score descending, with rank column (1=best).
    """
    df = compute_composite_score(metrics_df, weights)
    df = apply_v1_gates(df)
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df


def sensitivity_analysis(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """
    Rank strategies under all 4 weighting schemes and measure robustness.

    For each strategy, computes its rank under each of the 4 weight schemes.
    A strategy is "robust" if it ranks in the top 2 under at least 3 of 4 schemes.

    Parameters
    ----------
    metrics_df : pd.DataFrame
        OOS metrics df. See compute_composite_score for required columns.

    Returns
    -------
    pd.DataFrame
        One row per strategy with columns:
        - strategy_label or strategy_name (identifier)
        - rank_balanced, rank_risk_focus, rank_quality_focus, rank_low_cost
        - composite_balanced, composite_risk_focus, composite_quality_focus,
          composite_low_cost
        - n_times_top2 (int): count of schemes where rank <= 2
        - robust (bool): True if n_times_top2 >= 3
        - passes_v1_gates (bool)
        - gate_failures (list)
    """
    if metrics_df.empty:
        return pd.DataFrame()

    # Determine label column
    label_col = (
        "strategy_label" if "strategy_label" in metrics_df.columns else "strategy_name"
    )

    # Apply gates once (same for all schemes)
    gated_df = apply_v1_gates(metrics_df)

    rows: List[Dict[str, Any]] = []
    for _, strategy_row in gated_df.iterrows():
        label = strategy_row[label_col]
        row: Dict[str, Any] = {
            label_col: label,
            "passes_v1_gates": strategy_row["passes_v1_gates"],
            "gate_failures": strategy_row["gate_failures"],
        }
        rows.append(row)

    result_df = pd.DataFrame(rows)

    n_times_top2 = pd.Series(0, index=result_df.index, dtype=int)

    for scheme_name, weights in WEIGHT_SCHEMES.items():
        ranked = rank_strategies(metrics_df, weights)

        # Build mapping: label -> rank
        rank_map = {}
        score_map = {}
        for _, r in ranked.iterrows():
            lbl = r[label_col]
            rank_map[lbl] = int(r["rank"])
            score_map[lbl] = float(r["composite_score"])

        result_df[f"rank_{scheme_name}"] = result_df[label_col].map(rank_map)
        result_df[f"composite_{scheme_name}"] = result_df[label_col].map(score_map)

        # Count top-2 occurrences
        is_top2 = result_df[f"rank_{scheme_name}"] <= 2
        n_times_top2 = n_times_top2 + is_top2.astype(int)

    result_df["n_times_top2"] = n_times_top2
    result_df["robust"] = result_df["n_times_top2"] >= 3

    # Sort by average rank across schemes
    rank_cols = [f"rank_{s}" for s in WEIGHT_SCHEMES]
    result_df["avg_rank"] = result_df[rank_cols].mean(axis=1)
    result_df = result_df.sort_values("avg_rank").reset_index(drop=True)

    return result_df


def blend_signals(
    position_series_list: Sequence[pd.Series],
    weights: Optional[Sequence[float]] = None,
) -> pd.Series:
    """
    Majority-vote ensemble from position series (simple signal blending).

    Each series contains values in {-1, 0, 1} or continuous weights.
    The blended signal is np.sign of the weighted sum, producing {-1, 0, 1}.

    Parameters
    ----------
    position_series_list : sequence of pd.Series
        Each series has the same DatetimeIndex and values in {-1, 0, 1}.
    weights : sequence of float, optional
        Per-series weights. If None, equal weighting is applied.

    Returns
    -------
    pd.Series
        Blended signal in {-1, 0, 1} with same index as first input series.
    """
    if not position_series_list:
        raise ValueError("position_series_list must not be empty")

    n = len(position_series_list)
    if weights is None:
        weights = [1.0 / n] * n

    if len(weights) != n:
        raise ValueError(
            f"len(weights)={len(weights)} != len(position_series_list)={n}"
        )

    reference_index = position_series_list[0].index
    weighted_sum = pd.Series(0.0, index=reference_index)
    for series, w in zip(position_series_list, weights):
        weighted_sum += w * series.reindex(reference_index, fill_value=0.0)

    return np.sign(weighted_sum).astype(int)


def load_bakeoff_metrics(
    engine: Engine,
    asset_id: int,
    tf: str,
    cv_method: str = "purged_kfold",
    cost_scenario: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load OOS metrics from strategy_bakeoff_results for composite scoring.

    When cost_scenario is None, selects the best available baseline scenario
    from _FALLBACK_COST_SCENARIOS (tries each in order, uses first that exists).
    When --all-scenarios is desired, pass cost_scenario='__all__' to get
    all cost scenarios (one row per strategy x scenario combination).

    For each (strategy_name, params_json) combination, returns one row
    with the best sharpe_mean across matched rows (or the specific
    cost_scenario row when explicitly provided).

    Parameters
    ----------
    engine : Engine
        SQLAlchemy engine.
    asset_id : int
        Asset to load (e.g., 1 for BTC).
    tf : str
        Timeframe (e.g., "1D").
    cv_method : str
        "purged_kfold" or "cpcv". Default "purged_kfold".
    cost_scenario : str or None
        Specific cost scenario label, or None to auto-select baseline,
        or '__all__' to return all scenarios.

    Returns
    -------
    pd.DataFrame
        Columns: strategy_name, strategy_label, cost_scenario, cv_method,
        sharpe_mean, sharpe_std, max_drawdown_mean, max_drawdown_worst,
        total_return_mean, cagr_mean, trade_count_total, turnover, psr, dsr,
        psr_n_obs, pbo_prob.
        Indexed 0..N-1.
    """
    # --- Resolve cost scenario ---
    if cost_scenario is None:
        cost_scenario = _resolve_baseline_scenario(engine, asset_id, tf, cv_method)

    # --- Build SQL ---
    if cost_scenario == "__all__":
        sql = text(
            """
            SELECT
                strategy_name,
                asset_id,
                tf,
                cost_scenario,
                cv_method,
                params_json::text AS params_str,
                sharpe_mean,
                sharpe_std,
                max_drawdown_mean,
                max_drawdown_worst,
                total_return_mean,
                cagr_mean,
                trade_count_total,
                turnover,
                psr,
                dsr,
                psr_n_obs,
                pbo_prob
            FROM public.strategy_bakeoff_results
            WHERE asset_id = :asset_id
              AND tf = :tf
              AND cv_method = :cv_method
            ORDER BY strategy_name, cost_scenario, sharpe_mean DESC
            """
        )
        params: Dict[str, Any] = {
            "asset_id": asset_id,
            "tf": tf,
            "cv_method": cv_method,
        }
    else:
        sql = text(
            """
            SELECT
                strategy_name,
                asset_id,
                tf,
                cost_scenario,
                cv_method,
                params_json::text AS params_str,
                sharpe_mean,
                sharpe_std,
                max_drawdown_mean,
                max_drawdown_worst,
                total_return_mean,
                cagr_mean,
                trade_count_total,
                turnover,
                psr,
                dsr,
                psr_n_obs,
                pbo_prob
            FROM public.strategy_bakeoff_results
            WHERE asset_id = :asset_id
              AND tf = :tf
              AND cv_method = :cv_method
              AND cost_scenario = :cost_scenario
            ORDER BY strategy_name, sharpe_mean DESC
            """
        )
        params = {
            "asset_id": asset_id,
            "tf": tf,
            "cv_method": cv_method,
            "cost_scenario": cost_scenario,
        }

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        logger.warning(
            f"No bakeoff results found for asset_id={asset_id}, tf={tf}, "
            f"cv_method={cv_method}, cost_scenario={cost_scenario}"
        )
        return df

    # --- Create strategy_label for display ---
    # e.g. "ema_trend(fast=10,slow=50) @ spot_fee16_slip10"
    df["strategy_label"] = df.apply(
        lambda r: f"{r['strategy_name']}({r['params_str']}) @ {r['cost_scenario']}",
        axis=1,
    )

    logger.info(
        f"Loaded {len(df)} bakeoff rows for asset_id={asset_id}, tf={tf}, "
        f"cv_method={cv_method}"
    )
    return df


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_baseline_scenario(
    engine: Engine,
    asset_id: int,
    tf: str,
    cv_method: str,
) -> str:
    """Try fallback cost scenarios in order and return the first that has data."""
    sql = text(
        """
        SELECT DISTINCT cost_scenario
        FROM public.strategy_bakeoff_results
        WHERE asset_id = :asset_id
          AND tf = :tf
          AND cv_method = :cv_method
        ORDER BY cost_scenario
        """
    )
    with engine.connect() as conn:
        result = conn.execute(
            sql, {"asset_id": asset_id, "tf": tf, "cv_method": cv_method}
        )
        available = {row[0] for row in result.fetchall()}

    # First check the named default
    if _DEFAULT_COST_SCENARIO in available:
        return _DEFAULT_COST_SCENARIO

    # Try fallbacks in order
    for scenario in _FALLBACK_COST_SCENARIOS:
        if scenario in available:
            logger.info(
                f"Baseline scenario '{_DEFAULT_COST_SCENARIO}' not found; "
                f"using '{scenario}'"
            )
            return scenario

    # Last resort: first available alphabetically
    if available:
        chosen = sorted(available)[0]
        logger.warning(
            f"No preferred baseline scenario found; using '{chosen}' "
            f"from available: {sorted(available)}"
        )
        return chosen

    raise ValueError(
        f"No bakeoff results found for asset_id={asset_id}, tf={tf}, "
        f"cv_method={cv_method}"
    )
