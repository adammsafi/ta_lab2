# -*- coding: utf-8 -*-
"""
IC-based parameter optimizer using Optuna.

This module is the primary parameter sweep infrastructure for Phase 105.
It runs Optuna studies using Spearman IC vs forward returns as the objective.

Design notes:
- NOT Sharpe-based (that is parameter_sweep.py, which uses evaluate_signals).
- NOT ML-based (that is run_optuna_sweep.py, which optimizes ML model params).
- IC-based: maximize Spearman correlation of indicator vs fwd_ret in train window.

Sampler selection based on grid_size (product of all param range sizes):
- grid_size <= grid_threshold (default 200): GridSampler with explicit value lists
- grid_size > grid_threshold: TPESampler(seed=seed, multivariate=True)

Public API:
    run_sweep               -- top-level entry point, returns sweep result dict
    plateau_score           -- fraction of neighboring params within threshold of peak IC
    rolling_stability_test  -- split-window IC stability check (sign flips, CV)
    compute_dsr_over_sweep  -- rolling-IC-based DSR with full sweep space deflation
    select_best_from_sweep  -- orchestrates top-N → plateau → stability → DSR pipeline
    _make_ic_objective      -- builds Optuna objective callable (exported for tests)
    _suggest_params         -- maps param_space_def dicts to trial.suggest_*
    _log_sweep_to_registry  -- upserts COMPLETE trials to trial_registry
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from math import prod
from typing import Any, Callable, Optional

import numpy as np
import optuna
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import text

from ta_lab2.analysis.ic import compute_rolling_ic
from ta_lab2.backtests.psr import compute_dsr

logger = logging.getLogger(__name__)

# Suppress per-trial Optuna output at module load time.
optuna.logging.set_verbosity(optuna.logging.WARNING)


# ---------------------------------------------------------------------------
# Overfitting-aware selection helpers (Phase 105-02)
# ---------------------------------------------------------------------------


def plateau_score(
    trial_results: list[dict[str, Any]],
    best_params: dict[str, Any],
    threshold: float = 0.80,
    neighbor_radius: int | float = 2,
) -> float:
    """
    Fraction of neighboring parameter combos whose IC is within ``threshold``
    of the best IC.

    A high plateau_score means the indicator is robust across a broad region of
    parameter space, not just a single sharp peak.

    Parameters
    ----------
    trial_results:
        List of dicts, each with keys ``"params"`` (dict) and ``"ic"`` (float or None).
    best_params:
        Parameter dict for the best trial (defines the center of the neighborhood).
    threshold:
        IC must be >= threshold * best_ic to count as a "good" neighbor.
        Default 0.80 (80% of peak IC).
    neighbor_radius:
        For single-param indicators: max allowed |p[k] - best_params[k]| for ALL keys.
        For multi-param indicators: max L-infinity distance in normalized param space
        expressed as neighbor_radius / max_range (scale-invariant).

    Returns
    -------
    float in [0.0, 1.0]:
        Fraction of neighbors whose IC >= threshold * best_ic.
        Returns 0.0 if no valid trials, best_ic <= 0, or no neighbors found.
    """
    # Filter to valid (non-None, non-NaN) IC trials.
    valid = [
        r for r in trial_results if r.get("ic") is not None and not np.isnan(r["ic"])
    ]
    if not valid:
        return 0.0

    best_ic = max(r["ic"] for r in valid)
    if best_ic <= 0.0:
        return 0.0

    min_ic = threshold * best_ic
    keys = list(best_params.keys())

    # Single-param: use absolute distance for each key.
    if len(keys) == 1:
        neighbors = [
            r
            for r in valid
            if abs(
                r["params"].get(keys[0], best_params[keys[0]]) - best_params[keys[0]]
            )
            <= neighbor_radius
        ]
    else:
        # Multi-param: normalize each dimension to [0,1] then use L-infinity distance.
        # Compute per-key min/max across all valid trials.
        key_min: dict[str, float] = {}
        key_max: dict[str, float] = {}
        for k in keys:
            vals = [r["params"].get(k, best_params[k]) for r in valid]
            key_min[k] = float(min(vals))
            key_max[k] = float(max(vals))

        # max_range is the largest raw range across all params (for scale-invariance).
        max_range = max((key_max[k] - key_min[k]) for k in keys)
        if max_range == 0.0:
            # All params are constant: the only neighbor is the point itself.
            neighbors = valid
        else:
            norm_radius = float(neighbor_radius) / max_range

            def _linf(r: dict[str, Any]) -> float:
                dists = []
                for k in keys:
                    rng = key_max[k] - key_min[k]
                    if rng == 0.0:
                        dists.append(0.0)
                    else:
                        p_norm = (r["params"].get(k, best_params[k]) - key_min[k]) / rng
                        b_norm = (best_params[k] - key_min[k]) / rng
                        dists.append(abs(p_norm - b_norm))
                return max(dists)

            neighbors = [r for r in valid if _linf(r) <= norm_radius]

    if not neighbors:
        return 0.0

    good = sum(1 for r in neighbors if r["ic"] >= min_ic)
    return float(good) / float(len(neighbors))


def rolling_stability_test(
    feature_series: pd.Series,
    fwd_ret: pd.Series,
    train_start: Any,
    train_end: Any,
    n_windows: int = 5,
    max_sign_flips: int = 1,
    max_ic_cv: float = 2.0,
    min_obs_per_window: int = 50,
) -> dict[str, Any]:
    """
    Split-window IC stability test.

    Divides [train_start, train_end] into ``n_windows`` non-overlapping chunks,
    computes per-chunk Spearman IC, then checks:
    - Sign flips: how many windows have IC sign != median IC sign
    - IC CV: std(ICs) / abs(mean(ICs)) — coefficient of variation

    Parameters
    ----------
    feature_series:
        Pre-computed indicator values (pd.Series, UTC-indexed).
    fwd_ret:
        Forward return series (aligned with feature_series).
    train_start, train_end:
        Window boundaries. Only data in [train_start, train_end] is used.
    n_windows:
        Number of non-overlapping windows to split the data into. Default 5.
    max_sign_flips:
        Maximum allowed windows where IC sign != median IC sign. Default 1.
    max_ic_cv:
        Maximum allowed IC coefficient of variation. Default 2.0.
    min_obs_per_window:
        Minimum valid observations required per window. Windows below this
        threshold are skipped.

    Returns
    -------
    dict with keys:
        passes           -- bool: True if all stability criteria are met
        sign_flips       -- int: windows with IC sign != median IC sign
        ic_cv            -- float: std/abs(mean) of window ICs (inf if abs(mean)<1e-10)
        window_ics       -- list[float]: per-window IC values (valid windows only)
        n_valid_windows  -- int: number of windows with >= min_obs_per_window valid obs
    """
    # Slice to train window and align series.
    feat = feature_series.loc[train_start:train_end]
    fwd = fwd_ret.loc[train_start:train_end]
    combined = pd.concat([feat.rename("feat"), fwd.rename("fwd")], axis=1).dropna()

    # Sort by index (defensive: should already be sorted).
    combined = combined.sort_index()

    # Split into n_windows equal chunks by row count.
    chunks = np.array_split(combined, n_windows)

    window_ics: list[float] = []
    for chunk in chunks:
        if len(chunk) < min_obs_per_window:
            continue
        corr, _ = spearmanr(chunk["feat"].values, chunk["fwd"].values)
        window_ics.append(float(corr))

    n_valid = len(window_ics)

    # Default: fail if too few valid windows to evaluate stability.
    if n_valid < 3:
        return {
            "passes": False,
            "sign_flips": 0,
            "ic_cv": float("inf"),
            "window_ics": window_ics,
            "n_valid_windows": n_valid,
        }

    ics_arr = np.array(window_ics, dtype=np.float64)
    median_ic = float(np.median(ics_arr))
    median_sign = np.sign(median_ic)

    # Count windows where sign differs from median sign.
    sign_flips = int(np.sum(np.sign(ics_arr) != median_sign))

    ic_mean = float(np.mean(ics_arr))
    ic_std = float(np.std(ics_arr, ddof=1))

    if abs(ic_mean) < 1e-10:
        ic_cv = float("inf")
    else:
        ic_cv = ic_std / abs(ic_mean)

    passes = (sign_flips <= max_sign_flips) and (ic_cv <= max_ic_cv) and (n_valid >= 3)

    return {
        "passes": bool(passes),
        "sign_flips": sign_flips,
        "ic_cv": float(ic_cv),
        "window_ics": window_ics,
        "n_valid_windows": n_valid,
    }


def compute_dsr_over_sweep(
    feature_best: pd.Series,
    fwd_ret: pd.Series,
    all_sweep_ics: list[float | None],
    window: int = 63,
) -> dict[str, Any]:
    """
    Compute Deflated Sharpe Ratio using the rolling IC series as returns.

    Uses the full sweep IC distribution to set the benchmark (expected maximum
    IC across all parameter combinations tested), deflating the best parameter's
    DSR for the size of the search space.

    Parameters
    ----------
    feature_best:
        Indicator values for the best parameter set (pd.Series, UTC-indexed).
    fwd_ret:
        Forward return series (aligned with feature_best).
    all_sweep_ics:
        IC value for EVERY parameter combination tested in the sweep (including
        None/NaN for failed trials). Used as sr_estimates for compute_dsr().
    window:
        Rolling window size for compute_rolling_ic. Default 63 (1 quarter).

    Returns
    -------
    dict with keys:
        dsr            -- float: DSR value in [0, 1], or NaN if insufficient data
        n_trials       -- int: number of valid (non-None, non-NaN) IC values
        rolling_ic_n   -- int: number of valid rolling IC observations (0 if insufficient)
        note           -- str: present only when dsr=NaN (e.g. "insufficient_rolling_ic")
    """
    # Compute rolling IC series (returns tuple: rolling_ic_series, ic_ir, ic_ir_tstat).
    rolling_ic_series, _, _ = compute_rolling_ic(feature_best, fwd_ret, window=window)
    rolling_ic_clean = rolling_ic_series.dropna().values

    if len(rolling_ic_clean) < 30:
        return {
            "dsr": float("nan"),
            "n_trials": len(all_sweep_ics),
            "rolling_ic_n": int(len(rolling_ic_clean)),
            "note": "insufficient_rolling_ic",
        }

    # Filter valid sweep ICs for benchmark computation.
    valid_ics = [
        ic for ic in all_sweep_ics if ic is not None and not np.isnan(float(ic))
    ]

    dsr_val = compute_dsr(
        best_trial_returns=rolling_ic_clean,
        sr_estimates=valid_ics if valid_ics else None,
        n_trials=len(all_sweep_ics) if not valid_ics else None,
    )

    return {
        "dsr": float(dsr_val),
        "n_trials": len(valid_ics),
        "rolling_ic_n": int(len(rolling_ic_clean)),
    }


def select_best_from_sweep(
    sweep_result: dict[str, Any],
    feature_fn: Callable[..., pd.Series],
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    fwd_ret: pd.Series,
    train_start: Any,
    train_end: Any,
    tf_days_nominal: float,
    conn: Optional[Any] = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """
    Overfitting-aware parameter selection from a completed sweep.

    Orchestrates the full selection pipeline:
    1. Build trial_results from sweep's COMPLETE trials.
    2. Sort by IC descending, take top_n candidates.
    3. Compute plateau_score for each candidate.
    4. Select the candidate with the highest plateau_score (tie-break: highest IC).
    5. Compute feature_best using feature_fn(**selected_params).
    6. Run rolling_stability_test on the selected params.
    7. Compute compute_dsr_over_sweep for selection-bias deflation.
    8. If conn provided: UPDATE trial_registry with plateau/stability/DSR metadata.

    Parameters
    ----------
    sweep_result:
        Dict returned by run_sweep() (keys: sweep_id, trials, etc.).
    feature_fn:
        Indicator function: feature_fn(close, high, low, volume, **params) -> pd.Series.
    close, high, low, volume:
        OHLCV price series (tz-aware UTC).
    fwd_ret:
        Forward return series.
    train_start, train_end:
        Train window boundaries for rolling_stability_test.
    tf_days_nominal:
        Nominal timeframe in days (not used directly here; passed for caller context).
    conn:
        Optional SQLAlchemy connection. If provided, UPDATE trial_registry with results.
    top_n:
        Number of top-IC candidates to consider for plateau ranking. Default 5.

    Returns
    -------
    dict with keys:
        selected_params  -- dict of parameter values for the chosen parameter set
        ic               -- float: IC of selected params
        plateau_score    -- float: plateau score of selected params
        stability        -- dict: result of rolling_stability_test
        dsr              -- dict: result of compute_dsr_over_sweep
        sweep_id         -- str: sweep UUID from sweep_result
    """
    trials = sweep_result.get("trials", [])
    sweep_id = sweep_result.get("sweep_id", "")

    # Build trial_results from COMPLETE trials only.
    trial_results = [
        {"params": t.params, "ic": t.value}
        for t in trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
    ]

    if not trial_results:
        logger.warning(
            "select_best_from_sweep: no COMPLETE trials found in sweep_result"
        )
        return {
            "selected_params": None,
            "ic": float("nan"),
            "plateau_score": 0.0,
            "stability": {
                "passes": False,
                "sign_flips": 0,
                "ic_cv": float("inf"),
                "window_ics": [],
                "n_valid_windows": 0,
            },
            "dsr": {"dsr": float("nan"), "n_trials": 0, "rolling_ic_n": 0},
            "sweep_id": sweep_id,
        }

    # Collect all sweep ICs for DSR deflation.
    all_sweep_ics: list[float | None] = [t.value for t in trials]

    # Sort by IC descending, take top_n.
    sorted_trials = sorted(trial_results, key=lambda r: float(r["ic"]), reverse=True)
    candidates = sorted_trials[:top_n]

    # Compute plateau_score for each candidate.
    candidate_scores = []
    for cand in candidates:
        ps = plateau_score(trial_results, cand["params"])
        candidate_scores.append({"params": cand["params"], "ic": cand["ic"], "ps": ps})

    # Select best: highest plateau_score, tie-break by highest IC.
    best = max(candidate_scores, key=lambda x: (x["ps"], x["ic"]))
    selected_params = best["params"]
    selected_ic = best["ic"]
    selected_ps = best["ps"]

    # Compute feature series for selected params.
    try:
        feature_best = feature_fn(
            close=close, high=high, low=low, volume=volume, **selected_params
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "select_best_from_sweep: feature_fn raised %s with params %s",
            exc,
            selected_params,
        )
        feature_best = pd.Series(dtype=float, index=close.index)

    # Slice to train window for stability test.
    feat_train = feature_best.loc[train_start:train_end]
    fwd_train = fwd_ret.loc[train_start:train_end]

    # Rolling stability test.
    stability = rolling_stability_test(feat_train, fwd_train, train_start, train_end)

    # DSR with full sweep space deflation.
    dsr = compute_dsr_over_sweep(feat_train, fwd_train, all_sweep_ics)

    # Optional DB update: UPDATE trial_registry with metadata for selected params.
    if conn is not None:
        try:
            conn.execute(
                text("""
                UPDATE public.trial_registry
                SET
                    plateau_score           = :plateau_score,
                    rolling_stability_passes = :stability_passes,
                    ic_cv                   = :ic_cv,
                    sign_flips              = :sign_flips,
                    dsr_adjusted_sharpe     = :dsr_val,
                    n_sweep_trials          = :n_trials
                WHERE sweep_id = :sweep_id
                  AND param_set = :param_set
                """),
                {
                    "plateau_score": float(selected_ps),
                    "stability_passes": bool(stability["passes"]),
                    "ic_cv": float(stability["ic_cv"])
                    if np.isfinite(stability["ic_cv"])
                    else None,
                    "sign_flips": int(stability["sign_flips"]),
                    "dsr_val": float(dsr["dsr"]) if not np.isnan(dsr["dsr"]) else None,
                    "n_trials": int(dsr["n_trials"]),
                    "sweep_id": uuid.UUID(sweep_id) if sweep_id else None,
                    "param_set": str(selected_params),
                },
            )
            logger.info(
                "select_best_from_sweep: updated trial_registry for sweep_id=%s "
                "params=%s plateau=%.3f dsr=%s",
                sweep_id[:8] if sweep_id else "?",
                selected_params,
                selected_ps,
                f"{dsr['dsr']:.4f}" if not np.isnan(dsr["dsr"]) else "NaN",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "select_best_from_sweep: DB update failed (%s); selection result unaffected",
                exc,
            )

    return {
        "selected_params": selected_params,
        "ic": float(selected_ic),
        "plateau_score": float(selected_ps),
        "stability": stability,
        "dsr": dsr,
        "sweep_id": sweep_id,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _suggest_params(trial: optuna.Trial, param_space_def: list[dict]) -> dict[str, Any]:
    """
    Map param_space_def entries to Optuna trial suggestions.

    param_space_def entry format:
      {"name": "window", "type": "int", "low": 5, "high": 30}
      {"name": "std", "type": "float", "low": 1.0, "high": 3.0, "step": 0.25}

    Returns dict mapping param name -> suggested value.
    """
    params: dict[str, Any] = {}
    for spec in param_space_def:
        name: str = spec["name"]
        ptype: str = spec["type"]
        low = spec["low"]
        high = spec["high"]
        if ptype == "int":
            params[name] = trial.suggest_int(name, int(low), int(high))
        elif ptype == "float":
            step = spec.get("step")
            params[name] = trial.suggest_float(name, float(low), float(high), step=step)
        else:
            raise ValueError(f"Unknown param type '{ptype}' for param '{name}'")
    return params


def _make_ic_objective(
    feature_fn: Callable[..., pd.Series],
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    fwd_ret: pd.Series,
    train_start: Any,
    train_end: Any,
    param_space_def: list[dict],
    tf_days_nominal: float,
    min_obs: int = 50,
) -> Callable[[optuna.Trial], float]:
    """
    Build an Optuna objective callable that maximizes Spearman IC.

    Parameters
    ----------
    feature_fn:
        Indicator function. Signature: feature_fn(close, high, low, volume, **params)
        Returns pd.Series aligned with the input index.
    close, high, low, volume:
        Price series (tz-aware UTC).
    fwd_ret:
        Forward return series aligned with close (typically pct_change().shift(-1)).
    train_start, train_end:
        Inclusive window boundaries for IC computation.
    param_space_def:
        List of param dicts (same format as _suggest_params).
    tf_days_nominal:
        Nominal timeframe length in days. Used to mask boundary observations
        where the forward return window extends beyond train_end.
    min_obs:
        Minimum valid (non-NaN) observations required; returns NaN if below.

    Returns
    -------
    Callable that takes an optuna.Trial and returns IC as float (maximize).
    """

    def objective(trial: optuna.Trial) -> float:
        params = _suggest_params(trial, param_space_def)

        # Compute indicator values.
        try:
            feat = feature_fn(close=close, high=high, low=low, volume=volume, **params)
        except Exception as exc:  # noqa: BLE001
            logger.debug("feature_fn raised %s with params %s -- pruning", exc, params)
            raise optuna.exceptions.TrialPruned() from exc

        # Slice to train window.
        feat_train = feat.loc[train_start:train_end]
        fwd_train = fwd_ret.loc[train_start:train_end]

        # Boundary mask: exclude observations where forward-return window spills
        # past train_end (these observations have lookahead leakage in fwd_ret).
        boundary_cutoff = pd.Timestamp(train_end) - timedelta(
            days=float(tf_days_nominal)
        )
        fwd_train = fwd_train.copy()
        mask = feat_train.index > boundary_cutoff
        fwd_train[mask] = float("nan")

        # Align and drop NaN pairs.
        combined = pd.concat(
            [feat_train.rename("feat"), fwd_train.rename("fwd")], axis=1
        ).dropna()

        if len(combined) < min_obs:
            return float("nan")

        ic_val, _ = spearmanr(combined["feat"].values, combined["fwd"].values)
        return float(ic_val)

    return objective


def _log_sweep_to_registry(
    conn: Any,
    trials: list[optuna.trial.FrozenTrial],
    sweep_id: str,
    indicator_name: str,
    asset_id: int,
    tf: str,
    venue_id: int = 1,
) -> int:
    """
    Upsert COMPLETE Optuna trials to trial_registry with sweep_id grouping.

    Uses temp table + ON CONFLICT DO UPDATE pattern (project standard).
    Only COMPLETE trials are written (PRUNED/FAILED are skipped).

    Returns number of rows written.
    """
    complete_trials = [
        t
        for t in trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
    ]
    if not complete_trials:
        logger.debug("_log_sweep_to_registry: no COMPLETE trials to write")
        return 0

    n_sweep = len(trials)
    sweep_uuid = uuid.UUID(sweep_id)

    rows = []
    for t in complete_trials:
        rows.append(
            {
                "indicator_name": indicator_name,
                "param_set": str(t.params),
                "tf": tf,
                "asset_id": asset_id,
                "venue_id": venue_id,
                "horizon": 1,
                "return_type": "arith",
                "ic_observed": t.value,
                "sweep_id": sweep_uuid,
                "n_sweep_trials": n_sweep,
                "source_table": "param_sweep",
            }
        )

    # Temp table upsert pattern (project standard).
    conn.execute(
        text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_sweep_trials (
            indicator_name  VARCHAR(128) NOT NULL,
            param_set       VARCHAR(256) NOT NULL,
            tf              VARCHAR(32)  NOT NULL,
            asset_id        INTEGER      NOT NULL,
            venue_id        SMALLINT     NOT NULL,
            horizon         SMALLINT     NOT NULL,
            return_type     VARCHAR(8)   NOT NULL,
            ic_observed     DOUBLE PRECISION,
            sweep_id        UUID,
            n_sweep_trials  INTEGER,
            source_table    VARCHAR(64)  NOT NULL
        ) ON COMMIT DROP
        """)
    )

    conn.execute(
        text("""
        INSERT INTO _tmp_sweep_trials
            (indicator_name, param_set, tf, asset_id, venue_id, horizon,
             return_type, ic_observed, sweep_id, n_sweep_trials, source_table)
        VALUES
            (:indicator_name, :param_set, :tf, :asset_id, :venue_id, :horizon,
             :return_type, :ic_observed, :sweep_id, :n_sweep_trials, :source_table)
        """),
        rows,
    )

    result = conn.execute(
        text("""
        INSERT INTO public.trial_registry
            (indicator_name, param_set, tf, asset_id, venue_id, horizon,
             return_type, ic_observed, sweep_id, n_sweep_trials, source_table,
             sweep_ts)
        SELECT
            indicator_name, param_set, tf, asset_id, venue_id, horizon,
            return_type, ic_observed, sweep_id, n_sweep_trials, source_table,
            now()
        FROM _tmp_sweep_trials
        ON CONFLICT (indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type)
        DO UPDATE SET
            ic_observed    = EXCLUDED.ic_observed,
            sweep_id       = EXCLUDED.sweep_id,
            n_sweep_trials = EXCLUDED.n_sweep_trials,
            source_table   = EXCLUDED.source_table,
            sweep_ts       = now()
        """)
    )

    n_written = result.rowcount
    logger.info(
        "_log_sweep_to_registry: upserted %d rows for sweep_id=%s indicator=%s tf=%s",
        n_written,
        sweep_id,
        indicator_name,
        tf,
    )
    return n_written


def _compute_grid_size(param_space_def: list[dict]) -> int:
    """Compute total grid size (Cartesian product of all param ranges)."""
    sizes = []
    for spec in param_space_def:
        low = spec["low"]
        high = spec["high"]
        ptype = spec["type"]
        if ptype == "int":
            sizes.append(int(high) - int(low) + 1)
        elif ptype == "float":
            step = spec.get("step")
            if step is not None and step > 0:
                sizes.append(int(round((float(high) - float(low)) / float(step))) + 1)
            else:
                # No step specified -- treat as continuous, assign size 1 for grid calc.
                sizes.append(1)
        else:
            sizes.append(1)
    return prod(sizes) if sizes else 1


def _build_grid_search_space(param_space_def: list[dict]) -> dict[str, list]:
    """
    Build GridSampler search_space with explicit Python value lists.

    CRITICAL: Uses list(range(...)) for int params and list comprehension
    for float params. Never uses np.arange (returns numpy scalars, which
    cause GridSampler to fail silently or raise type errors).
    """
    search_space: dict[str, list] = {}
    for spec in param_space_def:
        name = spec["name"]
        low = spec["low"]
        high = spec["high"]
        ptype = spec["type"]
        if ptype == "int":
            search_space[name] = list(range(int(low), int(high) + 1))
        elif ptype == "float":
            step = spec.get("step")
            if step is not None and step > 0:
                n_steps = int(round((float(high) - float(low)) / float(step)))
                search_space[name] = [
                    round(float(low) + i * float(step), 10) for i in range(n_steps + 1)
                ]
            else:
                # No step -- single-point float (continuous params not supported by Grid).
                search_space[name] = [float(low)]
        else:
            search_space[name] = [low]
    return search_space


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_sweep(
    indicator_name: str,
    feature_fn: Callable[..., pd.Series],
    param_space_def: list[dict],
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    fwd_ret: pd.Series,
    train_start: Any,
    train_end: Any,
    asset_id: int,
    tf: str,
    tf_days_nominal: float,
    venue_id: int = 1,
    grid_threshold: int = 200,
    tpe_n_trials: int = 100,
    seed: int = 42,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Run an IC-based parameter optimization sweep using Optuna.

    Sampler selection:
    - grid_size <= grid_threshold: GridSampler (exhaustive, deterministic).
    - grid_size >  grid_threshold: TPESampler(seed, multivariate=True).

    Parameters
    ----------
    indicator_name:
        Name of the indicator being swept (logged to trial_registry).
    feature_fn:
        Indicator function: feature_fn(close, high, low, volume, **params) -> pd.Series.
    param_space_def:
        List of param spec dicts. Each dict has keys: name, type, low, high,
        and optionally step (for float params).
    close, high, low, volume:
        OHLCV price series (tz-aware UTC, same index).
    fwd_ret:
        Forward return series (typically close.pct_change().shift(-1)).
    train_start, train_end:
        Train window boundaries for IC computation. Inclusive.
    asset_id:
        Asset ID for trial_registry logging.
    tf:
        Timeframe string (e.g. '1D', '4H').
    tf_days_nominal:
        Nominal timeframe in days. Used for boundary masking in objective.
    venue_id:
        Venue ID for trial_registry logging (default=1, CMC_AGG).
    grid_threshold:
        Max grid_size to use GridSampler. Above this TPESampler is used.
    tpe_n_trials:
        Number of trials for TPESampler runs.
    seed:
        Random seed for TPESampler.
    conn:
        Optional SQLAlchemy connection. If provided, logs trials to trial_registry.

    Returns
    -------
    dict with keys:
        sweep_id    -- UUID string identifying this sweep run
        best_params -- dict of best parameter values found
        best_ic     -- best IC value found
        n_trials    -- total number of trials (all states)
        n_complete  -- number of COMPLETE trials (NaN-value trials count as COMPLETE)
        trials      -- list of optuna.trial.FrozenTrial objects
    """
    grid_size = _compute_grid_size(param_space_def)
    sweep_id = str(uuid.uuid4())

    if grid_size <= grid_threshold:
        search_space = _build_grid_search_space(param_space_def)
        sampler: optuna.samplers.BaseSampler = optuna.samplers.GridSampler(search_space)
        n_trials = grid_size
        logger.info(
            "run_sweep [%s]: GridSampler, grid_size=%d, indicator=%s tf=%s",
            sweep_id[:8],
            grid_size,
            indicator_name,
            tf,
        )
    else:
        sampler = optuna.samplers.TPESampler(seed=seed, multivariate=True)
        n_trials = tpe_n_trials
        logger.info(
            "run_sweep [%s]: TPESampler, n_trials=%d (grid_size=%d > threshold=%d), "
            "indicator=%s tf=%s",
            sweep_id[:8],
            n_trials,
            grid_size,
            grid_threshold,
            indicator_name,
            tf,
        )

    objective = _make_ic_objective(
        feature_fn=feature_fn,
        close=close,
        high=high,
        low=low,
        volume=volume,
        fwd_ret=fwd_ret,
        train_start=train_start,
        train_end=train_end,
        param_space_def=param_space_def,
        tf_days_nominal=tf_days_nominal,
    )

    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    complete_trials = [
        t
        for t in study.trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
    ]
    n_complete = len(complete_trials)

    # best_params / best_ic from the study (Optuna skips NaN-valued trials).
    try:
        best_params = study.best_params
        best_ic = study.best_value
    except ValueError:
        # No non-NaN trials completed.
        best_params = {}
        best_ic = float("nan")

    logger.info(
        "run_sweep [%s]: complete=%d/%d, best_ic=%.4f, best_params=%s",
        sweep_id[:8],
        n_complete,
        n_trials,
        best_ic if not np.isnan(best_ic) else float("nan"),
        best_params,
    )

    if conn is not None:
        _log_sweep_to_registry(
            conn=conn,
            trials=study.trials,
            sweep_id=sweep_id,
            indicator_name=indicator_name,
            asset_id=asset_id,
            tf=tf,
            venue_id=venue_id,
        )

    return {
        "sweep_id": sweep_id,
        "best_params": best_params,
        "best_ic": best_ic,
        "n_trials": len(study.trials),
        "n_complete": n_complete,
        "trials": study.trials,
    }
