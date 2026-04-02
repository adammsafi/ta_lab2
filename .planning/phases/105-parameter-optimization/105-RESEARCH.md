# Phase 105: Parameter Optimization - Research

**Researched:** 2026-04-01
**Domain:** Bayesian parameter sweep (Optuna), plateau scoring, rolling temporal stability, DSR over parameter search space, trial_registry integration
**Confidence:** HIGH (Optuna API verified via official GitHub; psr.py and ic.py read directly; Optuna usage in run_optuna_sweep.py read directly; DSR formula from Bailey & Lopez de Prado 2014 verified against existing psr.py implementation)

---

## Summary

Phase 105 adds systematic, overfitting-aware parameter optimization for every indicator that survived Phases 103-104. The phase has three concerns: (1) running a sweep (grid or Optuna Bayesian) over each indicator's parameter space, (2) selecting parameters from the widest IC-positive plateau rather than the sharpest peak, and (3) applying DSR over the full parameter search space to quantify how much selection bias inflates the winning parameter's apparent Sharpe.

**What was researched:** Optuna's GridSampler and TPESampler APIs (verified via official GitHub source); the existing `run_optuna_sweep.py` (LightGBM ML use, entirely different objective — IC-based objective must be written fresh); the existing `psr.py` DSR functions (fully compatible for parameter-space DSR with minor framing change); the existing `ic.py` `compute_rolling_ic()` function (directly usable for rolling stability windows); the `parameter_sweep.py` file (bare-bones, Sharpe-based, not IC-based — not reusable as-is); the `trial_registry` schema from Phase 102 planning (does NOT yet have `sweep_id` — must be added in Phase 105); indicator parameter spaces for all 20 Phase 103 traditional TA indicators and crypto-native Phase 104 indicators.

**Standard approach:** Use Optuna with `GridSampler` for small parameter spaces (< 200 combinations) and `TPESampler` for larger ones. The objective function computes IC (Spearman rank correlation with forward returns) per parameter set over a fixed train window. All results are logged to `trial_registry` grouped by a `sweep_id` UUID. Plateau scoring counts the fraction of neighboring parameter sets within 80% of peak IC. Rolling stability splits the data into 5+ non-overlapping windows and applies the DSR-corrected selection criterion.

**Primary recommendation:** Build `src/ta_lab2/analysis/param_optimizer.py` as a single new module containing `run_sweep()`, `plateau_score()`, `rolling_stability_test()`, and `compute_dsr_over_sweep()`. The sweep runner delegates to Optuna (or itertools for grid). The DSR functions wrap `compute_dsr()` from the existing `psr.py`. No new library dependencies are needed beyond Optuna (already installed, already used in run_optuna_sweep.py).

---

## Standard Stack

### Core (all already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| optuna | (installed) | Bayesian TPE search and grid search over indicator parameter spaces | Already used in run_optuna_sweep.py; TPESampler with seed=42 is project convention |
| scipy.stats.spearmanr | (installed) | Spearman IC computation inside objective function | Already used in ic.py and multiple_testing.py |
| numpy | 2.4.1 | Parameter range construction, IC array operations | Already used everywhere |
| pandas | 2.3.3 | Feature/returns alignment, rolling windows | Already used everywhere |
| sqlalchemy.text | (installed) | trial_registry upsert and sweep_id grouping | Project standard |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| itertools.product | stdlib | Exhaustive grid search when n_combinations <= 200 | For small parameter spaces: RSI(5-30 step 1) = 26 trials |
| uuid.uuid4 | stdlib | Generate sweep_id grouping all trials for one indicator sweep | One sweep_id per indicator × asset × tf × run |

### Not Needed

| Library | Reason to Skip |
|---------|----------------|
| scikit-optimize (skopt) | Optuna already installed and used; no need for second HPO library |
| hyperopt | Same reason |
| pandas-ta / ta-lib | Project standard is hand-rolled indicators (see Phase 103 research) |

### No New Dependencies

All required functionality is in already-installed packages. Optuna is confirmed installed (imported in `run_optuna_sweep.py` without install guard failure in CI).

**Installation:**
```bash
# Nothing to install — all required libraries are already installed
# Verify:
python -c "import optuna; print(optuna.__version__)"
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/analysis/
├── ic.py                    # existing — compute_rolling_ic() reused as-is
├── multiple_testing.py      # existing (Phase 102) — log_trials_to_registry() called after sweep
├── psr.py                   # existing — compute_dsr() called for DSR over sweep
├── param_optimizer.py       # NEW — run_sweep, plateau_score, rolling_stability_test, compute_dsr_over_sweep

alembic/versions/
└── v5w6x7y8z9a0_phase105_trial_registry_sweep_id.py   # NEW — adds sweep_id column

src/ta_lab2/scripts/analysis/
├── run_param_sweep.py       # NEW — CLI runner for Phase 105 sweeps
```

### Pattern 1: Optuna IC Objective Function

**What:** Optuna objective function that computes Spearman IC for a given parameter set over a fixed train window.
**When to use:** For all indicators where grid size > 200 combinations, or where Bayesian guidance is useful (MACD, BBANDS with 3+ params).

```python
# Source: verified against run_optuna_sweep.py pattern + ic.py _compute_single_ic
import optuna
from scipy.stats import spearmanr
import numpy as np

def _make_ic_objective(
    feature_fn,          # callable(close, high, low, volume, **params) -> pd.Series
    close, high, low, volume,
    fwd_ret,             # precomputed forward returns (full series)
    train_start, train_end,
    tf_days_nominal: int,
    min_obs: int = 50,
):
    """
    Returns an Optuna objective that:
    1. Calls feature_fn(**trial.params) to compute indicator values
    2. Computes Spearman IC vs fwd_ret in the train window
    3. Returns IC (maximize) or -abs(IC) if no-directional search preferred
    """
    def objective(trial) -> float:
        params = _suggest_params(trial, feature_fn)   # indicator-specific suggest block
        feat = feature_fn(close=close, high=high, low=low, volume=volume, **params)

        # Align to train window, boundary-mask, dropna
        mask = (feat.index >= train_start) & (feat.index <= train_end)
        feat_train = feat[mask]
        fwd_train = fwd_ret.reindex(feat_train.index).copy()
        horizon_delta = pd.Timedelta(days=1 * tf_days_nominal)
        fwd_train[feat_train.index + horizon_delta > train_end] = np.nan

        valid = pd.concat([feat_train, fwd_train], axis=1).dropna()
        if len(valid) < min_obs:
            return float("nan")   # Optuna treats nan as pruned/failed

        ic, _ = spearmanr(valid.iloc[:, 0], valid.iloc[:, 1])
        return float(ic) if not np.isnan(ic) else float("nan")

    return objective
```

**Critical:** When objective returns `float("nan")`, Optuna marks the trial as failed (not as a valid result). Use `optuna.exceptions.TrialPruned()` instead if you want Optuna to track the trial but ignore it for sampling. For parameter sweep purposes, returning nan is acceptable since we want to record ALL trials in `trial_registry` manually after the study completes.

### Pattern 2: GridSampler for Small Parameter Spaces

**What:** Use `optuna.samplers.GridSampler` when the full grid fits in <= 200 trials.
**When to use:** RSI (window=5..30 step 1 = 26 trials), Williams %R (14..28 step 2 = 8 trials), VWAP (7..21 step 1 = 15 trials).

```python
# Source: verified from GitHub optuna/optuna/samplers/_grid.py
import optuna

search_space = {"window": list(range(5, 31))}   # 26 integer values
sampler = optuna.samplers.GridSampler(search_space, seed=42)
study = optuna.create_study(
    study_name=f"rsi_sweep_{asset_id}_{tf}",
    direction="maximize",
    sampler=sampler,
)
# GridSampler exhausts all combinations then stops
study.optimize(objective, n_trials=len(search_space["window"]))
```

**CRITICAL GridSampler gotcha:** `GridSampler.search_space` takes explicit value lists — not ranges or floats with steps. The trial's `trial.suggest_int("window", 5, 30)` inside the objective will be overridden to use only values in the grid. Do NOT use `suggest_float` with a step alongside GridSampler — it does not enforce quantization (verified in GitHub source: "just samples one of values specified in the search space").

### Pattern 3: TPESampler for Large Parameter Spaces

**What:** Use `optuna.samplers.TPESampler` when grid size > 200 combinations.
**When to use:** MACD (fast=2..15, slow=10..50, signal=3..12 = 11 x 41 x 10 = 4,510 grid cells), BBANDS (window=5..50, std=1.0..3.0 step 0.25 = 46 x 9 = 414 cells), Ichimoku (tenkan, kijun, senkou_b — ~200+).

```python
# Source: verified from run_optuna_sweep.py lines 474-488
sampler = optuna.samplers.TPESampler(seed=42, multivariate=True)
study = optuna.create_study(
    study_name=f"macd_sweep_{asset_id}_{tf}",
    direction="maximize",
    sampler=sampler,
)
study.optimize(objective, n_trials=100)   # 100 trials for 4,510-cell space
```

**Why `multivariate=True`:** MACD parameters are correlated (fast must be < slow). Multivariate TPE models joint distributions and respects this constraint better than independent per-parameter modeling. Set `multivariate=True` for all multi-parameter indicators.

### Pattern 4: sweep_id Grouping

**What:** Every call to `run_sweep()` for one (indicator, asset, tf) combination gets a single UUID as `sweep_id`. All parameter variants written to `trial_registry` share this `sweep_id`.
**When to use:** Always — this is how the planner can later query "all RSI variants for BTC on 1D in this run."

```python
import uuid

def run_sweep(indicator_name, asset_id, tf, ...) -> str:
    sweep_id = str(uuid.uuid4())
    # ... run study ...
    # for each trial, write to trial_registry with sweep_id=sweep_id
    return sweep_id
```

### Pattern 5: plateau_score() Algorithm

**What:** Measures the width of the IC-positive region around the optimal parameter set. For discrete integer parameters, counts how many neighboring parameter combinations are within `threshold` (default 80%) of peak IC.
**When to use:** After sweep completes, on the collected trial results DataFrame.

```python
def plateau_score(
    trial_results: pd.DataFrame,   # columns: param_1, ..., param_N, ic
    best_params: dict,
    threshold: float = 0.80,
    neighbor_radius: int = 2,      # for integer params: +/- 2 steps
) -> float:
    """
    Returns fraction of neighboring parameter combinations (within neighbor_radius
    steps of best_params on each integer axis) where IC >= threshold * best_ic.

    For float parameters, discretize to nearest grid step before computing neighbors.

    Returns float in [0, 1]. Higher = broader plateau = more robust parameter choice.
    """
    best_ic = trial_results["ic"].max()
    if best_ic <= 0:
        return 0.0   # no IC-positive region

    min_ic = threshold * best_ic
    neighbors = _get_neighbors(trial_results, best_params, neighbor_radius)
    if len(neighbors) == 0:
        return 0.0
    return float((neighbors["ic"] >= min_ic).mean())
```

**Why `neighbor_radius=2` is the right default:** A radius of 1 is too sensitive to local noise. A radius of 3+ may cross into a different regime for narrow indicators (RSI window 14 vs 17 is already very different behavior). Radius 2 gives a 5-wide window for integer params (+/-2) which is stable and comparable to the "broad area of success" concept from Kaufman.

**Multi-parameter normalization:** For indicators with multiple parameters (MACD: fast, slow, signal), normalize each dimension to [0,1] using the range, then compute L-infinity distance in normalized space. A neighbor is any combination where L-inf distance <= `neighbor_radius / total_range`. This keeps the radius scale-invariant across parameters.

### Pattern 6: rolling_stability_test() Algorithm

**What:** Splits the full data window into N non-overlapping folds, computes IC per fold for the optimal parameter set, and rejects parameters where IC sign flips in more than 1 fold or IC coefficient of variation (std/mean) exceeds a threshold.
**When to use:** After `plateau_score()` selects a candidate parameter set, before writing to `dim_feature_selection`.

```python
def rolling_stability_test(
    feature_fn,
    close, high, low, volume,
    fwd_ret,
    best_params: dict,
    n_windows: int = 5,
    max_sign_flips: int = 1,
    max_ic_cv: float = 2.0,     # IC std/mean < 2.0
    tf_days_nominal: int = 1,
    min_obs_per_window: int = 50,
) -> dict:
    """
    Splits the full time range into n_windows non-overlapping segments.
    Computes IC in each segment for best_params.
    Returns:
        {
          "passes": bool,
          "sign_flips": int,
          "ic_cv": float,
          "window_ics": list[float],
          "n_valid_windows": int,
        }
    """
    # Split index into n_windows
    # Compute IC per window using _compute_single_ic() or spearmanr directly
    # Count sign flips: window IC changes sign vs overall IC direction
    # Compute ic_cv = std(window_ics) / abs(mean(window_ics))
    # passes = sign_flips <= max_sign_flips AND ic_cv <= max_ic_cv
```

**Reuse `compute_rolling_ic()` from ic.py:** `ic.py` already has `compute_rolling_ic(feature, fwd_ret, window=63)` which returns a rolling IC series. For the stability test, use a non-overlapping variant: split data into 5 equal-length chunks, compute IC on each chunk with `_compute_single_ic()`. Do NOT use `compute_rolling_ic()` directly (it's overlapping; produces correlated windows).

**Sign flip definition:** A sign flip is when a window IC has the opposite sign of the median IC across all windows. One flip is allowable (regime change); two or more indicates an unstable factor.

**IC CV threshold:** `max_ic_cv = 2.0` means the IC standard deviation can be up to 2x the mean. This is generous but appropriate: IC values are noisy, and crypto markets have regime changes. A tighter threshold (1.0) would reject most indicators.

### Pattern 7: DSR over Parameter Search Space

**What:** Apply DSR (Deflated Sharpe Ratio) to the winning parameter set, where the "N trials" is all parameter combinations tested in the sweep.
**When to use:** After the sweep completes, before final parameter selection.

**The critical framing distinction:** DSR was originally designed for strategy backtests with returns series. Here we're applying it to IC-derived pseudo-Sharpes. The connection:

1. For each parameter combination `k`, compute `IC_k` over the train window.
2. Convert IC to a pseudo-Sharpe: `sr_k = IC_k * sqrt(n_obs)` (IC t-stat form, which is proportional to Sharpe for long-only signals). Alternatively, use the IC t-stat directly as `sr_k`.
3. Collect all `sr_k` into `sr_estimates` (list of N values, one per parameter combination).
4. Call `compute_dsr(best_trial_returns, sr_estimates=sr_estimates)` from `psr.py`.

**Problem with IC-as-returns:** `compute_dsr()` expects a returns series for the best trial (`best_trial_returns`), not an IC value. The IC is not a returns series.

**Recommended approach:** Use `compute_dsr()` with `n_trials` mode (approximate mode) rather than exact mode:

```python
from ta_lab2.backtests.psr import compute_dsr, expected_max_sr

# N = total parameter combinations tested in this sweep
n_params = len(study.trials)

# For the best parameter set, get the rolling IC series as a proxy returns series
# rolling_ic_series from compute_rolling_ic() -- mean is IC, std is IC variability
rolling_ic_best, ic_ir_best, _ = compute_rolling_ic(
    feature_best, fwd_ret, window=63
)
rolling_ic_clean = rolling_ic_best.dropna().values

# DSR: treat rolling IC values as the "returns" of the best trial
# N trials = n_params (all parameter combinations tested)
dsr_value = compute_dsr(
    best_trial_returns=rolling_ic_clean,
    n_trials=n_params,
)

# For exact mode (preferred if all sweep ICs available):
all_sr_estimates = [t.value for t in study.trials if t.value is not None]
dsr_exact = compute_dsr(
    best_trial_returns=rolling_ic_clean,
    sr_estimates=all_sr_estimates,  # list of IC values (used as pseudo-SR)
)
```

**DSR storage:** Store `dsr_adjusted_sharpe = dsr_value` in `trial_registry` for the best-parameter row. Also store `n_sweep_trials` (total combinations tested) and the raw IC value. Success criterion IND-15 says "DSR-adjusted Sharpe is stored alongside the raw Sharpe" — use a new column `dsr_adjusted_sharpe` added in the Phase 105 migration.

### Anti-Patterns to Avoid

- **Reusing `parameter_sweep.py` grid() / random_search():** These use Sharpe ratio (strategy backtest-based) as the objective. Phase 105 uses IC as the objective. The existing `parameter_sweep.py` is not reusable for this purpose. Build fresh in `param_optimizer.py`.
- **Reusing `run_optuna_sweep.py` directly:** That script sweeps LightGBM hyperparameters with cross-validation accuracy as the objective, not IC. The architecture (objective function, study setup) can be used as a reference pattern, but the script cannot be reused.
- **Using Optuna's built-in study persistence (SQLite storage):** The existing project convention stores all results in PostgreSQL (`trial_registry`). Do NOT use `--storage sqlite:///optuna.db`. Run studies in-memory and write results to `trial_registry` manually.
- **Computing IC on overlapping windows for `rolling_stability_test()`:** Use non-overlapping windows only. Rolling/overlapping windows produce correlated IC values that understate variance and make the CV test too lenient.
- **Passing GridSampler a `suggest_float(step=...)` parameter:** GridSampler ignores quantization — it will return arbitrary float values from within a specified range, not the step-discretized values. Always pass explicit integer lists to GridSampler.
- **Setting N_trials too high for TPE on small data:** For crypto 1D data, ~2,000-4,000 bars are available. IC computation is O(n_obs log n_obs) for Spearman. 100 Optuna trials = 100 IC computations = fast. 1000 trials adds no value for a 26-cell RSI space (just run the full grid). Use GridSampler when grid size < 200.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bayesian parameter search | Custom sequential model | `optuna.samplers.TPESampler` (already installed) | TPE handles correlated params with `multivariate=True`, convergence tracking, pruning |
| Expected max SR for DSR | Custom E[max SR] formula | `expected_max_sr()` in `psr.py` (already exists) | Bailey & Lopez de Prado approximation already implemented and tested |
| IC computation per parameter | Custom Spearman | `scipy.stats.spearmanr` (already in ic.py pattern) | Project standard, handles ties correctly |
| trial_registry upsert | Custom INSERT | `log_trials_to_registry()` from `multiple_testing.py` — extend it or call upsert directly with same ON CONFLICT pattern | Phase 102 already established this pattern |
| IC rolling windows | Custom window splitter | `compute_rolling_ic()` from `ic.py` for reference; non-overlapping split for stability test | ic.py already handles boundary masking, alignment |

**Key insight:** The DSR, expected_max_sr, and compute_psr functions in `psr.py` are fully compatible with IC-derived pseudo-Sharpes. The rolling IC series IS the "returns series" for DSR purposes — a series of IC values measured in non-overlapping windows. No adaptation of psr.py is needed.

---

## Common Pitfalls

### Pitfall 1: sweep_id Does Not Exist in trial_registry Schema (Phase 102)

**What goes wrong:** Phase 102 creates `trial_registry` WITHOUT a `sweep_id` column. Phase 105 requires grouping all parameter variants of the same indicator by `sweep_id`.
**Why it happens:** `sweep_id` is a Phase 105 requirement (IND-13) that was not in the Phase 102 spec.
**How to avoid:** Phase 105-01 must include an Alembic migration that adds `sweep_id UUID` (nullable, so existing rows get NULL) and `n_sweep_trials INTEGER` to `trial_registry`. Also add `dsr_adjusted_sharpe DOUBLE PRECISION` column.
**Warning signs:** "column sweep_id does not exist" error when writing to trial_registry.

### Pitfall 2: IC as Returns Framing for DSR

**What goes wrong:** `compute_dsr()` in `psr.py` expects a returns series with enough observations (>= 30) to compute PSR. If you pass a single IC value instead of a rolling IC series, you get n=1 which fails the guard.
**Why it happens:** IC is usually a scalar summary (mean IC over the train window). DSR needs a series.
**How to avoid:** Use the rolling IC series (63-bar window, dropping NaN) as the "returns series" for DSR. For a 1D indicator with 2 years of data, this gives ~(730-63) = ~667 rolling IC values — well above the 30-observation floor in `compute_psr()`.
**Warning signs:** "PSR: n=1 < 30. Estimate is unreliable — returning NaN." in logs.

### Pitfall 3: MACD Parameter Constraint (fast < slow)

**What goes wrong:** Optuna TPE may suggest `fast=20, slow=12` (fast > slow). MACD is undefined in this case.
**Why it happens:** TPE treats fast and slow as independent by default unless `multivariate=True` and a constraint is added.
**How to avoid:** Add `if fast >= slow: raise optuna.exceptions.TrialPruned()` at the top of the MACD objective. Optuna will record the trial as pruned and exclude it from sampling guidance. Also use `multivariate=True` for correlated parameter sweeps.
**Warning signs:** NaN IC values for MACD trials where fast >= slow.

### Pitfall 4: Database Bloat from Storing All Trials

**What goes wrong:** If 30 indicators x 200 avg param combinations x 50 assets x 5 timeframes = 15,000,000 rows in `trial_registry`. At ~500 bytes/row with indexes, this is ~7.5 GB.
**Why it happens:** The trial_registry was designed for Phase 102 IC sweep (one row per indicator-asset-tf). Parameter sweeps multiply this by 200x.
**How to avoid:**
  - Store only `horizon=1` AND `return_type='arith'` (per Phase 102 log_trials_to_registry pattern that already filters to this scope).
  - Run parameter sweeps only for surviving indicators (Phase 103-104 FDR survivors), not all 20+ indicators against all 50+ assets. A realistic scope: 10-15 survivors x 100 avg param combinations x 10-15 key assets x 3 TFs = 45,000-67,500 rows. This is fine.
  - For Phase 105 development, run on 2-3 assets first to estimate row volume before full sweep.
**Warning signs:** `trial_registry` growing beyond 500K rows after a first test run.

### Pitfall 5: GridSampler float/int Type Mismatch

**What goes wrong:** `GridSampler(search_space={"window": [5, 10, 14, 20]})` returns integers from the grid, but inside the objective you call `trial.suggest_int("window", 5, 20)`. Optuna's GridSampler overrides the suggest call — but if the value is stored as `float` in the search_space dict (e.g., `[5.0, 10.0]`), the returned value is a float, not int. Passing a float to a function expecting an int (e.g., `pd.Series.rolling(window)`) raises TypeError.
**Why it happens:** Python `range()` returns ints; `numpy.arange()` may return floats depending on dtype.
**How to avoid:** Always build GridSampler search spaces with explicit Python `int` lists: `list(range(5, 31))` not `np.arange(5, 31).tolist()`.
**Warning signs:** `TypeError: window must be an integer` inside indicator computation.

### Pitfall 6: Optuna `nan` vs `TrialPruned` Confusion

**What goes wrong:** Returning `float("nan")` from the objective causes Optuna to mark the trial as FAILED. Failed trials are excluded from TPE sampling updates but still counted toward `n_trials`. If many parameter combinations are invalid (e.g., MACD fast > slow), the study wastes budget on failures.
**Why it happens:** `float("nan")` is treated as a failed trial by Optuna.
**How to avoid:** For expected-invalid combinations (constraint violations), use `raise optuna.exceptions.TrialPruned()`. For unexpected failures (data too short), use `return float("nan")` — these shouldn't happen if min_obs guards are correct.
**Warning signs:** Many FAILED trials in `study.trials` alongside COMPLETE trials.

### Pitfall 7: MACD and BBANDS Have Large Grid Sizes — Use Appropriate n_trials

**What goes wrong:** MACD with fast=2..15, slow=10..50, signal=3..12 has 11x41x10 = 4,510 grid combinations. Running 4,510 IC computations for every asset/tf combination is too slow.
**Why it happens:** Multi-parameter indicators have exponentially larger search spaces.
**How to avoid:** Use TPESampler with n_trials=100 for spaces > 200 combinations. 100 trials typically samples ~2-3% of a 4,510-cell grid but finds near-optimal parameters within ~50 trials (empirically from run_optuna_sweep.py's grid_comparison at 99% threshold in ~trials_to_near_optimal). For multi-parameter indicators, 100 trials is sufficient.
**Warning signs:** Phase 105 sweep taking more than 10 minutes per indicator.

---

## Code Examples

### Running a Grid Sweep for RSI (small space)

```python
# Source: based on run_optuna_sweep.py pattern + GridSampler from GitHub optuna source
import optuna
import uuid
from scipy.stats import spearmanr
import numpy as np

def run_rsi_sweep(close, high, low, volume, fwd_ret, train_start, train_end, asset_id, tf):
    sweep_id = str(uuid.uuid4())
    search_space = {"window": list(range(5, 31))}   # 26 int values
    sampler = optuna.samplers.GridSampler(search_space, seed=42)
    study = optuna.create_study(direction="maximize", sampler=sampler)

    def objective(trial):
        window = trial.suggest_int("window", 5, 30)   # GridSampler overrides to grid values
        feat = rsi(close, window=window)   # from indicators_extended.py
        ic = _ic_in_window(feat, fwd_ret, train_start, train_end)
        return ic if ic is not None else float("nan")

    study.optimize(objective, n_trials=len(search_space["window"]))

    # Collect results
    results = [
        {"sweep_id": sweep_id, "indicator_name": "rsi",
         "param_set": str(t.params), "ic_observed": t.value,
         "asset_id": asset_id, "tf": tf}
        for t in study.trials if t.value is not None
    ]
    return results, sweep_id, study.best_params
```

### plateau_score() Implementation Pattern

```python
# Source: verified logic, not from external library
def plateau_score(
    results: list[dict],   # dicts with "params" (dict) and "ic" (float)
    best_params: dict,
    threshold: float = 0.80,
    neighbor_radius: int = 2,
) -> float:
    best_ic = max(r["ic"] for r in results if r.get("ic") is not None)
    if best_ic <= 0:
        return 0.0
    min_ic = threshold * best_ic
    param_keys = list(best_params.keys())

    neighbors = []
    for r in results:
        p = r["params"]
        ic = r.get("ic")
        if ic is None:
            continue
        # For integer params: Manhattan distance per-parameter <= neighbor_radius
        if all(abs(p[k] - best_params[k]) <= neighbor_radius for k in param_keys):
            neighbors.append(ic)

    if not neighbors:
        return 0.0
    return float(sum(1 for ic in neighbors if ic >= min_ic) / len(neighbors))
```

### rolling_stability_test() Signature and Core Loop

```python
# Source: based on ic.py _compute_single_ic pattern + spearmanr from existing usage
import numpy as np
from scipy.stats import spearmanr

def rolling_stability_test(
    feature_series: pd.Series,   # precomputed for best_params
    fwd_ret: pd.Series,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    n_windows: int = 5,
    max_sign_flips: int = 1,
    max_ic_cv: float = 2.0,
    min_obs_per_window: int = 50,
) -> dict:
    # Split index into n_windows equal non-overlapping time ranges
    full_range = feature_series[
        (feature_series.index >= train_start) & (feature_series.index <= train_end)
    ].index
    window_boundaries = np.array_split(np.arange(len(full_range)), n_windows)

    ics = []
    for idxs in window_boundaries:
        if len(idxs) < min_obs_per_window:
            continue
        w_start = full_range[idxs[0]]
        w_end = full_range[idxs[-1]]
        feat_w = feature_series.loc[w_start:w_end]
        fwd_w = fwd_ret.reindex(feat_w.index).dropna()
        aligned = pd.concat([feat_w, fwd_w], axis=1).dropna()
        if len(aligned) < min_obs_per_window:
            continue
        ic, _ = spearmanr(aligned.iloc[:, 0], aligned.iloc[:, 1])
        if not np.isnan(ic):
            ics.append(ic)

    if not ics:
        return {"passes": False, "sign_flips": 0, "ic_cv": np.nan,
                "window_ics": [], "n_valid_windows": 0}

    median_ic = float(np.median(ics))
    sign_flips = sum(1 for ic in ics if (ic > 0) != (median_ic > 0))
    ic_mean = float(np.mean(ics))
    ic_std = float(np.std(ics, ddof=1))
    ic_cv = (ic_std / abs(ic_mean)) if abs(ic_mean) > 1e-10 else float("inf")

    passes = (sign_flips <= max_sign_flips) and (ic_cv <= max_ic_cv)
    return {
        "passes": passes,
        "sign_flips": sign_flips,
        "ic_cv": ic_cv,
        "window_ics": ics,
        "n_valid_windows": len(ics),
    }
```

### DSR Over Parameter Sweep Space

```python
# Source: psr.py compute_dsr() API (read directly from source)
from ta_lab2.backtests.psr import compute_dsr
from ta_lab2.analysis.ic import compute_rolling_ic

def compute_dsr_over_sweep(
    feature_best: pd.Series,   # feature values for best parameter set
    fwd_ret: pd.Series,
    all_sweep_ics: list[float],   # IC value for EVERY parameter combination tested
    window: int = 63,
) -> dict:
    """
    Computes DSR for the best parameter set, where N = len(all_sweep_ics).
    Uses rolling IC series as the "returns series" for PSR computation.
    """
    rolling_ic, ic_ir, _ = compute_rolling_ic(feature_best, fwd_ret, window=window)
    rolling_ic_clean = rolling_ic.dropna().values

    if len(rolling_ic_clean) < 30:
        return {"dsr": float("nan"), "n_trials": len(all_sweep_ics), "note": "insufficient_data"}

    # Exact mode: use observed IC distribution across all parameter trials
    valid_ics = [ic for ic in all_sweep_ics if ic is not None and not np.isnan(ic)]
    dsr_value = compute_dsr(
        best_trial_returns=rolling_ic_clean,
        sr_estimates=valid_ics,
    )
    return {
        "dsr": dsr_value,
        "n_trials": len(valid_ics),
        "rolling_ic_n": len(rolling_ic_clean),
    }
```

---

## Indicator Parameter Spaces

Reference ranges for Phase 105 sweeps (verified against Phase 103 research and standard TA literature):

### Phase 103 Traditional TA Indicators

| Indicator | Parameters | Default | Sweep Range | Grid Size | Sampler |
|-----------|-----------|---------|-------------|-----------|---------|
| Williams %R | window | 14 | 7..28 step 1 | 22 | Grid |
| CCI | window | 20 | 10..30 step 2 | 11 | Grid |
| Elder Ray | ema_period | 13 | 8..21 step 1 | 14 | Grid |
| Force Index | smooth_period | 13 | 5..20 step 1 | 16 | Grid |
| VWAP | window | 14 | 7..28 step 1 | 22 | Grid |
| Hurst | rolling_window | 100 | 60..150 step 10 | 10 | Grid |
| VIDYA | cmo_period, vidya_period | 9, 9 | 5..20 each, step 1 | 256 | TPE |
| CMF | window | 20 | 10..30 step 2 | 11 | Grid |
| Chaikin Osc | fast_ema, slow_ema | 3, 10 | (3..6, 8..15) | 28 | Grid |
| RSI | window | 14 | 5..30 step 1 | 26 | Grid |
| MACD | fast, slow, signal | 12, 26, 9 | (2..15, 10..50, 3..12) | 4510 | TPE |
| BBANDS | window, std | 20, 2.0 | (5..50, 1.0..3.0 step 0.25) | 414 | TPE |
| Stochastic | k_period, d_period | 14, 3 | (5..25, 2..6) | 105 | Grid |
| Keltner | ema_period, atr_period | 20, 10 | (10..30, 5..20) | 240 | TPE |
| Ichimoku | tenkan, kijun, senkou_b | 9, 26, 52 | (6..15, 18..35, 42..62) | 360 | TPE |
| MFI | window | 14 | 7..28 step 1 | 22 | Grid |
| FRAMA | period | 16 | 8..26 step 2 | 10 | Grid |
| ADX | period | 14 | 7..28 step 1 | 22 | Grid |

### Phase 104 Crypto-Native Indicators

| Indicator | Parameters | Default | Sweep Range | Notes |
|-----------|-----------|---------|-------------|-------|
| Volume-OI regime classifier | window | 20 | 10..30 step 2 | Categorical 6-regime output; IC on label |
| Liquidation pressure proxy | window | 14 | 7..21 step 1 | OI + funding based |
| OI concentration ratio | window, threshold | varies | TBD after Phase 104 complete | Depends on Phase 104 implementation |
| OI Z-score | window | 20 | 10..50 step 5 | Multiple windows may already be tested |

Note: Phase 104 indicators were designed with "Claude's discretion" on z-score windows. Phase 105 must first inspect what parameters were actually implemented before defining sweep ranges.

---

## DSR Application: Conceptual Framing

The key intellectual question for IND-15 is: what counts as "N trials" for DSR?

**Answer (HIGH confidence from psr.py review):** N = total number of distinct parameter combinations evaluated in the sweep for that indicator × asset × tf triplet. If you sweep RSI with 26 window values, N=26. If you sweep MACD with 100 Optuna trials (from a 4,510-cell space), N=100 (not 4,510 — you only tested 100 combinations).

**The `sr_estimates` mode vs `n_trials` mode:**
- Use `sr_estimates` mode (exact) when you have ALL IC values for all combinations tested. This is always the case when you store results in `trial_registry`.
- Use `n_trials` mode (approximate) only as a fallback. The approximation assumes IC ~ N(0,1) which understates DSR penalty for correlated parameters.

**The "Sharpe" in "DSR-adjusted Sharpe":** For IND-15, "raw Sharpe" = IC_IR (IC / std(IC) over rolling windows) for the best parameter set. "DSR-adjusted Sharpe" = `compute_dsr(rolling_ic_best, sr_estimates=all_sweep_ics)`, which is a probability in [0,1] (the DSR value is a PSR — probability the true Sharpe exceeds the expected max Sharpe over N trials). Store both numbers.

---

## Relationship to Existing run_optuna_sweep.py

| Aspect | run_optuna_sweep.py (existing) | Phase 105 param_optimizer.py (new) |
|--------|-------------------------------|--------------------------------------|
| Objective | LightGBM OOS accuracy (cross-validation) | Spearman IC (in-sample, train window) |
| Parameters | ML hyperparams (n_estimators, num_leaves, etc.) | Indicator parameters (window, std, etc.) |
| Sampler | TPESampler(seed=42) | GridSampler OR TPESampler based on grid size |
| Storage | ml_experiments table via ExperimentTracker | trial_registry table with sweep_id |
| CV method | PurgedKFold (5 folds) | Single train window (IC sweep pattern) |
| Returns series | LGBMClassifier predictions vs true labels | Rolling IC series |
| DSR | Not computed | compute_dsr() from psr.py on rolling IC |

**Conclusion:** `run_optuna_sweep.py` cannot be reused or extended. Build `param_optimizer.py` fresh. The Optuna study setup pattern (create_study, samplers, seed=42 convention, in-memory study) is directly reusable as a reference.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Fixed parameter (e.g., RSI=14 always) | Sweep over range, select from plateau | More robust indicator; avoids cherry-picking |
| Single-period IC | Rolling IC + CV | Catches regime-dependent indicators |
| Raw Sharpe of best parameter | DSR-adjusted Sharpe | Corrects for selection bias across parameter space |
| Grid search only | Grid for small spaces, Bayesian TPE for large | 10-100x faster for multi-parameter indicators |
| Store only winning params | Store all trial results with sweep_id | Enables post-hoc plateau analysis and auditing |

**Deprecated/outdated:**
- `analysis/parameter_sweep.py`'s `grid()` and `random_search()`: Uses backtest Sharpe as objective. Not applicable to IC-based optimization. Can coexist but Phase 105 builds its own module.

---

## Schema Changes Required

Phase 105 must add these columns to `trial_registry` via a new Alembic migration:

```sql
-- Phase 105 migration: add sweep_id and DSR columns to trial_registry
ALTER TABLE trial_registry
    ADD COLUMN sweep_id UUID,                         -- groups all params in one sweep run
    ADD COLUMN n_sweep_trials INTEGER,                -- total params tested in this sweep
    ADD COLUMN plateau_score DOUBLE PRECISION,        -- fraction of neighbors within 80% of peak IC
    ADD COLUMN rolling_stability_passes BOOLEAN,     -- result of rolling_stability_test()
    ADD COLUMN ic_cv DOUBLE PRECISION,                -- IC coefficient of variation across windows
    ADD COLUMN sign_flips SMALLINT,                  -- count of IC sign flips across windows
    ADD COLUMN dsr_adjusted_sharpe DOUBLE PRECISION; -- DSR output (probability vs E[max_SR])

CREATE INDEX ix_trial_registry_sweep_id ON trial_registry (sweep_id)
    WHERE sweep_id IS NOT NULL;
```

**Migration chain:** Chain from Phase 102's `u4v5w6x7y8z9` migration (if that runs before Phase 105). All new columns are nullable to preserve backward compatibility with Phase 102 backfill rows.

---

## Open Questions

1. **Phase 104 indicator parameter schemas are undefined**
   - What we know: Phase 104 indicators were specified with "Claude's discretion" on z-score windows and formula parameters.
   - What's unclear: What parameters were actually implemented (depends on Phase 104 execution, not yet done).
   - Recommendation: Phase 105-03 (execute sweeps) should first inspect `dim_feature_registry` to enumerate Phase 104 survivors and their parameter names before defining sweep ranges.

2. **IC as proxy for Sharpe in DSR framing**
   - What we know: `compute_dsr()` in psr.py accepts a returns series and produces PSR. Rolling IC is a plausible proxy for "returns" of the indicator signal.
   - What's unclear: Whether the PSR formula's non-normality correction (skewness, Pearson kurtosis) meaningfully applies to IC distributions, which are approximately normal but bounded.
   - Recommendation: Use IC t-stat series (multiply each rolling IC value by sqrt(n_obs_in_window)) for better approximation to Sharpe semantics. Document the approximation in code.

3. **survivor list from Phases 103-104 not yet known**
   - What we know: FDR at 5% is the criterion; 20 Phase 103 indicators + N Phase 104 indicators enter.
   - What's unclear: How many will survive (could be 5, could be 18).
   - Recommendation: Phase 105-03 plan should be conditional on the survivor count. If only 3-5 indicators survive, the full grid is tractable for all of them.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/backtests/psr.py` — full read; `compute_dsr`, `expected_max_sr`, `compute_psr` API confirmed
- `src/ta_lab2/scripts/ml/run_optuna_sweep.py` — full read; Optuna TPESampler usage, study setup, in-memory study pattern
- `src/ta_lab2/analysis/ic.py` — partial read; `compute_rolling_ic`, `_compute_single_ic` signatures confirmed
- `src/ta_lab2/analysis/parameter_sweep.py` — full read; confirmed it uses Sharpe (not IC), not reusable
- `.planning/phases/102-indicator-research-framework/102-01-PLAN.md` — trial_registry schema confirmed (no sweep_id column)
- `.planning/phases/103-traditional-ta-expansion/103-RESEARCH.md` — indicator parameter defaults confirmed
- GitHub `optuna/optuna/samplers/_grid.py` — GridSampler constructor, `GridValueType = Union[str, float, int, bool, None]`, no quantization enforcement, `_n_min_trials` = cartesian product size
- Bailey & Lopez de Prado 2014 "The Deflated Sharpe Ratio" (SSRN 2460551) — DSR formula mechanics

### Secondary (MEDIUM confidence)
- WebSearch: Optuna 4.8.0 samplers overview — CMA-ES vs TPE vs GridSampler use cases
- WebSearch: QuantBeckman robust optimization protocol — "broad plateau" vs "brittle peak" framing, rank blending for multi-metric parameter selection
- WebSearch: Walk-forward IC stability — IC-IR (IC/std(IC)) as temporal stability metric; non-overlapping windows to avoid correlated IC estimates

### Tertiary (LOW confidence)
- Bailey & Lopez de Prado "Probability of Backtest Overfitting" — conceptually relevant but N_trials framing in PBO differs from DSR over parameter space; not directly applicable

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed installed, all APIs verified against source
- Architecture: HIGH — patterns derived directly from existing codebase (run_optuna_sweep.py, ic.py, psr.py)
- Pitfalls: HIGH for codebase-specific pitfalls (sweep_id missing, nan vs pruned); MEDIUM for DSR framing
- Parameter spaces: HIGH for Phase 103 indicators (research already done); LOW for Phase 104 (implementation not yet done)

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (Optuna 4.x API is stable; project infrastructure stable)
