# Phase 42: Strategy Bake-Off - Research

**Researched:** 2026-02-24
**Domain:** Strategy evaluation, walk-forward backtesting, composite scoring, selection documentation
**Confidence:** HIGH (all findings from direct codebase inspection)

---

## Summary

Phase 42 is a high-leverage, mostly-orchestration phase. The v0.9.0 research tooling is fully built and battle-tested. The primary work is writing the bake-off orchestrator that wires together existing components in the correct order, implementing the composite scoring system (which is new logic), and producing the formal scorecard document. No new analytical algorithms need to be invented.

The existing infrastructure covers: IC evaluation (ic.py + run_ic_eval.py CLI), purged K-fold and CPCV splitters (cv.py), PSR/DSR computation (psr.py + compute_psr.py CLI), vectorbt backtesting (vbt_runner.py + backtest_from_signals.py), cost models (costs.py, CostModel dataclass), and the experiment runner for experimental features (runner.py). DB persistence is handled by cmc_ic_results, cmc_backtest_runs/trades/metrics, and psr_results tables.

What does NOT exist and must be built: (1) a walk-forward bake-off orchestrator that sweeps all signal types x all assets x all cost scenarios using PurgedKFold + CPCV; (2) a composite scoring module that blends Sharpe, Max DD, PSR, and turnover with sensitivity analysis across weighting schemes; (3) ensemble/blending logic for the contingency path; (4) a scorecard generator producing the markdown report with charts; (5) new DB tables for bake-off results (strategy_bakeoff_results or equivalent).

**Primary recommendation:** Structure the phase as 5 sequential plans: (1) IC sweep across all 112 features + experimental features, (2) walk-forward backtest orchestration, (3) composite scoring + sensitivity analysis, (4) strategy selection + ensemble contingency, (5) scorecard generation + documentation.

---

## Standard Stack

All libraries are already in the project's dependency set. No new installs required.

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| vectorbt | 0.28.1 | Backtesting engine | Already integrated, CostModel supports bps fees/slippage/funding |
| scikit-learn | current | PurgedKFoldSplitter/CPCVSplitter inherit BaseCrossValidator | Already in cv.py |
| scipy | current | PSR/DSR formulas (skew, kurtosis, norm.cdf) | Already in psr.py |
| pandas | current | All data operations | Project standard |
| numpy | current | Vectorized computation | Project standard |
| plotly | current | Charts for scorecard | Already used in ic.py visualizations |
| matplotlib | optional | equity_plot in reports.py | Optional dependency, import-guarded |
| sqlalchemy | current | DB persistence | Project standard, NullPool for scripts |

### Supporting (already installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| scipy.stats.false_discovery_control | current | BH correction | Already used in ExperimentRunner |
| scipy.stats.spearmanr | current | Spearman IC | Already used in ic.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| vectorbt | backtrader | vectorbt already integrated with CostModel + PSR pipeline; don't switch |
| PurgedKFoldSplitter (custom) | mlfinlab | Deliberately avoided — mlfinlab discontinued with known bug #295 |
| manual composite score | alphalens | alphalens is Quantopian-era; existing IC tooling is more complete for this project |

**Installation:**
```bash
# Nothing new to install — all dependencies already present
```

---

## Architecture Patterns

### Recommended Project Structure for New Files
```
src/ta_lab2/
├── backtests/
│   ├── bakeoff_orchestrator.py   # NEW: walk-forward CV orchestrator for bake-off
│   └── composite_scorer.py       # NEW: weighted composite scoring + sensitivity analysis
├── scripts/
│   ├── backtests/
│   │   └── run_bakeoff.py        # NEW: CLI entry point for full bake-off run
│   └── analysis/
│       └── run_ic_sweep.py       # NEW: batch IC across all assets x all tfs x all features
reports/
└── bakeoff/
    └── BAKEOFF_SCORECARD.md      # NEW: formal markdown scorecard (generated artifact)
sql/
└── backtests/
    └── 074_strategy_bakeoff_results.sql  # NEW: bake-off composite scores table
```

### Pattern 1: Bake-Off Orchestration Pipeline

**What:** A sequential pipeline that runs IC sweep, then walk-forward backtests, then scoring, then selection
**When to use:** The main bake-off execution entry point

```python
# Conceptual structure — new bakeoff_orchestrator.py
class BakeoffOrchestrator:
    """
    Orchestrates the full bake-off pipeline:
    1. IC sweep: batch_compute_ic across all feature columns x all assets x all tfs
    2. Feature ranking: sort by IC-IR, flag top candidates
    3. Walk-forward backtest: PurgedKFold + CPCV for each signal type
    4. Cost matrix: 3 slippage levels x spot/perps x base fee tier
    5. PSR/DSR per fold combination
    6. Regime-conditional analysis
    7. Composite scoring with sensitivity analysis
    8. Ensemble attempt if no strategy passes gates
    9. Final selection + persist results
    """
    def run(self, strategy_configs: list[dict], cost_matrix: list[CostModel], ...):
        ...
```

### Pattern 2: Walk-Forward with PurgedKFold + CPCV (10-fold design)

**What:** The CONTEXT.md locks in: 10-fold purged K-fold, 20-bar embargo, both fixed-param and re-optimized per fold

**Implementation notes from cv.py:**
- `PurgedKFoldSplitter(n_splits=10, t1_series=t1, embargo_frac=0.02)` gives 20-bar embargo on 1000-bar history (1000 * 0.02 = 20)
- `CPCVSplitter(n_splits=10, n_test_splits=2, t1_series=t1, embargo_frac=0.02)` gives C(10,2)=45 path combinations for PBO

```python
# Source: src/ta_lab2/backtests/cv.py (verified)
from ta_lab2.backtests.cv import PurgedKFoldSplitter, CPCVSplitter

# t1_series: index=entry_ts, values=exit_ts (label-end timestamps)
# For 1D crypto with 1-bar hold: t1 = index.shift(1) — entry on close, exit next close
pkf = PurgedKFoldSplitter(
    n_splits=10,
    t1_series=t1_series,   # REQUIRED — no default
    embargo_frac=0.02      # 20/1000 bars for 1D with 10 years history
)
cpcv = CPCVSplitter(
    n_splits=10,
    n_test_splits=2,       # C(10,2) = 45 combinations
    t1_series=t1_series,
    embargo_frac=0.02
)
```

**CRITICAL:** The t1_series (label-end timestamps) must be constructed correctly per signal type. For EMA crossover with 1-bar hold: t1 = signal_ts + 1 bar. For ATR breakout with variable holds: t1 = actual exit_ts from backtest or estimated exit_ts using ATR channel exit rule.

### Pattern 3: Cost Matrix Construction

**What:** The CONTEXT.md locks in: Kraken maker 0.16%, taker 0.26%, slippage at 5/10/20 bps, spot + perps with funding

```python
# Source: src/ta_lab2/backtests/costs.py (verified)
from ta_lab2.backtests.costs import CostModel

# Spot cost matrix
COST_MATRIX_SPOT = [
    CostModel(fee_bps=16, slippage_bps=5),   # maker + 5bps slip
    CostModel(fee_bps=16, slippage_bps=10),  # maker + 10bps slip
    CostModel(fee_bps=16, slippage_bps=20),  # maker + 20bps slip
    CostModel(fee_bps=26, slippage_bps=5),   # taker + 5bps slip
    CostModel(fee_bps=26, slippage_bps=10),  # taker + 10bps slip
    CostModel(fee_bps=26, slippage_bps=20),  # taker + 20bps slip
]

# Perps cost matrix: add funding_bps_day
# Historical BTC/ETH avg funding ~0.01%/8h = 0.03%/day = 3 bps/day
# Use fixed 3.0 if historical data not in DB, pull from cmc_funding_rates if available
COST_MATRIX_PERPS = [
    CostModel(fee_bps=16, slippage_bps=5, funding_bps_day=3.0),
    # ... full 6 spot combos x 1 funding rate = 6 perps scenarios
]
```

### Pattern 4: Composite Scoring with Sensitivity Analysis

**What:** New module — does not exist. Must be built.

```python
# Source: new composite_scorer.py
WEIGHT_SCHEMES = {
    "balanced":     {"sharpe": 0.35, "max_dd": 0.30, "psr": 0.25, "turnover": 0.10},
    "risk_focus":   {"sharpe": 0.25, "max_dd": 0.45, "psr": 0.20, "turnover": 0.10},
    "quality_focus":{"sharpe": 0.30, "max_dd": 0.25, "psr": 0.35, "turnover": 0.10},
    "low_cost":     {"sharpe": 0.30, "max_dd": 0.25, "psr": 0.25, "turnover": 0.20},
}
# V1 hard gates (always applied before scoring)
V1_GATES = {"min_sharpe": 1.0, "max_drawdown": -0.15}  # DD is negative fraction

def compute_composite_score(metrics_df: pd.DataFrame, weights: dict) -> pd.Series:
    """Normalize each metric to [0,1], apply weights, sum."""
    ...
```

**Sensitivity robustness check:** A strategy must rank in top-2 under at least 3 of 4 weighting schemes to be considered robustly selected.

### Pattern 5: IC Sweep (Batch Mode)

**What:** The existing batch_compute_ic + run_ic_eval CLI handles per-asset per-feature. For the bake-off's broad sweep across ALL assets x ALL tfs x ALL 112 features, a new orchestrator script is needed.

```python
# Source: src/ta_lab2/analysis/ic.py (verified)
from ta_lab2.analysis.ic import batch_compute_ic, save_ic_results

# batch_compute_ic operates on a single asset+tf+window
# The sweep script must loop: assets x tfs x train_windows
# For broad discovery: use full history as train window (no CV split)
# For walk-forward IC: use each CV fold's train split

# Existing CLI can be called per-asset, but a batch script is more efficient:
# python -m ta_lab2.scripts.analysis.run_ic_eval --asset-id 1 --tf 1D --all-features ...
```

### Pattern 6: Experimental Feature as Signal Strategy

**What:** The CONTEXT.md requires the 7 experimental features (features.yaml) to be evaluated as signal candidates, not just ranked by IC. The path is: ExperimentRunner computes IC, if IC > threshold then the feature value itself becomes a signal (long if feature > 0, short if feature < 0, or quantile-ranked thresholds).

```python
# Source: src/ta_lab2/experiments/runner.py (verified)
# ExperimentRunner.run() returns IC results per asset/horizon
# To use a feature as a signal: threshold its values into {-1, 0, +1} positions

def feature_to_signal(feature_series: pd.Series, threshold: float = 0.0):
    """Convert feature values to long/flat/short positions."""
    return np.sign(feature_series - threshold)  # {-1, 0, 1}
```

### Anti-Patterns to Avoid

- **In-sample parameter selection:** Never select final parameters (EMA periods, RSI thresholds) based on in-sample backtest Sharpe. Parameters must be chosen via walk-forward CV — the CONTEXT.md is explicit about this.
- **Computing t1_series incorrectly:** The CPCVSplitter and PurgedKFoldSplitter REQUIRE t1_series to have index=label_start_ts, values=label_end_ts. If label_end is misset, purge doesn't work and you get look-ahead bias.
- **PSR with too-few bars:** psr.py warns when n < 30 and returns NaN when n < 30. Each CV fold on 1D data will have ~330 bars — this is fine. But short-TF or small assets may have sparse data causing PSR degradation.
- **Testing the benchmark Sharpe in annual vs per-bar units:** `psr.py`'s `compute_psr(returns, sr_star=0.0)` expects sr_star in PER-BAR units. compute_psr.py converts annual Sharpe using `sr_star_per_bar = sr_star_annual / sqrt(365)`. Do not pass an annual Sharpe directly.
- **Using metrics.py psr_placeholder for selection:** `metrics.py` contains `psr_placeholder()` which is a sigmoid stub, NOT the real PSR. Always use `backtests/psr.py:compute_psr()`.
- **Building a composite scorer on in-sample metrics:** All scoring must use OOS (test fold) metrics only. Training-fold performance is not informative.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Walk-forward CV splits | Custom date slicer | `PurgedKFoldSplitter` from `backtests/cv.py` | Handles purge + embargo correctly; sklearn-compatible |
| Combinatorial CV for PBO | Custom combinations | `CPCVSplitter` from `backtests/cv.py` | Pre-computes all C(n,k) combinations; purge-aware |
| PSR computation | Custom formula | `compute_psr` from `backtests/psr.py` | Pearson kurtosis (fisher=False) already correct; documented pitfall with fisher kurtosis |
| DSR (deflated SR) | Custom multi-test correction | `compute_dsr` from `backtests/psr.py` | Handles both exact mode (sr_estimates list) and approximate mode (n_trials) |
| IC computation | Manual Spearman | `batch_compute_ic` from `analysis/ic.py` | Boundary masking, rolling IC-IR, turnover, regime breakdown all included |
| Backtest execution | Custom loop | `run_vbt_on_split` from `backtests/vbt_runner.py` | Next-bar execution, CostModel integration, vectorbt compat fixes already applied |
| Cost application | Manual fees | `CostModel` from `backtests/costs.py` | Already converts bps to fractions, handles funding_bps_day for perps |
| IC persistence | Custom INSERT | `save_ic_results` from `analysis/ic.py` | ON CONFLICT DO NOTHING/UPDATE, numpy scalar normalization, correct column mapping |
| Regime-conditional IC | Custom groupby | `compute_ic_by_regime` from `analysis/ic.py` | Handles sparse regime subsets, falls back to full-sample gracefully |
| Multi-strategy orchestration | Custom loops | `run_multi_strategy` from `backtests/orchestrator.py` | Per-strategy leaderboards, tidy results DataFrame |

**Key insight:** The algorithmic infrastructure is complete. Phase 42's value is in the orchestration glue code, the composite scoring logic, and the formal documentation — not new algorithms.

---

## Common Pitfalls

### Pitfall 1: Leaking Forward Returns into IC Evaluation
**What goes wrong:** Computing IC by slicing the dataset first, then computing forward returns on the slice. The last `horizon` bars in the slice will have forward returns that are NaN due to the slice boundary, not because of look-ahead prevention. This understates the IC near the window boundary.
**Why it happens:** Intuitive approach is to slice, then compute. The correct approach is compute forward returns on the full series first, then slice.
**How to avoid:** Always use `compute_forward_returns(full_close, horizon)` before slicing to train window. The `compute_ic()` function in `ic.py` enforces this contract — do NOT pre-slice before passing to `compute_ic`.
**Warning signs:** IC drops sharply near the evaluation window end; the function logs "boundary masking applied."

### Pitfall 2: t1_series Construction Error in CV Splitters
**What goes wrong:** The PurgedKFoldSplitter requires `t1_series.index = label_start_ts` and `t1_series.values = label_end_ts`. Getting this backwards or using wrong timestamps causes incorrect purge, allowing look-ahead.
**Why it happens:** API is similar to sklearn but semantics differ. t1_series is a REQUIRED constructor argument — no silent default.
**How to avoid:** For 1-bar holding period signals: `t1 = pd.Series(index.shift(1), index=index)`. For multi-bar holds: t1 must reflect the actual label-end timestamp. Verify by checking that `t1.index.is_monotonic_increasing` (cv.py raises ValueError otherwise).
**Warning signs:** `ValueError: t1_series index must be monotonically increasing` means index/value are swapped.

### Pitfall 3: PSR fisher=False Requirement
**What goes wrong:** Using `scipy.stats.kurtosis(arr, fisher=True)` (the default) instead of `fisher=False` in the PSR formula causes systematically wrong PSR values. Normal data has Pearson kurtosis=3 (fisher=False), not Fisher kurtosis=0 (fisher=True). The PSR formula from Bailey & Lopez de Prado uses Pearson kurtosis.
**Why it happens:** scipy defaults to Fisher (excess) kurtosis. The PSR formula's term `(gamma_4 - 1)/4` assumes Pearson kurtosis.
**How to avoid:** Always use `compute_psr()` from `backtests/psr.py` — the correct convention is already enforced there with `kurtosis(arr, fisher=False)`. Never call `compute_psr` with pre-computed kurtosis from scipy's default.
**Warning signs:** PSR values near 0.5 for all strategies regardless of Sharpe ratio suggests the kurtosis term is cancelling out.

### Pitfall 4: Windows UTF-8 SQL File Reading
**What goes wrong:** `UnicodeDecodeError` when executing SQL migration files that contain UTF-8 box-drawing characters (═══) in comments.
**Why it happens:** Windows default encoding is cp1252; SQL files may use box-drawing chars in header comments.
**How to avoid:** Always `open(sql_file, encoding='utf-8')` when reading SQL on Windows. Already documented in MEMORY.md.

### Pitfall 5: tz-aware Timestamp Series.values on Windows
**What goes wrong:** `series.values` on a tz-aware datetime Series returns tz-NAIVE `numpy.datetime64`, causing `TypeError` when the CV splitters do timestamp comparisons.
**Why it happens:** Known Windows platform behavior. cv.py already handles this by using pandas comparison operators (`.to_numpy()` after pandas-native comparison) instead of numpy datetime comparisons.
**How to avoid:** New walk-forward code should use `pd.to_datetime(ts, utc=True)` and pandas-native comparisons, not `.values` on tz-aware timestamps. Use `.tolist()` or `.tz_localize("UTC")` patterns as documented in MEMORY.md.

### Pitfall 6: Data Sparsity Across Broad Asset/TF Discovery
**What goes wrong:** The CONTEXT.md requires evaluating across ALL assets and ALL timeframes. Many non-BTC/ETH assets have sparse histories. Short TFs (1H, 4H) for small assets may have fewer than 100 bars — PSR will warn/return NaN, and IC computation will fail the min_obs=20 gate.
**Why it happens:** The broad discovery scope is intentional (let data reveal surprises) but the tooling requires minimum data density.
**How to avoid:** Filter asset+TF combinations by minimum row count from `asset_data_coverage` table before running bake-off. A reasonable floor: min 500 bars for IC analysis (rolling_window=63 needs at least 200+ bars to be meaningful), min 300 bars for PSR. Log and skip sparse combinations rather than failing.

### Pitfall 7: vbt CostModel — Only fee and slippage Passed to vectorbt
**What goes wrong:** `CostModel.to_vbt_kwargs()` in `costs.py` only passes `fees` and `slippage` to vectorbt. The `funding_bps_day` field is NOT passed to vectorbt — it must be applied manually as a per-day P&L deduction on positions.
**Why it happens:** vectorbt's `Portfolio.from_signals` does not natively support a daily funding cost on gross position value. The field is tracked in the CostModel for accounting purposes.
**How to avoid:** When running perps backtests, compute funding cost post-hoc: `daily_funding_cost = position_size * funding_bps_day / 1e4`. Deduct from the equity curve before computing metrics. The existing `backtest_from_signals.py` tracks funding_bps_day in `cost_model` JSONB but does not deduct it from equity — this is a known gap.

### Pitfall 8: Strategy Re-Optimization Per Fold vs Fixed Parameters
**What goes wrong:** If parameters are re-optimized per fold using the training data, and the optimization itself leaks (e.g., forward returns from the fold's test period are accessible during optimization), this invalidates the walk-forward.
**Why it happens:** Parameter sweeps using `parameter_sweep.py` or `sweep_grid()` are evaluated on the full DataFrame passed to them. If the DataFrame contains the test fold, optimization sees the future.
**How to avoid:** When running expanding-window re-optimization per fold, ALWAYS slice the DataFrame to the training indices before passing to the parameter search. Verify by checking that the best parameters from the training fold are applied to the test fold WITHOUT re-running the search on test data.

---

## Code Examples

Verified patterns from source code inspection:

### IC Batch Sweep Pattern
```python
# Source: src/ta_lab2/analysis/ic.py + src/ta_lab2/scripts/analysis/run_ic_eval.py
from ta_lab2.analysis.ic import batch_compute_ic, load_feature_series, save_ic_results
from ta_lab2.scripts.sync_utils import get_columns

# Discover all feature columns dynamically (don't hardcode 112 columns)
_NON_FEATURE_COLS = frozenset(
    ["id", "ts", "tf", "close", "open", "high", "low", "volume", "ingested_at"]
)
all_cols = get_columns(engine, "public.cmc_features")
feature_list = [c for c in all_cols if c not in _NON_FEATURE_COLS]

# Load features_df for one asset+tf, then batch compute
ic_results = batch_compute_ic(
    features_df=features_df,
    close=close_series,
    train_start=train_start,
    train_end=train_end,
    feature_cols=feature_list,
    horizons=[1, 2, 3, 5, 10, 20, 60],  # Claude's discretion default matches existing tooling
    return_types=["arith", "log"],
    rolling_window=63,
    tf_days_nominal=1,  # 1 for 1D; look up from DimTimeframe for other TFs
)
```

### Walk-Forward Backtest Loop Pattern
```python
# Source: src/ta_lab2/backtests/cv.py + src/ta_lab2/backtests/vbt_runner.py
from ta_lab2.backtests.cv import PurgedKFoldSplitter
from ta_lab2.backtests.vbt_runner import run_vbt_on_split
from ta_lab2.backtests.splitters import Split
from ta_lab2.backtests.costs import CostModel

# Build t1_series for 1-bar-hold signal
t1_series = pd.Series(
    data=price_df.index[1:].tolist() + [price_df.index[-1]],  # shift by 1 bar
    index=price_df.index,
).sort_index()

pkf = PurgedKFoldSplitter(n_splits=10, t1_series=t1_series, embargo_frac=0.02)

oos_results = []
for fold_idx, (train_idx, test_idx) in enumerate(pkf.split(price_df)):
    train_df = price_df.iloc[train_idx]
    test_df = price_df.iloc[test_idx]

    # Fixed-param: use pre-specified params (no in-fold optimization)
    entries, exits, size = signal_fn(test_df, **fixed_params)

    split = Split(
        name=f"fold_{fold_idx}",
        start=test_df.index[0],
        end=test_df.index[-1],
    )
    row = run_vbt_on_split(
        df=test_df, entries=entries, exits=exits, size=size,
        cost=cost_model, split=split, freq_per_year=365
    )
    oos_results.append(row)
```

### PSR on Walk-Forward OOS Returns
```python
# Source: src/ta_lab2/backtests/psr.py
from ta_lab2.backtests.psr import compute_psr, compute_dsr

# Collect OOS returns across all folds (concatenated)
all_oos_returns = pd.concat(fold_returns_list)

# PSR vs 0 benchmark
psr_value = compute_psr(all_oos_returns.values, sr_star=0.0)

# DSR: adjust for N strategies tested (multiple testing correction)
# sr_estimates = list of Sharpe ratios from all N strategies tested
dsr_value = compute_dsr(
    best_trial_returns=best_strategy_returns.values,
    sr_estimates=all_strategy_sharpes,  # exact mode
)
```

### Composite Score Pattern (to be built)
```python
# Source: new src/ta_lab2/backtests/composite_scorer.py
import pandas as pd
import numpy as np

WEIGHT_SCHEMES = {
    "balanced":     {"sharpe": 0.35, "max_dd_abs": 0.30, "psr": 0.25, "turnover_inv": 0.10},
    "risk_focus":   {"sharpe": 0.25, "max_dd_abs": 0.45, "psr": 0.20, "turnover_inv": 0.10},
    "quality_focus":{"sharpe": 0.30, "max_dd_abs": 0.25, "psr": 0.35, "turnover_inv": 0.10},
    "low_cost":     {"sharpe": 0.30, "max_dd_abs": 0.25, "psr": 0.25, "turnover_inv": 0.20},
}

def compute_composite_score(df: pd.DataFrame, weights: dict) -> pd.Series:
    """
    Normalize OOS metrics to [0,1] and compute weighted composite.
    df must contain: sharpe, max_drawdown (negative), psr, turnover
    Returns composite_score in [0,1].
    """
    scores = pd.DataFrame(index=df.index)
    # Sharpe: higher is better
    scores["sharpe"] = (df["sharpe"] - df["sharpe"].min()) / (df["sharpe"].max() - df["sharpe"].min() + 1e-10)
    # Max DD: less negative is better (invert)
    scores["max_dd_abs"] = (df["max_drawdown"].abs().max() - df["max_drawdown"].abs()) / (df["max_drawdown"].abs().max() - df["max_drawdown"].abs().min() + 1e-10)
    # PSR: higher is better (already [0,1])
    scores["psr"] = df["psr"]
    # Turnover: lower is better (invert)
    scores["turnover_inv"] = (df["turnover"].max() - df["turnover"]) / (df["turnover"].max() - df["turnover"].min() + 1e-10)

    composite = sum(weights[k] * scores[k] for k in weights if k in scores.columns)
    return composite
```

### Scorecard Report Pattern (to be built)
```python
# New script: src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py
# Reads from DB tables, formats markdown with tables + plotly charts (saved as PNG)

# Tables to read:
#   cmc_ic_results — feature rankings
#   cmc_backtest_metrics JOIN psr_results — per-strategy metrics
#   strategy_bakeoff_results — composite scores (new table)
# Output: reports/bakeoff/BAKEOFF_SCORECARD.md
```

---

## Gaps: What Must Be Built

The following components do not exist and must be created in this phase:

### Gap 1: Bake-Off Walk-Forward Orchestrator (HIGH PRIORITY)
**What's missing:** No script exists that runs the full matrix of [signal_types x assets x cost_scenarios x cv_folds] in an automated way using PurgedKFold + CPCV. The existing `run_backtest_signals.py` runs a single signal/asset/date range — it is not a sweep.
**What to build:** `src/ta_lab2/backtests/bakeoff_orchestrator.py` — loops over all combinations, collects OOS metrics per fold, persists to new DB table.
**Estimated complexity:** MEDIUM. The component logic exists in cv.py + vbt_runner.py; the orchestrator is glue code plus result collection.

### Gap 2: Composite Scoring Module (HIGH PRIORITY)
**What's missing:** No composite scoring logic anywhere in the codebase. All existing ranking uses single-metric sorts (MAR, then Sharpe, then CAGR in `orchestrator.py`'s leaderboard).
**What to build:** `src/ta_lab2/backtests/composite_scorer.py` with `compute_composite_score()`, `rank_strategies()`, and `sensitivity_analysis()`.
**Estimated complexity:** LOW. Math is straightforward; the challenge is defining canonical normalization.

### Gap 3: Strategy Bake-Off Results Table (HIGH PRIORITY)
**What's missing:** No DB table stores composite scores, sensitivity analysis results, or final selection rationale.
**What to build:** `sql/backtests/074_strategy_bakeoff_results.sql` — one row per (strategy, asset, tf, cost_scenario, cv_method, weight_scheme) with all metrics and composite score. Also a `strategy_selection_log` table for the formal selection rationale.
**Estimated complexity:** LOW. Follow the pattern of cmc_backtest_metrics.

### Gap 4: IC Sweep Batch Script (MEDIUM PRIORITY)
**What's missing:** The existing `run_ic_eval.py` handles one asset at a time. For the broad sweep across ALL assets x ALL tfs, a batch wrapper is needed.
**What to build:** `src/ta_lab2/scripts/analysis/run_ic_sweep.py` — iterates over (asset_id, tf) pairs from `asset_data_coverage`, applies minimum row count filter, calls the existing IC computation, persists results.
**Estimated complexity:** LOW. Mostly a loop around existing CLI logic.

### Gap 5: Ensemble/Blending Logic (LOW PRIORITY — contingency)
**What's missing:** No ensemble or signal blending code exists anywhere.
**What to build:** If needed, a simple `blend_signals()` function in `backtests/composite_scorer.py` that takes position series from multiple strategies and combines them (e.g., equal-weight, or IC-weighted). Only activate this path if no single strategy hits Sharpe >= 1.0.
**Estimated complexity:** LOW for simple blending; MEDIUM for IC-weighted dynamic blending.

### Gap 6: Scorecard Generator (MEDIUM PRIORITY)
**What's missing:** No markdown report generation script exists. `reports.py` has `save_table()` and `equity_plot()` but no structured report builder.
**What to build:** `src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py` — reads DB results, formats ranked tables, generates equity curve PNGs via plotly, writes `reports/bakeoff/BAKEOFF_SCORECARD.md`.
**Estimated complexity:** MEDIUM. Chart generation and markdown templating require attention to formatting.

### Gap 7: Funding Rate Data (LOW PRIORITY — may use fixed rate)
**What's missing:** No `cmc_funding_rates` table or ingestion pipeline exists in the codebase.
**What to build:** Either ingest historical BTC/ETH funding rates (adds scope) or use fixed 0.01%/8h = 3 bps/day (simpler). CONTEXT.md says "use historical average if available, fixed 0.01%/8h otherwise." Recommend fixed rate for phase scope.
**Estimated complexity:** HIGH if full ingestion, LOW if fixed rate constant.

---

## Risks

### Risk 1: Compute Time for Broad Asset x TF Sweep
**Description:** ALL assets x ALL timeframes x ALL 112 features x IC evaluation is a large combinatorial space. IC computation involves Spearman correlation per (feature, horizon, return_type) tuple. 112 features x 7 horizons x 2 return_types = 1568 IC calculations per asset-tf pair. If there are 100 assets x 10 TFs = 1000 asset-tf pairs, that's 1.57 million IC computations.
**Severity:** HIGH for broad sweep
**Mitigation:** Two-phase approach: (1) broad IC sweep at horizon=1 arith only to rank features quickly; (2) full IC sweep only for top-50 features by |IC|. The `batch_compute_ic` is vectorized (rolling rank + rolling corr), which is ~30x faster than per-window spearmanr. Estimated wall clock: 30-60 minutes for broad sweep.

### Risk 2: Insufficient Data for 10-Fold CV on Non-1D TFs
**Description:** 10-fold purged K-fold on a 1D timeframe with 3 years of history = ~1095 bars total, ~110 bars per fold. That's borderline for PSR (min 30) and rolling IC (min 63). For weekly (1W) bars, 3 years = ~156 bars, ~16 bars per fold — PSR will return NaN for all folds.
**Severity:** MEDIUM
**Mitigation:** Apply data density filter: skip asset+TF with fewer than 500 bars for CV analysis. Use fewer folds (5-fold) for shorter TF histories. Log all skipped combinations. Focus the full 10-fold analysis on BTC/ETH 1D which has the longest, cleanest history.

### Risk 3: No Strategy Meets Sharpe >= 1.0 Gate
**Description:** The V1 hard gate requires Sharpe >= 1.0 with realistic Kraken fees. With taker fees of 26 bps + slippage, high-turnover strategies (e.g., RSI mean-reversion) may not survive. The CONTEXT.md specifies: try ensemble/blending before lowering the gate.
**Severity:** MEDIUM — possible outcome
**Mitigation:** The CONTEXT.md provides the fallback path. Pre-screen on clean PnL (0 fees) first to identify which signals have positive alpha before cost drag. If no signal survives realistic fees, document clearly rather than massaging results.

### Risk 4: vbt_runner Funding Cost Gap
**Description:** `CostModel.to_vbt_kwargs()` does NOT pass `funding_bps_day` to vectorbt (only `fees` and `slippage`). The perps comparison backtest will under-count costs by the funding amount.
**Severity:** MEDIUM for perps analysis accuracy
**Mitigation:** Implement post-hoc funding deduction in the bakeoff orchestrator. For each perps backtest, compute `funding_cost = n_bars_in_position * funding_bps_day / 1e4` and adjust equity curve before metric computation.

### Risk 5: Experimental Feature Signal Path Undefined
**Description:** The ExperimentRunner computes IC for the 7 experimental features but does not generate entry/exit signals. Treating feature values as signal scores requires a threshold decision (e.g., top/bottom quartile as long/short signals). This threshold is not defined anywhere.
**Severity:** LOW — design decision needed
**Mitigation:** Use a standard quantile threshold approach: feature values in top quartile = long signal, bottom quartile = short signal, middle = flat. This is the standard IC-to-signal conversion in factor investing. Document the threshold choice in the scorecard.

---

## Data Availability Assessment

### Confirmed Available (from MEMORY.md)
- `cmc_features`: 112 columns, bar-level, (id, ts, tf) PK, ~2.1M rows, all 109 TFs refreshed
- `cmc_ema_multi_tf_u`: EMA values with (id, ts, tf, period) PK, ~14.8M rows
- `cmc_ama_multi_tf_u`: AMA values (kama indicator with params_hash d47fe5cc)
- `cmc_returns_bars_multi_tf_u`: Bar returns with z-scores, ~4.1M rows
- `cmc_vol`: Volatility columns (vol_30d, vol_7d) — used by `vol_ratio_30_7` experiment
- `cmc_ta_daily`: RSI, MACD etc — used by `rsi_momentum` experiment
- `cmc_regimes`: Regime labels (l2_label with trend_state + vol_state) for regime-conditional IC
- `cmc_backtest_runs/trades/metrics`: Existing backtest results (some runs already in DB)
- `cmc_ic_results`: May have partial IC results from prior runs — bake-off should use --overwrite to refresh

### May Need Pre-Computation Before Bake-Off
- Full IC sweep results (cmc_ic_results): Run `run_ic_eval --all-features` for BTC/ETH first as a quality check before broad sweep
- Experimental feature IC (cmc_feature_experiments): Run ExperimentRunner for all 7 features before including them in strategy candidate pool

### Not Available — Must Handle
- Historical funding rates: No `cmc_funding_rates` table. Use fixed 3 bps/day (0.01%/8h) for perps cost model
- AMA-based standalone signals: `cmc_ama_multi_tf_u` exists but no signal generator uses it yet. For bake-off, the experimental features `kama_er_signal` and `ama_ret_momentum` can be evaluated as IC-based signal scores, not through the full signal generator infrastructure

---

## Plan Structure Recommendation

Break Phase 42 into 5 sequential plans:

**Plan 01: IC Feature Sweep**
- Run `run_ic_eval --all-features --regime` for BTC/ETH 1D (validation that tooling works)
- Build `run_ic_sweep.py` batch script for broad sweep
- Run broad sweep across ALL assets x ALL TFs (filtered by min 500 bars)
- Produce feature ranking table in DB (cmc_ic_results) and markdown table
- Deliverable: Feature IC ranking, top-20 features by IC-IR identified

**Plan 02: Walk-Forward Backtest Orchestration**
- Build `bakeoff_orchestrator.py` with PurgedKFold + CPCV loops
- Run all 3 existing signal types x cost matrix x BTC/ETH 1D (core analysis)
- Run subset of top assets for other TFs (broader discovery)
- Compute PSR/DSR per strategy
- Compute regime-conditional metrics (backtest-by-regime)
- Deliverable: OOS metrics in DB for all strategies

**Plan 03: Composite Scoring + Sensitivity Analysis**
- Build `composite_scorer.py` with 4 weighting schemes
- Build `strategy_bakeoff_results` table DDL
- Run scoring across all strategies, persist results
- Apply V1 hard gates (Sharpe >= 1.0, Max DD <= 15%)
- Run sensitivity analysis: rank robustness across weighting schemes
- Deliverable: Ranked strategy scorecard data in DB

**Plan 04: Strategy Selection + Ensemble Contingency**
- Apply selection rules from CONTEXT.md (top-2 by composite, robust across 3/4 weighting schemes)
- If no strategy passes gates: blend top-2 signals, re-evaluate
- Choose final parameters (via walk-forward OOS results, not in-sample optimization)
- Document rationale for each decision
- Deliverable: Selected strategies identified with documented rationale

**Plan 05: Scorecard Generation**
- Build `generate_bakeoff_scorecard.py`
- Generate: feature IC ranking table, strategy comparison table, equity curves, regime analysis, sensitivity analysis
- Write `reports/bakeoff/BAKEOFF_SCORECARD.md`
- Deliverable: Formal scorecard document ready for Phase 53 V1 Validation reference

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed window walk-forward (splitters.py) | Purged K-fold (cv.py) | Phase 36 | Leakage-free CV; train/test sets don't bleed forward returns |
| Stub PSR in metrics.py | Full PSR from psr.py | Phase 36 | Real probabilistic significance, not sigmoid approximation |
| Single-asset, single-feature IC scripts | batch_compute_ic + run_ic_eval CLI | Phase 37 | Scales to 112 features x multiple assets without code changes |
| Single-metric ranking (Sharpe only) | Composite scoring (new in Phase 42) | Phase 42 | Avoids gaming single metric; robustness across weighting schemes |
| mlfinlab PurgedKFold | Custom implementation | Phase 36 | mlfinlab discontinued; known bug #295; custom has full test coverage |

**Deprecated / do not use:**
- `metrics.py:psr_placeholder()`: Sigmoid stub, not real PSR. Use `backtests/psr.py:compute_psr()` instead
- `backtests/orchestrator.py` leaderboard (MAR → Sharpe → CAGR sort): Only for single-metric sweep; Phase 42 needs composite scoring
- `splitters.py:expanding_walk_forward()`: Calendar-year splits, not purged; use `cv.py:PurgedKFoldSplitter` for bake-off

---

## Open Questions

1. **Funding rate for perps comparison**
   - What we know: `funding_bps_day` field exists in CostModel but no historical data in DB
   - What's unclear: Should we ingest historical Binance/Bybit funding rates, or use fixed 3 bps/day?
   - Recommendation: Use fixed 3 bps/day (0.01%/8h) for Phase 42. Historical ingestion is a Phase 51 task. Document the assumption in the scorecard.

2. **How to convert experimental feature scores to backtest signals**
   - What we know: ExperimentRunner produces IC scores, not entry/exit signals. `vol_ratio_30_7`, `rsi_momentum`, etc. produce float values.
   - What's unclear: What threshold converts a feature value to a buy/sell signal?
   - Recommendation: Use quartile threshold (top 25% = long, bottom 25% = short, middle = flat). This is the standard cross-sectional factor approach. Set this in `composite_scorer.py` as a configurable parameter.

3. **Minimum expanding-window training size for re-optimization path**
   - What we know: The CONTEXT.md marks this as Claude's discretion. EMA features need ~200 bars of warmup for period-200 EMAs. RSI needs ~14 bars.
   - What's unclear: The warmup requirement for the full feature set (ATR with 14-bar period, Donchian with 20-bar period).
   - Recommendation: Use 504 bars (~2 years of 1D data) as the minimum training window for the expanding-window re-optimization path. This gives adequate warmup for all indicators.

4. **Which assets qualify for broad discovery vs core analysis**
   - What we know: CONTEXT.md says ALL assets and ALL TFs for discovery. But compute time is a concern (Risk 1).
   - What's unclear: Exact row counts per asset-TF combination in the current DB.
   - Recommendation: Core analysis on BTC + ETH with full 10-fold CV and full cost matrix. Broad discovery sweep on all qualifying assets (>= 500 bars) at horizon=1, arith only, 5-fold CV, single cost scenario. Flag any non-BTC/ETH surprises for secondary investigation.

---

## Sources

### Primary (HIGH confidence — direct code inspection)
- `src/ta_lab2/backtests/cv.py` — PurgedKFoldSplitter, CPCVSplitter API, embargo_frac parameter
- `src/ta_lab2/backtests/psr.py` — PSR/DSR/MinTRL formulas, fisher=False convention documented
- `src/ta_lab2/backtests/vbt_runner.py` — run_vbt_on_split, CostModel integration, funding_bps_day gap
- `src/ta_lab2/backtests/costs.py` — CostModel dataclass, to_vbt_kwargs() only passes fee+slippage
- `src/ta_lab2/backtests/metrics.py` — psr_placeholder() stub identified as NOT real PSR
- `src/ta_lab2/backtests/orchestrator.py` — run_multi_strategy, leaderboard single-metric sort
- `src/ta_lab2/backtests/reports.py` — equity_plot (matplotlib optional), save_table, leaderboard
- `src/ta_lab2/backtests/splitters.py` — expanding_walk_forward (calendar-year, not purged)
- `src/ta_lab2/analysis/ic.py` — compute_ic, compute_rolling_ic, batch_compute_ic, save_ic_results, load_feature_series
- `src/ta_lab2/analysis/feature_eval.py` — redundancy_report, quick_logit_feature_weights
- `src/ta_lab2/analysis/regime_eval.py` — metrics_by_regime (uses analysis/performance.py)
- `src/ta_lab2/analysis/parameter_sweep.py` — grid, random_search utilities
- `src/ta_lab2/experiments/runner.py` — ExperimentRunner, BH correction, YAML-driven feature compute
- `src/ta_lab2/scripts/analysis/run_ic_eval.py` — full CLI for IC evaluation, --all-features mode
- `src/ta_lab2/scripts/backtests/run_backtest_signals.py` — CLI for single signal backtest
- `src/ta_lab2/scripts/backtests/compute_psr.py` — CLI for PSR on stored runs, fisher=False verified
- `src/ta_lab2/scripts/backtests/backtest_from_signals.py` — SignalBacktester class
- `src/ta_lab2/signals/registry.py` — REGISTRY dict with ema_trend, rsi_mean_revert adapters
- `configs/experiments/features.yaml` — 7 experimental features with YAML spec (5 feature types, 3 with param sweeps)
- `sql/backtests/070-073_*.sql` — cmc_backtest_runs, trades, metrics, psr_results DDL verified
- `sql/features/080_cmc_ic_results.sql` — IC results table DDL, natural key columns verified
- `sql/lookups/030_dim_signals.sql` — 6 seed signals across 3 signal types
- `.planning/phases/42-strategy-bake-off/42-CONTEXT.md` — all locked decisions

### Secondary (MEDIUM confidence)
- MEMORY.md project memory — data volumes, CRITICAL pitfalls (UTC timestamps, tf_days_nominal column name)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed present in codebase via direct inspection
- Architecture: HIGH — existing module APIs verified by reading source code
- Gaps identification: HIGH — confirmed absence of bakeoff orchestrator, composite scorer, scorecard generator by searching codebase
- Pitfalls: HIGH — most are from MEMORY.md (already encountered in production) or verified by reading source code
- Data availability: MEDIUM — row counts and asset coverage inferred from MEMORY.md, not from live DB query

**Research date:** 2026-02-24
**Valid until:** 2026-03-24 (stable architecture; re-verify if major vbt or scipy version changes)
