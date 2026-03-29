# Technology Stack: v1.3.0 Operational Activation & Research Expansion

**Project:** ta_lab2
**Milestone:** v1.3.0 — Operational Activation & Research Expansion
**Researched:** 2026-03-29
**Overall confidence:** HIGH (existing stack verified from codebase; new library versions verified via PyPI/official docs)

---

## Scope: What This Document Covers

v1.3.0 adds five new capability domains to a platform that is "built and idling":

1. **Operational Activation**: Scheduling paper executor, signal pipeline automation, parity tracking
2. **Massive Backtest Scaling**: 460K+ runs, 20-40M trades, resume-safe multiprocessing, Monte Carlo (113M+ bootstrap samples)
3. **ML Signal Combination**: LightGBM rank predictor (cross-sectional), SHAP values, XGBoost meta-label filter
4. **CTF Research Expansion**: Graduating CTF features to production, cross-asset composites, lead-lag analysis
5. **FRED Macro Expansion**: Adding SP500/NASDAQ Composite/DJIA/NASDAQ-100 equity indices to existing FRED pipeline

**The guiding question:** What additions, if any, are needed to the existing stack for these five domains?

**Answer summary:** Three targeted additions. Everything else is already installed. The platform's core stack (Python 3.12, PostgreSQL, SQLAlchemy, pandas, numpy, vectorbt, LightGBM, scikit-learn, multiprocessing) already covers the vast majority of what v1.3.0 requires. The three gaps are: SHAP for model interpretability, XGBoost for meta-label filtering, and a scheduling harness for operational automation.

---

## Confirmed Existing Stack (No Changes Needed)

These packages are installed and battle-tested across 290+ scripts. Do not re-evaluate.

| Package | Installed Version | v1.3.0 Role |
|---------|------------------|-------------|
| Python | 3.12 | Runtime |
| PostgreSQL | 14+ | All persistence |
| SQLAlchemy | 2.0.48 | Engine, raw SQL, Alembic |
| Alembic | 1.18.4 | Schema migrations |
| psycopg2-binary | 2.9.11 | Performance-critical raw SQL |
| pandas | 3.0.1 | DataFrame operations throughout |
| numpy | 2.4.3 | Numerical computation |
| scipy | 1.15.3 (venv311) | Monte Carlo, statistical tests |
| scikit-learn | 1.7.2 (venv311) | MetaLabeler (RandomForest), feature importance |
| vectorbt | 0.28.1 (venv311) | Backtest engine for all 460K+ runs |
| LightGBM | 4.6.0 | Already installed; used by double_ensemble.py |
| joblib | 1.5.3 (venv311) | Parallel loops, memory caching |
| schedule | 1.2.2 | Already installed; used for task scheduling |
| statsmodels | 0.14.0+ | ADF/KPSS stationarity (existing) |
| arch | 7.2.0 (venv311) | GARCH volatility (existing) |
| hmmlearn | 0.3.3+ | HMM regime classifier (existing) |
| optuna | (installed) | Hyperparameter sweep (existing) |
| PyYAML | 6.0.3 | Config files, experiment YAML |
| Streamlit | 1.44.0 (venv311) | Dashboard (17 pages) |
| fredapi | 0.5.2 | FRED API for equity index series |
| multiprocessing | stdlib | Bakeoff orchestrator, bar builders |

**Verified from:** `.venv/Scripts/pip list`, `.venv311/Scripts/pip list`, `pyproject.toml`, `requirements-311.txt`

---

## Decision 1: SHAP for LightGBM/XGBoost Interpretability

**Question:** What library should provide SHAP values for the ML signal combination module?

**Recommendation: `shap>=0.51.0`**

**Confidence: HIGH** (verified via PyPI, shap.readthedocs.io/en/latest/release_notes.html)

### Rationale

The ML signal combination work requires explaining why the LGBMRanker scores assets the way it does — which features (AMA slopes, CTF divergences, VIX regime, yield curve) are driving predictions. SHAP is the standard tool for this.

Key verified facts:
- **Current version: 0.51.0**, released March 4, 2026. Confirmed pandas 3.0 compatibility fixes are in this release. This matters because the project uses pandas 3.0.1.
- **Requires Python >=3.11.** The project runs Python 3.12 — compatible.
- **Tree SHAP** (fast C++ implementation) works natively with LightGBM 4.6.0 and XGBoost 3.x. No compatibility gap.
- **Zero friction integration:** `shap.Explainer(model)` accepts fitted `LGBMRanker` and `XGBClassifier` directly.

### How It Integrates

The existing `ml/feature_importance.py` implements MDA (Mean Decrease Accuracy), SFI, and Clustered FI via permutation — all sklearn-style. SHAP is a complementary, faster approach that works at inference time (not just training time). The planned usage:

```python
import shap

explainer = shap.TreeExplainer(lgbm_ranker)
shap_values = explainer.shap_values(X_cross_section)
# Result: per-asset, per-feature attribution for each cross-sectional prediction
```

This is additive to the existing feature importance infrastructure, not a replacement.

### What NOT to Use

| Alternative | Why Not |
|------------|---------|
| `lime` | Slower, less accurate for tree models than TreeSHAP |
| `eli5` | Lower maintenance, less precise for gradient boosting |
| sklearn `permutation_importance` | Already in `feature_importance.py` for MDA; SHAP adds complementary local explanations |

### Installation

```bash
pip install "shap>=0.51.0"
```

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
ml = [
    "shap>=0.51.0",
]
```

Source: [shap on PyPI](https://pypi.org/project/shap/) — v0.51.0 released 2026-03-04

---

## Decision 2: XGBoost for Meta-Label Filter

**Question:** Should the meta-label filter use the existing scikit-learn `RandomForestClassifier` (in `meta_labeler.py`) or switch to XGBoost?

**Recommendation: Add `xgboost>=3.2.0` as a new optional dependency. Keep `RandomForestClassifier` as the existing path.**

**Confidence: HIGH** (verified via PyPI xgboost page — v3.2.0 released 2026-02-10)

### Rationale

The existing `meta_labeler.py` uses `RandomForestClassifier` with `balanced_subsample`. XGBoost is proposed for a parallel meta-label pipeline because:

1. **Gradient boosting consistently outperforms random forests** on tabular financial features (this is why LightGBM was already chosen for `double_ensemble.py`).
2. **SHAP values integrate natively** with XGBoost — the same `shap.TreeExplainer` approach works for both the LGBMRanker and XGBClassifier models.
3. **Monotone constraints** available in XGBoost 3.x — useful for encoding prior knowledge (e.g., "higher VIX should increase meta-label uncertainty").

Key verified facts:
- **Current version: 3.2.0**, released February 10, 2026. Requires Python >=3.10.
- **Available as `xgboost-cpu`** for minimal footprint (no GPU), which suits a Windows research machine.
- **Windows-first support**: XGBoost 3.x has full Windows prebuilt wheels.

### Integration Point

A new `XGBMetaLabeler` class sits alongside the existing `MetaLabeler`:

```python
# Proposed: ml/xgb_meta_labeler.py
from xgboost import XGBClassifier

class XGBMetaLabeler:
    """XGBoost meta-labeler for binary trade-success filtering.
    Complements MetaLabeler (RandomForest) for A/B comparison.
    """
    def __init__(self, n_estimators=200, learning_rate=0.05, ...):
        self.model = XGBClassifier(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            scale_pos_weight=...,   # handles class imbalance
            use_label_encoder=False,
            eval_metric="logloss",
        )
```

The `triple_barrier_labels` and `meta_label_results` tables already exist. No schema changes needed for the XGBoost path.

### What NOT to Use

| Alternative | Why Not |
|------------|---------|
| CatBoost | Slower training, less ecosystem integration with SHAP than XGBoost |
| LightGBM for meta-labeling | Already used in double_ensemble.py — using XGBoost here enables a genuine A/B comparison between two gradient boosting frameworks |
| Neural networks (sklearn MLPClassifier) | Overkill for 10-100K training samples; interpretability gap |

### Installation

```bash
pip install "xgboost>=3.2.0"
```

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
ml = [
    "shap>=0.51.0",
    "xgboost>=3.2.0",
]
```

Source: [xgboost on PyPI](https://pypi.org/project/xgboost/) — v3.2.0 released 2026-02-10

---

## Decision 3: Scheduling — Use Existing `schedule` Library (Already Installed)

**Question:** What scheduler should automate the paper executor, signal pipeline, and daily refresh?

**Recommendation: Use the already-installed `schedule 1.2.2`. No new libraries needed.**

**Confidence: HIGH** (schedule v1.2.2 verified installed in both venvs; APScheduler v4.0 verified alpha-only)

### Current State

`schedule==1.2.2` is already installed in both `.venv` and `.venv311`. The `run_daily_refresh.py` script already orchestrates the full pipeline (VM sync → bars → EMAs → AMAs → regimes → signals → executor → drift). What is missing is not a scheduler library — it is:

1. **`dim_executor_config` is empty**: No active strategy configurations → executor has nothing to run
2. **No always-on runner**: `run_daily_refresh.py` exists but is not invoked automatically

### Recommended Approach

**Windows Task Scheduler + `run_daily_refresh.py`** — not a Python scheduler daemon.

The operational activation work is not a scheduling problem; it is a configuration problem. The correct sequence:

```
Step 1: Seed dim_executor_config (one-time DB seed)
Step 2: Wire signals → executor (confirm flow works in manual run)
Step 3: Register run_daily_refresh.py in Windows Task Scheduler
        trigger: daily at market close + 15min (e.g., 23:15 UTC)
        action: python -m ta_lab2.scripts.run_daily_refresh --all --ids all
```

Windows Task Scheduler (built into Windows 11) runs scripts persistently without a Python daemon process, survives reboots, and has no library dependencies. This is the correct tool for a single-machine research platform.

### Why Not APScheduler

- APScheduler 3.11.2 is the current stable release (December 22, 2025). Version 4.0 is still alpha (`4.0.0a6`) as of April 2025 — NOT production-ready.
- APScheduler runs inside a Python process. If the process crashes (a real risk with 460K+ backtest runs), the schedule dies. Windows Task Scheduler runs externally and restarts on reboot.
- The project already has `schedule` installed. APScheduler would be a second scheduler library with no benefit.

### For the Signal Freshness Loop

If a lightweight in-process heartbeat is needed (e.g., a 5-minute signal freshness check), `schedule 1.2.2` is already available:

```python
import schedule
import time

schedule.every(5).minutes.do(check_signal_freshness)

while True:
    schedule.run_pending()
    time.sleep(60)
```

This pattern is appropriate for a development/research context. For production, this loop runs inside a supervised process (a Windows Service or Task Scheduler task).

Source: [schedule docs](https://schedule.readthedocs.io/) — v1.2.0 is latest documented stable, v1.2.2 installed

---

## Decision 4: Massive Backtest Scaling — No New Libraries

**Question:** What stack is needed for 460K+ backtest runs, 20-40M trades, resume-safe execution, and 113M+ Monte Carlo bootstrap samples?

**Recommendation: Existing stack (vectorbt 0.28.1 + multiprocessing + joblib 1.5.3 + numpy 2.4.3). No new libraries.**

**Confidence: HIGH** (verified installed; pattern documented in bakeoff_orchestrator.py and MultiprocessingOrchestrator)

### Scale Analysis

| Operation | Volume | Tooling |
|-----------|--------|---------|
| Backtest parameter combinations | 460K+ runs | vectorbt parameter grid (in-memory) |
| Simulated trades | 20-40M trades | vectorbt Portfolio, stored in backtest_trades |
| Monte Carlo bootstrap samples | 113M+ | numpy `Generator.integers()` with vectorized sampling |
| Parallel workers | Up to 8 CPUs | Python `multiprocessing.Pool` + `NullPool` pattern |

### Resume-Safety Pattern (No New Libraries)

The project's established pattern for large jobs:

```python
# Pattern: state map filtering (already in MultiprocessingOrchestrator)
# Skip combinations that already have results in backtest_runs
completed = set(engine.execute("SELECT (asset_id, tf, strategy, cost_scenario)
                                 FROM strategy_bakeoff_results
                                 WHERE experiment_name = :exp").fetchall())
tasks = [t for t in all_tasks if (t.asset_id, t.tf, t.strategy, t.cost) not in completed]
```

This is already how the bar builders work (`state_map` optimization). The same pattern applies to the bakeoff orchestrator. **No checkpoint library needed** — PostgreSQL IS the checkpoint store.

### Monte Carlo Scaling

The existing `monte_carlo.py` uses `numpy.random.default_rng()` for reproducible bootstrap. For 113M samples, the bottleneck is memory layout, not the library:

```python
# Vectorized bootstrap — existing pattern, just more samples
rng = np.random.default_rng(seed)
indices = rng.integers(0, n_trades, size=(n_samples, n_trades))  # shape: (10K, 11.3K)
bootstrapped = pnl_array[indices]   # numpy fancy indexing — no Python loop
sharpes = bootstrapped.mean(axis=1) / bootstrapped.std(axis=1, ddof=1) * sqrt(365)
```

For 113M samples (10K bootstrap × 11.3K trades), numpy 2.4.3 handles this with ~900MB memory. Acceptable on a 16GB+ research machine.

### Windows Multiprocessing Constraints

The existing conventions remain:
- `NullPool` for all DB engines in subprocess workers (prevents connection leaks)
- `maxtasksperchild=1` when memory growth is a risk (AMA builders)
- `maxtasksperchild=50` for lighter tasks (bakeoff workers)
- `spawn` start method (Windows default — no `fork`)

No changes to these conventions for v1.3.0.

### joblib vs multiprocessing

`joblib 1.5.3` (installed) is available for its `Memory` caching feature — useful if intermediate bakeoff results need disk caching between runs. However, the existing `multiprocessing.Pool` in `MultiprocessingOrchestrator` is the primary parallel mechanism and should not be replaced. Use `joblib.Memory` only if caching intermediate computations proves beneficial.

---

## Decision 5: LightGBM Rank Predictor — Use Existing LightGBM (LGBMRanker API)

**Question:** Does the cross-sectional rank predictor require a new library or LightGBM upgrade?

**Recommendation: Use existing `LightGBM 4.6.0` with `LGBMRanker`. No upgrade needed.**

**Confidence: HIGH** (LGBMRanker verified in LightGBM 4.6.0 official docs: lightgbm.readthedocs.io/en/stable)

### LGBMRanker in LightGBM 4.6.0

`LGBMRanker` is available in LightGBM 4.6.0 (the installed version). The API is stable and has been present since 3.x. The required pattern:

```python
from lightgbm import LGBMRanker

ranker = LGBMRanker(
    objective="lambdarank",
    n_estimators=300,
    learning_rate=0.05,
    num_leaves=31,
    min_child_samples=20,
    verbose=-1,
)

# Cross-sectional ranking: group = number of assets per date
groups = cross_section_df.groupby("ts").size().values  # e.g., [213, 213, 213, ...]

ranker.fit(
    X_train,
    y_rank_train,       # rank labels (0=worst, N=best)
    group=groups,
)

scores = ranker.predict(X_today)   # continuous score per asset, cross-sectionally comparable
```

The `group` parameter tells LGBMRanker the query (date) boundaries. For daily cross-sections with ~213 assets, this works without any library changes.

### NDCG as Optimization Target

`LGBMRanker` defaults to NDCG optimization. For signal combination (rank assets by forward return prediction), NDCG is appropriate — it rewards correctly ordering the top decile.

### Integration with Existing Code

The existing `ml/expression_engine.py` has `Rank()` as an operator, but that computes cross-sectional ranks as features. The LGBMRanker is a level up: it learns to combine features into a final ranking, replacing a hand-crafted composite IC score.

---

## Decision 6: CTF Research Expansion — No New Libraries

**Question:** What stack is needed for graduating CTF features to production, cross-asset composites, and lead-lag analysis?

**Recommendation: Existing stack. No additions needed.**

**Confidence: HIGH** (all CTF code already uses numpy, pandas, scipy, SQLAlchemy)

### Verified Existing CTF Stack

The `features/cross_timeframe.py` module is already written (Phase 90). It uses:
- `numpy.polyfit` for rolling slope computation
- `pandas.merge_asof` for timeframe alignment
- `scipy` (indirectly via statsmodels correlations in `macro/lead_lag_analyzer.py`)
- SQLAlchemy `text()` for DB reads/writes

Graduating CTF to production means: running `refresh_ctf.py` on schedule, merging CTF columns into the feature matrix for bakeoff, and adding CTF columns to the IC sweep. All of these use existing infrastructure.

The `macro/lead_lag_analyzer.py` is already implemented (Phase 70). Cross-asset composites use `macro/cross_asset.py`. No new libraries needed.

---

## Decision 7: FRED Macro Expansion (SP500/NASDAQ) — `fredapi` Already Covers It

**Question:** What is needed to add SP500/NASDAQCOM/DJIA/NASDAQ100 equity indices to the FRED pipeline?

**Recommendation: Use existing `fredapi 0.5.2`. The series IDs are valid FRED series. No new libraries needed.**

**Confidence: HIGH** (FRED series IDs verified directly at fred.stlouisfed.org; fredapi 0.5.2 already handles these)

### Verified FRED Series IDs

| Series | FRED ID | Frequency | History |
|--------|---------|-----------|---------|
| S&P 500 | `SP500` | Daily (market close) | 10 years only (S&P licensing limitation) |
| NASDAQ Composite | `NASDAQCOM` | Daily (market close) | Full history from 1971-02-05 |
| Dow Jones Industrial Average | `DJIA` | Daily (market close) | 10 years only (S&P/Dow Jones licensing) |
| NASDAQ-100 | `NASDAQ100` | Daily (market close) | Full history from 1986-01-02 |
| Russell 2000 | N/A | N/A | REMOVED from FRED in October 2019 |

**CRITICAL:** Russell 2000 is NOT available on FRED. FTSE Russell withdrew all 36 series from FRED in October 2019. If Russell 2000 exposure is needed, use `yfinance` with ticker `^RUT`. However, for the macro feature pipeline, the other four indices provide adequate equity regime coverage.

**CRITICAL:** SP500 and DJIA are limited to 10 years of daily history by licensing agreement with S&P Dow Jones Indices. For a project with data going back to 2013+, this means SP500 will have a gap before ~2016. The existing forward-fill logic in `macro/forward_fill.py` already handles this gracefully.

### What's Already Partially Done

The `macro/forward_fill.py` already has `SP500`, `NASDAQCOM`, `DJIA`, and `NASDAQ100` in the `FFILL_LIMITS` dict (lines 71-74) — they were pre-wired but not yet added to:
1. `fred_reader.py` SERIES_TO_LOAD list
2. `feature_computer.py` _RENAME_MAP
3. The VM's GCP FRED collection scripts (where the data is fetched from FRED API)
4. The `fred.fred_macro_features` DB schema (Alembic migration needed)

The work is code changes to existing files, not new library adoption.

### yfinance as Fallback (Optional, Not Recommended)

`yfinance 0.2.53` is installed in `.venv311` (confirmed in `requirements-311.txt`). It can fetch `^GSPC`, `^IXIC`, `^DJI`, `^NDX`, `^RUT`. This provides a fallback for the SP500/DJIA 10-year window limitation.

**However:** Do NOT use yfinance as the primary source for equity indices in the FRED pipeline. The existing pipeline syncs from the GCP VM (which uses fredapi). Mixing data sources for the same series creates provenance complexity. Use `fredapi` for FRED series. If the 10-year SP500 window is insufficient, note the limitation in the feature documentation and accept it — crypto strategies are unlikely to require equity data before 2016.

---

## Summary: Stack Delta for v1.3.0

| Category | Additions | Removals |
|----------|-----------|----------|
| Core dependencies | **None** | None |
| New optional group `ml` | `shap>=0.51.0`, `xgboost>=3.2.0` | None |
| Scheduling | None (use Windows Task Scheduler + existing `schedule 1.2.2`) | None |
| Backtest scaling | None (vectorbt + multiprocessing + numpy already sufficient) | None |
| LGBMRanker | None (LightGBM 4.6.0 `LGBMRanker` already available) | None |
| CTF research | None (numpy + pandas + scipy already used) | None |
| FRED equity indices | None (fredapi 0.5.2 already covers SP500/NASDAQ series) | None |

**Net new libraries: 2** (`shap`, `xgboost`). Both are targeted additions for specific capability gaps, not exploratory adoption.

---

## Recommended pyproject.toml Changes

```toml
# Add this new optional group:
[project.optional-dependencies]
ml = [
    "shap>=0.51.0",      # SHAP values for LGBMRanker and XGBClassifier interpretability
    "xgboost>=3.2.0",    # XGBoost meta-label filter (complements LightGBM in double_ensemble.py)
]

# Update the 'all' group to include ml:
all = [
    # ... existing entries ...
    "shap>=0.51.0",
    "xgboost>=3.2.0",
]
```

No changes to core `dependencies` block. These remain optional because the platform runs without them — the existing `MetaLabeler` (RandomForest) and `feature_importance.py` (MDA/SFI) continue to work.

---

## What NOT to Add (And Why)

| Candidate | Why NOT |
|-----------|---------|
| **APScheduler** | v4.0 is alpha-only; v3.11.2 would duplicate `schedule 1.2.2` already installed; Windows Task Scheduler is more robust for this use case |
| **Celery** | Distributed task queue designed for multi-machine deployments; this is a single-machine research platform; massive overkill |
| **Prefect / Airflow / Luigi** | Full workflow orchestration systems; `run_daily_refresh.py` already orchestrates the pipeline as a Python script |
| **Ray** | Distributed computing for multi-machine parallelism; overkill; `multiprocessing.Pool` handles 460K runs within a single machine |
| **Dask** | Lazy evaluation and distributed DataFrames; pandas 3.0 + numpy 2.4 is sufficient; Dask adds operational complexity |
| **pandas-datareader** | Only needed for FRED data; `fredapi` already covers the required equity index series (`SP500`, `NASDAQCOM`, `DJIA`, `NASDAQ100`) |
| **yfinance (as primary FRED replacement)** | Would create dual-source provenance for the same time series; acceptable only as a Russell 2000 fallback |
| **CatBoost** | Third gradient boosting framework; LightGBM + XGBoost already provides a valid A/B comparison |
| **PyTorch / TensorFlow** | No deep learning capability is planned for v1.3.0; gradient boosting is sufficient for the feature counts involved (100-300 features) |
| **Great Expectations / dbt** | Data quality and SQL-first pipeline frameworks; overkill given the existing audit scripts and SQLAlchemy patterns |
| **pytest-alembic** | Recommended in v1.1.0 STACK.md as an optional dev addition; still optional for v1.3.0 |

---

## Integration Notes for Phase Authors

### ML Signal Combination (SHAP + XGBoost)

The lazy import pattern from `double_ensemble.py` should be replicated:

```python
# In any new ML module using XGBoost or SHAP:
try:
    import xgboost as xgb
    import shap
except ImportError:  # pragma: no cover
    xgb = None
    shap = None
```

This keeps the module importable in CI environments that don't install the `ml` extras.

### Massive Backtest Scaling

The `MultiprocessingOrchestrator` in `orchestration/multiprocessing_orchestrator.py` is the correct abstraction for 460K+ runs. Do not create a new parallel mechanism. Extend the existing orchestrator's `config` dataclass (`OrchestratorConfig`) if additional configuration is needed (e.g., chunk size for resume-safety).

### FRED Equity Indices

The pipeline to add SP500/NASDAQCOM/DJIA/NASDAQ100 requires changes to four existing files only:
1. `macro/fred_reader.py` — add to `SERIES_TO_LOAD`
2. `macro/feature_computer.py` — add to `_RENAME_MAP` and compute derived features (momentum, volatility)
3. `scripts/etl/sync_fred_from_vm.py` (or the GCP VM collection script) — ensure series are collected
4. One Alembic migration — add columns to `fred.fred_macro_features`

Do NOT create a separate equity index pipeline. The FRED macro pipeline already handles forward-filling, provenance tracking, and DB upserts. These indices belong in the same `fred.fred_macro_features` table.

---

## Sources

- [shap on PyPI](https://pypi.org/project/shap/) — v0.51.0 confirmed March 4, 2026
- [SHAP release notes](https://shap.readthedocs.io/en/latest/release_notes.html) — v0.51.0: pandas 3.0 compatibility, XGBoost compatibility
- [xgboost on PyPI](https://pypi.org/project/xgboost/) — v3.2.0 confirmed February 10, 2026
- [XGBoost installation guide](https://xgboost.readthedocs.io/en/stable/install.html) — Python >=3.10, Windows wheels available
- [APScheduler on PyPI](https://pypi.org/project/APScheduler/) — stable 3.11.2 (December 2025); 4.0 still alpha
- [LightGBM LGBMRanker docs](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRanker.html) — confirmed in 4.6.0 stable
- [joblib on PyPI](https://pypi.org/project/joblib/) — v1.5.3 released December 15, 2025
- [FRED SP500 series](https://fred.stlouisfed.org/series/SP500) — 10-year daily window; licensing limitation confirmed
- [FRED NASDAQCOM series](https://fred.stlouisfed.org/series/NASDAQCOM) — full history from 1971
- [FRED NASDAQ100 series](https://fred.stlouisfed.org/series/NASDAQ100) — full history from 1986
- [FRED Russell 2000 removal notice](https://fred.stlouisfed.org/series/RU2000VTR) — confirmed removed October 2019
- [yfinance on PyPI](https://pypi.org/project/yfinance/) — v1.2.0 released February 16, 2026 (reference only, not recommended as primary source)
- [schedule library docs](https://schedule.readthedocs.io/) — v1.2.0 stable; v1.2.2 installed in this project
