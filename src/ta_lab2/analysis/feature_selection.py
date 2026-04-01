# -*- coding: utf-8 -*-
"""
Feature selection library for Phase 80 IC Analysis.

Provides statistical test functions (stationarity, Ljung-Box autocorrelation,
quintile monotonicity), tier classification logic, config builder, and I/O
helpers for persisting the feature selection config to DB and YAML.

All public functions operate on pandas Series or DataFrames. The statistical
tests are designed to be run on IC series (not raw feature values), except for
stationarity which is run on the feature value series itself.

Public API:
    test_stationarity         -- ADF + KPSS stationarity classification
    test_ljungbox_on_ic       -- Ljung-Box autocorrelation flag on rolling IC series
    compute_monotonicity_score -- Spearman Q1-Q5 terminal return correlation
    load_ic_ranking           -- IC ranking DataFrame from ic_results
    load_regime_ic            -- Per-regime IC-IR for a single feature
    classify_feature_tier     -- Tier assignment: active/conditional/watch/archive
    build_feature_selection_config -- Full config dict from IC + test results
    save_to_db                -- Persist config to dim_feature_selection
    save_to_yaml              -- Write config to YAML file

Internal helpers (exported for testing):
    _to_python                -- Normalize values for SQL binding
"""

from __future__ import annotations

import logging
import math
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import yaml
from scipy.stats import spearmanr
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _to_python(v):
    """
    Normalize a value for SQL binding.

    - numpy scalars -> Python float/int via .item()
    - pd.Timestamp -> Python datetime
    - NaN float -> None (SQL NULL)
    - Everything else: unchanged
    """
    if hasattr(v, "item"):
        # numpy scalar (float32, float64, int32, int64, bool_, etc.)
        v = v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


# ---------------------------------------------------------------------------
# Statistical test functions
# ---------------------------------------------------------------------------


def test_stationarity(series: pd.Series, alpha: float = 0.05) -> dict:
    """
    Run ADF + KPSS stationarity tests on a feature series.

    CRITICAL: ADF and KPSS use OPPOSING null hypotheses:
    - ADF null = unit root (non-stationary). Low p-value -> REJECT null -> STATIONARY.
    - KPSS null = stationary. Low p-value -> REJECT null -> NON_STATIONARY.

    When both agree, the classification is unambiguous. When they disagree
    (one says stationary, other says non-stationary), result is AMBIGUOUS.

    Parameters
    ----------
    series : pd.Series
        Feature values. NaN values are dropped before testing.
    alpha : float
        Significance level for both tests. Default 0.05.

    Returns
    -------
    dict
        Keys:
        - adf_stat (float): ADF test statistic
        - adf_pvalue (float): ADF p-value
        - kpss_stat (float): KPSS test statistic
        - kpss_pvalue (float): KPSS p-value
        - result (str): One of 'STATIONARY', 'NON_STATIONARY', 'AMBIGUOUS',
          'INSUFFICIENT_DATA'
    """
    # Lazy import to keep startup fast and avoid missing-dep errors in contexts
    # where statsmodels is not installed
    from statsmodels.tsa.stattools import adfuller, kpss

    series_clean = series.dropna()

    if len(series_clean) < 30:
        logger.debug(
            "test_stationarity: insufficient data (%d non-NaN obs, need 30)",
            len(series_clean),
        )
        return {
            "adf_stat": float("nan"),
            "adf_pvalue": float("nan"),
            "kpss_stat": float("nan"),
            "kpss_pvalue": float("nan"),
            "result": "INSUFFICIENT_DATA",
        }

    # ADF test: H0 = unit root (non-stationary)
    adf_result = adfuller(series_clean.values, autolag="AIC")
    adf_stat = float(adf_result[0])
    adf_pvalue = float(adf_result[1])

    # KPSS test: H0 = stationary
    # Suppress InterpolationWarning when p-value is outside the table bounds
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        warnings.filterwarnings("ignore", message=".*InterpolationWarning.*")
        kpss_result = kpss(series_clean.values, regression="c", nlags="auto")
    kpss_stat = float(kpss_result[0])
    kpss_pvalue = float(kpss_result[1])

    # Interpret:
    # ADF: low p-value (< alpha) means REJECT H0 (unit root) -> evidence of stationarity
    # KPSS: low p-value (< alpha) means REJECT H0 (stationary) -> evidence of non-stationarity
    adf_says_stationary = adf_pvalue < alpha  # reject unit root null
    kpss_says_stationary = kpss_pvalue >= alpha  # fail to reject stationarity null

    if adf_says_stationary and kpss_says_stationary:
        result = "STATIONARY"
    elif not adf_says_stationary and not kpss_says_stationary:
        result = "NON_STATIONARY"
    else:
        result = "AMBIGUOUS"

    logger.debug(
        "test_stationarity: ADF p=%.4f, KPSS p=%.4f -> %s",
        adf_pvalue,
        kpss_pvalue,
        result,
    )

    return {
        "adf_stat": adf_stat,
        "adf_pvalue": adf_pvalue,
        "kpss_stat": kpss_stat,
        "kpss_pvalue": kpss_pvalue,
        "result": result,
    }


def test_ljungbox_on_ic(
    rolling_ic_series: pd.Series,
    lags: int = 10,
    alpha: float = 0.05,
) -> dict:
    """
    Ljung-Box autocorrelation test on a rolling IC series.

    Applied to the IC series (NOT the raw feature values). Significant
    autocorrelation in the IC series suggests the IC-IR may be inflated
    by serial correlation rather than genuine predictive power.

    Parameters
    ----------
    rolling_ic_series : pd.Series
        Rolling IC values, typically output of compute_rolling_ic().
    lags : int
        Number of lags to test. Default 10.
    alpha : float
        Significance level. Flag=True if any lag's p-value < alpha. Default 0.05.

    Returns
    -------
    dict
        Keys:
        - flag (bool): True if significant autocorrelation detected at any lag
        - min_pvalue (float or None): Minimum p-value across tested lags
        - n_obs (int): Number of non-NaN observations used
    """
    from statsmodels.stats.diagnostic import acorr_ljungbox

    clean = rolling_ic_series.dropna()
    n_obs = len(clean)

    if n_obs < lags + 1:
        logger.debug(
            "test_ljungbox_on_ic: insufficient data (%d obs, need %d for %d lags)",
            n_obs,
            lags + 1,
            lags,
        )
        return {"flag": False, "min_pvalue": None, "n_obs": n_obs}

    lb_result = acorr_ljungbox(clean.values, lags=lags, return_df=True)
    min_pvalue = float(lb_result["lb_pvalue"].min())
    flag = bool(min_pvalue < alpha)

    logger.debug(
        "test_ljungbox_on_ic: n_obs=%d, min_pvalue=%.4f, flag=%s",
        n_obs,
        min_pvalue,
        flag,
    )

    return {"flag": flag, "min_pvalue": min_pvalue, "n_obs": n_obs}


def compute_monotonicity_score(quintile_cumulative: pd.DataFrame) -> float:
    """
    Compute Spearman monotonicity score from quintile cumulative returns.

    Takes the terminal (last-row) cumulative return per quintile bucket and
    computes the Spearman rank correlation between quintile labels [1,2,3,4,5]
    and their terminal returns. A value near 1.0 (absolute) indicates that
    higher quintile labels consistently correspond to better (or worse) returns
    monotonically -- strong directional predictive power.

    Parameters
    ----------
    quintile_cumulative : pd.DataFrame
        Cumulative returns DataFrame with columns [1, 2, 3, 4, 5] (quintile labels)
        and timestamp index. Typically the first output of compute_quintile_returns().

    Returns
    -------
    float
        Absolute Spearman rho in [0, 1]. 0.0 if fewer than 2 rows.
    """
    if len(quintile_cumulative) < 1:
        logger.debug("compute_monotonicity_score: empty DataFrame — returning 0.0")
        return 0.0

    # Terminal cumulative return per quintile
    terminal = quintile_cumulative.iloc[-1]

    # Quintile labels must be present as columns
    labels = [1, 2, 3, 4, 5]
    try:
        terminal_values = [terminal[q] for q in labels]
    except KeyError:
        logger.warning(
            "compute_monotonicity_score: columns %s not found in DataFrame (has %s)",
            labels,
            list(quintile_cumulative.columns),
        )
        return 0.0

    result = spearmanr(labels, terminal_values)
    rho = float(result.statistic)

    # Return absolute value — both perfect positive and negative monotonicity
    # indicate predictive power (just in opposite directions)
    return abs(rho)


# ---------------------------------------------------------------------------
# DB query helpers
# ---------------------------------------------------------------------------


def load_ic_ranking(
    engine,
    horizon: int = 1,
    return_type: str = "arith",
) -> pd.DataFrame:
    """
    Load feature IC ranking from ic_results for the full-sample (regime='all') rows.

    Aggregates mean absolute IC-IR across all asset-TF pairs for the given
    horizon and return type. Used to identify candidate active/conditional features.

    Parameters
    ----------
    engine : SQLAlchemy engine
        Database engine.
    horizon : int
        Forward return horizon in bars. Default 1.
    return_type : str
        Return type filter: 'arith' or 'log'. Default 'arith'.

    Returns
    -------
    pd.DataFrame
        Columns: feature, mean_abs_ic, mean_abs_ic_ir, n_observations,
        n_asset_tf_pairs, pass_rate. Sorted by mean_abs_ic_ir descending.
        Empty DataFrame if ic_results has no matching rows.
    """
    sql = text(
        """
        SELECT feature,
               AVG(ABS(ic)) AS mean_abs_ic,
               AVG(ABS(ic_ir)) AS mean_abs_ic_ir,
               COUNT(*) AS n_observations,
               COUNT(DISTINCT asset_id::TEXT || '_' || tf) AS n_asset_tf_pairs,
               SUM(CASE WHEN ABS(ic_ir) > 0.3 THEN 1 ELSE 0 END)::FLOAT
                   / NULLIF(COUNT(*), 0) AS pass_rate
        FROM public.ic_results
        WHERE horizon = :horizon
          AND return_type = :return_type
          AND regime_col = 'all'
          AND regime_label = 'all'
          AND ic IS NOT NULL
        GROUP BY feature
        ORDER BY mean_abs_ic_ir DESC NULLS LAST
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={"horizon": horizon, "return_type": return_type},
        )

    logger.info(
        "load_ic_ranking: horizon=%d return_type=%s -> %d features",
        horizon,
        return_type,
        len(df),
    )
    return df


def load_regime_ic(
    engine,
    feature: str,
    horizon: int = 1,
    return_type: str = "arith",
) -> pd.DataFrame:
    """
    Load regime-specific IC-IR for a single feature from ic_results.

    Returns the aggregated mean absolute IC-IR per regime label for the
    feature, excluding the 'all' regime (which captures the full-sample IC).

    Parameters
    ----------
    engine : SQLAlchemy engine
        Database engine.
    feature : str
        Feature name (must match feature column in ic_results).
    horizon : int
        Forward return horizon. Default 1.
    return_type : str
        Return type filter. Default 'arith'.

    Returns
    -------
    pd.DataFrame
        Columns: regime_col, regime_label, mean_abs_ic_ir, n_obs.
        Sorted by mean_abs_ic_ir descending. Empty if no regime rows exist.
    """
    sql = text(
        """
        SELECT regime_col, regime_label,
               AVG(ABS(ic_ir)) AS mean_abs_ic_ir,
               COUNT(*) AS n_obs
        FROM public.ic_results
        WHERE feature = :feature
          AND horizon = :horizon
          AND return_type = :return_type
          AND regime_col != 'all'
          AND ic IS NOT NULL
        GROUP BY regime_col, regime_label
        ORDER BY mean_abs_ic_ir DESC
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "feature": feature,
                "horizon": horizon,
                "return_type": return_type,
            },
        )

    logger.debug(
        "load_regime_ic: feature=%s horizon=%d -> %d regime rows",
        feature,
        horizon,
        len(df),
    )
    return df


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------


def classify_feature_tier(
    ic_ir_mean: float,
    pass_rate: float,
    stationarity: str,
    regime_ic: Optional[pd.DataFrame] = None,
    perm_p_value: Optional[float] = None,
    ic_ir_cutoff: float = 0.3,
) -> str:
    """
    Classify a feature into one of four tiers based on IC-IR and test results.

    Tier hierarchy (evaluated in order):
    1. active     -- Strong universal signal, meets IC-IR cutoff
    2. conditional -- Regime specialist or borderline signal
    3. watch      -- Weak but non-trivial signal (IC-IR in 0.10-0.30 range)
    4. archive    -- No meaningful signal (IC-IR < 0.10)

    Stationarity acts as a soft gate per Phase 80 CONTEXT.md decisions:
    non-stationary features need stronger IC evidence (1.5x cutoff) to
    qualify as active. They are NOT auto-excluded.

    Permutation p-value gating (Phase 102 CONTEXT.md decisions):
    When perm_p_value is provided, it applies a downgrade gate AFTER the
    IC-IR tier is computed. The gate can only downgrade tiers, never upgrade.
    - perm_p_value >= 0.15: force tier to 'archive' (strong evidence of no signal)
    - perm_p_value in [0.05, 0.15): cap tier at 'watch' maximum (marginal evidence)
    - perm_p_value < 0.05: no additional constraint (passes permutation gate)
    - perm_p_value is None: existing logic unchanged (backward compatible)

    Parameters
    ----------
    ic_ir_mean : float
        Mean absolute IC-IR across observations.
    pass_rate : float
        Fraction of IC computations where |IC-IR| > 0.3.
    stationarity : str
        Stationarity classification: 'STATIONARY', 'NON_STATIONARY',
        'AMBIGUOUS', or 'INSUFFICIENT_DATA'.
    regime_ic : pd.DataFrame or None
        Regime-specific IC DataFrame from load_regime_ic(). Used to
        detect regime specialists. None treated as no regime data.
    perm_p_value : float or None
        Permutation test p-value. When provided, gates tier assignment by
        statistical evidence. None means permutation test has not been run
        for this feature (backward compatible — existing logic unchanged).
    ic_ir_cutoff : float
        Base IC-IR threshold for active tier. Default 0.3.

    Returns
    -------
    str
        One of: 'active', 'conditional', 'watch', 'archive'.
    """
    # Guard against NaN inputs
    if ic_ir_mean is None or (isinstance(ic_ir_mean, float) and math.isnan(ic_ir_mean)):
        ic_ir_mean = 0.0
    if pass_rate is None or (isinstance(pass_rate, float) and math.isnan(pass_rate)):
        pass_rate = 0.0

    # Determine effective cutoff — non-stationary features need stronger evidence
    if stationarity == "NON_STATIONARY":
        effective_cutoff = ic_ir_cutoff * 1.5
    else:
        effective_cutoff = ic_ir_cutoff

    # --- ACTIVE ---
    # Meets or exceeds the (possibly elevated) IC-IR cutoff AND has adequate pass_rate
    if ic_ir_mean >= effective_cutoff and pass_rate >= 0.30:
        tier = "active"

    # --- CONDITIONAL ---
    # Two paths to conditional:
    elif (
        # (a) Regime specialist: strong IC in at least one specific regime
        (
            regime_ic is not None
            and len(regime_ic) > 0
            and "mean_abs_ic_ir" in regime_ic.columns
            and float(regime_ic["mean_abs_ic_ir"].max()) >= ic_ir_cutoff
        )
        # (b) Borderline universal: IC-IR between 0.15 and cutoff with decent pass_rate
        or (0.15 <= ic_ir_mean < ic_ir_cutoff and pass_rate >= 0.20)
    ):
        tier = "conditional"

    # --- WATCH ---
    # Some signal but not strong enough for conditional
    elif ic_ir_mean >= 0.10:
        tier = "watch"

    # --- ARCHIVE ---
    else:
        tier = "archive"

    # --- PERMUTATION P-VALUE GATE ---
    # Applied after IC-IR classification. Can only downgrade tiers, never upgrade.
    if perm_p_value is not None:
        if perm_p_value >= 0.15:
            # Strong evidence of no signal — force to archive
            tier = "archive"
        elif perm_p_value >= 0.05:
            # Marginal evidence — cap at watch
            if tier in ("active", "conditional"):
                tier = "watch"
        # perm_p_value < 0.05: passes permutation gate, no constraint

    return tier


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------


def build_feature_selection_config(
    ranking_df: pd.DataFrame,
    stationarity_results: dict,
    ljungbox_results: dict,
    monotonicity_scores: dict,
    regime_ic_map: dict,
    ic_ir_cutoff: float = 0.3,
) -> dict:
    """
    Build the complete feature selection config dict from IC analysis results.

    Takes the per-feature test results and aggregates them into a nested dict
    suitable for YAML serialization and database storage. Each feature is
    assigned a tier and a human-readable rationale string.

    Parameters
    ----------
    ranking_df : pd.DataFrame
        IC ranking DataFrame from load_ic_ranking(). Must have columns:
        feature, mean_abs_ic, mean_abs_ic_ir, pass_rate.
    stationarity_results : dict[str, dict]
        Stationarity test dicts keyed by feature name. Each dict has keys:
        adf_stat, adf_pvalue, kpss_stat, kpss_pvalue, result.
    ljungbox_results : dict[str, dict]
        Ljung-Box test dicts keyed by feature name. Each dict has keys:
        flag, min_pvalue, n_obs.
    monotonicity_scores : dict[str, float]
        Spearman monotonicity scores keyed by feature name.
    regime_ic_map : dict[str, pd.DataFrame]
        Regime IC DataFrames keyed by feature name (from load_regime_ic()).
        May be empty dicts for features with no regime breakdown.
    ic_ir_cutoff : float
        IC-IR threshold for active tier. Default 0.3.

    Returns
    -------
    dict
        Nested config with keys: metadata, active, conditional, watch, archive.
        Each tier is a list of feature dicts with name, metrics, and rationale.
    """
    tiers: dict[str, list] = {
        "active": [],
        "conditional": [],
        "watch": [],
        "archive": [],
    }

    for _, row in ranking_df.iterrows():
        feature = str(row["feature"])
        ic_ir_mean = float(row.get("mean_abs_ic_ir") or 0.0)
        mean_abs_ic = float(row.get("mean_abs_ic") or 0.0)
        pass_rate = float(row.get("pass_rate") or 0.0)

        stat_result = stationarity_results.get(feature, {})
        stationarity = stat_result.get("result", "INSUFFICIENT_DATA")

        lb_result = ljungbox_results.get(feature, {})
        ljung_box_flag = bool(lb_result.get("flag", False))

        monotonicity = float(monotonicity_scores.get(feature) or 0.0)

        regime_ic = regime_ic_map.get(feature, pd.DataFrame())

        tier = classify_feature_tier(
            ic_ir_mean=ic_ir_mean,
            pass_rate=pass_rate,
            stationarity=stationarity,
            regime_ic=regime_ic if len(regime_ic) > 0 else None,
            ic_ir_cutoff=ic_ir_cutoff,
        )

        # Build rationale string
        rationale = _build_rationale(
            tier=tier,
            ic_ir_mean=ic_ir_mean,
            mean_abs_ic=mean_abs_ic,
            pass_rate=pass_rate,
            stationarity=stationarity,
            ljung_box_flag=ljung_box_flag,
            monotonicity=monotonicity,
            regime_ic=regime_ic,
            ic_ir_cutoff=ic_ir_cutoff,
        )

        feature_entry = {
            "name": feature,
            "ic_ir_mean": round(ic_ir_mean, 4),
            "mean_abs_ic": round(mean_abs_ic, 4),
            "pass_rate": round(pass_rate, 4),
            "stationarity": stationarity,
            "ljung_box_flag": ljung_box_flag,
            "monotonicity": round(monotonicity, 4),
            "rationale": rationale,
        }

        # Add regime specialists info for conditional tier
        if tier == "conditional" and len(regime_ic) > 0:
            top_regimes = (
                regime_ic.nlargest(3, "mean_abs_ic_ir")[["regime_col", "regime_label"]]
                .apply(lambda r: f"{r['regime_col']}={r['regime_label']}", axis=1)
                .tolist()
            )
            feature_entry["specialist_regimes"] = top_regimes

        tiers[tier].append(feature_entry)

    # Build metadata block
    n_active = len(tiers["active"])
    n_conditional = len(tiers["conditional"])
    n_watch = len(tiers["watch"])
    n_archive = len(tiers["archive"])

    config = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "ic_ir_cutoff": ic_ir_cutoff,
            "n_features_total": len(ranking_df),
            "n_features_active": n_active,
            "n_features_conditional": n_conditional,
            "n_features_watch": n_watch,
            "n_features_archive": n_archive,
        },
        "active": tiers["active"],
        "conditional": tiers["conditional"],
        "watch": tiers["watch"],
        "archive": tiers["archive"],
    }

    logger.info(
        "build_feature_selection_config: %d total -> active=%d, conditional=%d, watch=%d, archive=%d",
        len(ranking_df),
        n_active,
        n_conditional,
        n_watch,
        n_archive,
    )

    return config


def _build_rationale(
    tier: str,
    ic_ir_mean: float,
    mean_abs_ic: float,
    pass_rate: float,
    stationarity: str,
    ljung_box_flag: bool,
    monotonicity: float,
    regime_ic: pd.DataFrame,
    ic_ir_cutoff: float,
) -> str:
    """Build a human-readable rationale string for a feature's tier assignment."""
    lb_str = "LB-flagged (serial correlation)" if ljung_box_flag else "no LB flag"
    base = (
        f"IC-IR={ic_ir_mean:.3f}, pass_rate={pass_rate:.2f}, "
        f"{stationarity}, {lb_str}, monotonicity={monotonicity:.3f}"
    )

    if tier == "active":
        return f"Active: {base}"

    if tier == "conditional":
        if len(regime_ic) > 0 and "mean_abs_ic_ir" in regime_ic.columns:
            best_ic = float(regime_ic["mean_abs_ic_ir"].max())
            best_row = regime_ic.loc[regime_ic["mean_abs_ic_ir"].idxmax()]
            regime_info = (
                f"regime specialist ({best_row['regime_col']}="
                f"{best_row['regime_label']}, IC-IR={best_ic:.3f})"
            )
            return f"Conditional: {base}; {regime_info}"
        shortfall = ic_ir_cutoff - ic_ir_mean
        return (
            f"Conditional: {base}; borderline signal (shortfall={shortfall:.3f} "
            f"vs cutoff={ic_ir_cutoff})"
        )

    if tier == "watch":
        shortfall = ic_ir_cutoff - ic_ir_mean
        return (
            f"Watch: {base}; weak signal (IC-IR shortfall={shortfall:.3f} "
            f"vs cutoff={ic_ir_cutoff}, pass_rate below threshold)"
        )

    # archive
    return f"Archive: {base}; no meaningful signal (IC-IR={ic_ir_mean:.3f} < 0.10 threshold)"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def save_to_db(engine, config: dict, yaml_version: str) -> int:
    """
    Persist feature selection config to dim_feature_selection (full replace).

    Truncates the table on each run and inserts all features across all tiers.
    This ensures the table reflects the latest run's config exactly.

    Parameters
    ----------
    engine : SQLAlchemy engine
        Database engine.
    config : dict
        Feature selection config from build_feature_selection_config().
    yaml_version : str
        Version tag identifying this config run (e.g. 'v1.0', '2026-03-22').

    Returns
    -------
    int
        Number of rows inserted.
    """
    rows_to_insert = []

    for tier in ("active", "conditional", "watch", "archive"):
        for entry in config.get(tier, []):
            specialist_regimes = entry.get("specialist_regimes", None)
            is_specialist = tier == "conditional" and bool(specialist_regimes)

            rows_to_insert.append(
                {
                    "feature_name": _to_python(entry["name"]),
                    "tier": tier,
                    "ic_ir_mean": _to_python(entry.get("ic_ir_mean")),
                    "pass_rate": _to_python(entry.get("pass_rate")),
                    "quintile_monotonicity": _to_python(entry.get("monotonicity")),
                    "stationarity": entry.get("stationarity", "INSUFFICIENT_DATA"),
                    "ljung_box_flag": bool(entry.get("ljung_box_flag", False)),
                    "regime_specialist": is_specialist,
                    "specialist_regimes": specialist_regimes,
                    "selected_at": datetime.utcnow(),
                    "yaml_version": yaml_version,
                    "rationale": entry.get("rationale", ""),
                }
            )

    if not rows_to_insert:
        logger.warning("save_to_db: no rows to insert — config is empty")
        return 0

    insert_sql = text(
        """
        INSERT INTO public.dim_feature_selection
            (feature_name, tier, ic_ir_mean, pass_rate, quintile_monotonicity,
             stationarity, ljung_box_flag, regime_specialist, specialist_regimes,
             selected_at, yaml_version, rationale)
        VALUES
            (:feature_name, :tier, :ic_ir_mean, :pass_rate, :quintile_monotonicity,
             :stationarity, :ljung_box_flag, :regime_specialist, :specialist_regimes,
             :selected_at, :yaml_version, :rationale)
        """
    )

    with engine.begin() as conn:
        # Full replace — truncate first
        conn.execute(text("TRUNCATE TABLE public.dim_feature_selection"))
        conn.execute(insert_sql, rows_to_insert)

    logger.info(
        "save_to_db: inserted %d rows (yaml_version=%s)",
        len(rows_to_insert),
        yaml_version,
    )
    return len(rows_to_insert)


def save_to_yaml(config: dict, output_path: Union[str, Path]) -> Path:
    """
    Write feature selection config to YAML file.

    Parameters
    ----------
    config : dict
        Feature selection config from build_feature_selection_config().
    output_path : str or Path
        Destination file path. Parent directories must exist.

    Returns
    -------
    Path
        The output path where the file was written.

    Notes
    -----
    File is opened with encoding='utf-8' for Windows compatibility.
    A comment header is prepended to identify the file's origin.
    """
    output_path = Path(output_path)

    header = "# Feature Selection Config -- generated by Phase 80\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    logger.info(
        "save_to_yaml: wrote %d bytes to %s", output_path.stat().st_size, output_path
    )
    return output_path
