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

logger = logging.getLogger(__name__)

# Suppress per-trial Optuna output at module load time.
optuna.logging.set_verbosity(optuna.logging.WARNING)


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
