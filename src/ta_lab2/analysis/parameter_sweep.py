# -*- coding: utf-8 -*-
"""
Simple parameter sweep utilities (grid/random).
Goal: quickly test indicator/signal params and rank by performance metrics.
"""
from __future__ import annotations
import itertools
import random
from typing import Callable, Dict, Iterable, List, Tuple
import pandas as pd

from .performance import evaluate_signals

Metrics = Dict[str, float]
RunFn = Callable[[Dict[str, object]], pd.DataFrame]
# RunFn: takes a param dict, returns a DataFrame with ['close','position'] at minimum.

def grid(param_grid: Dict[str, Iterable], run: RunFn, freq: str | None = None, costs_bps: float = 0.0) -> pd.DataFrame:
    """
    Exhaustive grid search over param_grid.
    param_grid example:
      {"fast": [21,34,55], "slow": [50,100], "rsi_min_long": [40,45]}
    """
    keys = list(param_grid.keys())
    results = []
    for values in itertools.product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, values))
        df = run(params)
        metrics = evaluate_signals(df, freq=freq, costs_bps=costs_bps)
        results.append({**params, **metrics})
    return pd.DataFrame(results).sort_values("sharpe", ascending=False, kind="mergesort")

def random_search(
    space: Dict[str, Iterable],
    run: RunFn,
    n_samples: int = 50,
    seed: int | None = 123,
    freq: str | None = None,
    costs_bps: float = 0.0,
) -> pd.DataFrame:
    """
    Randomly sample combinations from a parameter space.
    Use when grid is too large.
    """
    rng = random.Random(seed)
    keys = list(space.keys())
    values = [list(v) for v in space.values()]
    results = []

    for _ in range(n_samples):
        params = {k: rng.choice(values[i]) for i, k in enumerate(keys)}
        df = run(params)
        metrics = evaluate_signals(df, freq=freq, costs_bps=costs_bps)
        results.append({**params, **metrics})

    return pd.DataFrame(results).sort_values("sharpe", ascending=False, kind="mergesort")
