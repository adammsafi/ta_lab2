# Technology Stack: v0.9.0 Research & Experimentation

**Project:** ta_lab2
**Milestone:** v0.9.0 — Adaptive MAs, IC evaluation, PSR, Purged CV, Feature lifecycle, Streamlit, Notebooks
**Researched:** 2026-02-23
**Overall confidence:** HIGH (all version claims verified against PyPI or official docs)

---

## Environment Clarification: Two Python Environments

This project runs two Python environments. This distinction matters for every dependency decision.

| Environment | Python | Relevant for |
|-------------|--------|-------------|
| System Python / `pip` | 3.12.7 | Active dev: runs signals, backtests, scripts, streamlit |
| `.venv311/` | 3.11.9 | Legacy freeze only; vectorbt was tested here in v0.7.0 |

**Practical consequence:** All new packages should target the **Python 3.12** environment. The `pyproject.toml` already specifies `target-version = "py312"` in ruff config. The main `pip` command resolves to Python 3.12.7.

**Confirmed existing stack (Python 3.12 environment):**

| Package | Installed Version |
|---------|------------------|
| numpy | 2.4.1 |
| scipy | 1.17.0 (released 2026-01-10) |
| pandas | 2.3.3 |
| scikit-learn | 1.8.0 (released 2025-12-10) |
| polars | 1.36.1 |
| plotly | 6.4.0 |
| arch | 7.2.0 |
| numba | 0.64.0 |
| vectorbt | 0.28.1 |
| streamlit | 1.44.0 |

**What this means:** scipy, numpy, scikit-learn, plotly, and numba are already installed. The new features can be implemented with minimal new packages.

---

## Context: What Already Exists (Do Not Re-Research)

The following stack is validated and in production. These are NOT open questions:

| Component | Status |
|-----------|--------|
| Python 3.12, PostgreSQL, SQLAlchemy 2.0 | Locked |
| pandas, numpy, scipy, scikit-learn | Installed, do not re-pin |
| vectorbt 0.28.1 | Locked — do not upgrade |
| ruff, mypy, mkdocs-material, alembic | v0.8.0 handled these |
| matplotlib (existing viz) | Locked |
| Telegram notifications | Complete |
| parameter_sweep.py (grid + random search) | Complete |
| feature_eval.py (Pearson corr, logistic regression) | Partial — needs IC/Spearman extension |
| splitters.py (expanding walk-forward) | Partial — needs purged CV |
| metrics.py (PSR placeholder) | Stub — needs real PSR |

---

## Feature Area 1: Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA)

### Recommendation: IMPLEMENT IN-HOUSE — NO NEW LIBRARY

**Rationale:** All four adaptive MA algorithms reduce to 10-30 lines of numpy each. The only library options are TA-Lib (requires a C binary install on Windows) and pandas-ta (beta-only, requires Python >=3.12 AND numba >=0.60, while the .venv311 environment has numba 0.57.1 — the divergence creates maintenance risk across environments).

The existing codebase already has:
- A `BaseEMAFeature` hierarchy with vectorized numpy computation patterns
- `EMAFeature` subclasses that compute running exponential weights
- Multi-TF feature write pipeline that handles chunked DB writes

KAMA, DEMA, TEMA, and HMA are single-pass or two-pass numpy algorithms that slot directly into this hierarchy.

**Algorithm complexities:**

| Indicator | Formula | numpy operations needed |
|-----------|---------|------------------------|
| KAMA | ER = abs(change) / sum(abs(moves)); SC = (ER*(fast-slow)+slow)^2; KAMA_t = KAMA_{t-1} + SC*(P - KAMA_{t-1}) | cumsum, abs, rolling window via stride tricks |
| DEMA | DEMA = 2*EMA(N) - EMA(EMA(N)) | Two EMA passes |
| TEMA | TEMA = 3*EMA1 - 3*EMA2 + EMA3 | Three EMA passes |
| HMA | HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n)) | Three WMA passes |

All algorithms are expressible with numpy and a simple EMA helper function. The existing `BaseEMAFeature` already computes pandas `ewm()` which can be reused.

**What NOT to add:**

- **TA-Lib (C wrapper):** Requires installing `ta-lib-0.4.0-msvc.zip` to `C:\ta-lib` on Windows before `pip install TA-Lib`. This is a manual binary dependency that breaks CI reproducibility and creates an installation footgun. Latest version is 0.6.8 (Oct 2025), but the C library install requirement makes it inappropriate here.

- **pandas-ta 0.4.71b0:** Beta-only (no stable release on PyPI). Requires Python >=3.12 AND numba >=0.60. The `.venv311` environment has numba 0.57.1 which is incompatible. Even though the main environment has numba 0.64.0, installing a beta library for four indicator functions is unjustifiable when the math is 30 lines.

- **finta:** Last meaningful release in 2021; effectively unmaintained.

---

## Feature Area 2: Information Coefficient (IC) Evaluation

### Recommendation: EXTEND feature_eval.py USING SCIPY (ALREADY INSTALLED)

**What's needed:**
- Spearman rank correlation (IC per period)
- Rolling IC mean and IC information ratio (IR = mean_IC / std_IC)
- IC decay analysis (IC at lag 1, 2, ..., N bars)
- Turnover metric (fraction of top-quintile assets changing per period)

**Stack decision:**

| Capability | Library | Status |
|-----------|---------|--------|
| `scipy.stats.spearmanr()` | scipy 1.17.0 | ALREADY INSTALLED |
| Groupby / rolling windows | pandas 2.3.3 | ALREADY INSTALLED |
| Plotting IC time series | matplotlib (existing) | ALREADY INSTALLED |

`scipy.stats.spearmanr(a, b)` returns (correlation, pvalue). Rolling IC by period is a groupby over the timestamp dimension. IC decay is the correlation at shifted horizons. All of this is 50-100 lines in `feature_eval.py`.

**Alphalens-reloaded assessment:**

`alphalens-reloaded==0.4.6` (released 2025-06-02) provides these IC metrics plus pre-built plotting. It is actively maintained (Production/Stable), Python >=3.10, no problematic dependencies.

**Decision: DO NOT add alphalens-reloaded.**

Rationale: The project has an existing `feature_eval.py` with a clear API pattern and a `viz/all_plots.py` with matplotlib conventions. Alphalens-reloaded's plotting style (seaborn-based, opinionated layouts) conflicts with the existing visualization layer. Adding it introduces `seaborn` (not currently installed, 2.1 MB), `statsmodels` (not currently installed, large), and a new plot aesthetic that differs from existing charts. The four IC functions needed fit in ~80 lines. The math is `scipy.stats.spearmanr` in a loop — not complex enough to justify the dependency surface.

**Exception — IF seaborn is added for another reason:** The alphalens-reloaded assessment becomes favorable. Seaborn 0.13.2 (latest, 2024-01-25) is a reasonable add-on for research notebooks. But add seaborn only if notebooks explicitly need seaborn-style plots; do not add it just to unblock alphalens.

---

## Feature Area 3: Probabilistic Sharpe Ratio (PSR)

### Recommendation: IMPLEMENT IN-HOUSE — scipy (ALREADY INSTALLED)

**What's needed (Lopez de Prado formulation):**

```python
# All required scipy/numpy functions already available
from scipy.stats import norm, skew, kurtosis

def psr(returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    n = len(returns)
    sr_hat = returns.mean() / returns.std(ddof=1) * np.sqrt(252)
    skew_r = skew(returns)
    kurt_r = kurtosis(returns, fisher=True)  # excess kurtosis
    # Standard deviation of estimated Sharpe (Bailey & Lopez de Prado 2012)
    sr_std = np.sqrt(
        (1 + (0.5 * sr_hat**2) - (skew_r * sr_hat) + ((kurt_r / 4) * sr_hat**2)) / (n - 1)
    )
    return float(norm.cdf((sr_hat - sr_benchmark) / sr_std))
```

**Required functions and their status:**

| Function | Module | Installed |
|----------|--------|-----------|
| `scipy.stats.norm.cdf` | scipy 1.17.0 | YES |
| `scipy.stats.skew` | scipy 1.17.0 | YES |
| `scipy.stats.kurtosis` | scipy 1.17.0 | YES |
| `numpy.sqrt`, `numpy.sqrt` | numpy 2.4.1 | YES |

The existing `metrics.py` has `psr_placeholder()` as a stub. The real PSR is a drop-in replacement using only already-installed libraries.

**What NOT to add:**
- **mlfinlab:** As of early 2026, mlfinlab is effectively discontinued on PyPI (no new PyPI releases in 12+ months). The project moved to a paid private tier. Its GitHub-sourced open version (`mlfinpy`) is a community fork with unclear maintenance. Do not add.
- **quantstats:** Adds heavy optional dependencies (yfinance, requests) and has a different API contract than the existing `metrics.py`. The codebase's metrics API is already defined; adapting to quantstats would be net negative.
- **pypbo:** Small library for backtest overfitting probability; single-function wrappers. Not needed when PSR math is 15 lines.

---

## Feature Area 4: Purged K-Fold Cross-Validation

### Recommendation: IMPLEMENT IN-HOUSE using sklearn BaseEstimator pattern — OR add skfolio

**Option A: Extend splitters.py (preferred for minimal dependency)**

scikit-learn 1.8.0's `TimeSeriesSplit` has a `gap` parameter (embargo). However, it does NOT implement purging (removing overlapping label windows from the training set). For a full Lopez de Prado purged CV, the codebase needs to implement `PurgedKFold` itself.

The implementation is ~100 lines following sklearn's `BaseCrossValidator` interface:

```python
from sklearn.model_selection import BaseCrossValidator
import numpy as np

class PurgedKFold(BaseCrossValidator):
    """
    Purged K-fold with embargo, following Lopez de Prado AFML Chapter 7.
    Assumes samples have prediction times and evaluation times.
    """
    def __init__(self, n_splits=5, embargo_pct=0.01):
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def split(self, X, y=None, pred_times=None, eval_times=None):
        # ... purge logic using pred_times/eval_times overlap detection
        pass

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits
```

This fits in the existing `splitters.py` and requires only `sklearn.model_selection.BaseCrossValidator` (already installed).

**Option B: skfolio 0.15.5 (released 2026-02-10)**

skfolio provides `CombinatorialPurgedCV`, which is the full combinatorial variant (multiple testing paths). It is actively maintained, Python >=3.10, sklearn-compatible.

**However:** skfolio's primary scope is portfolio optimization (mean-variance, hierarchical clustering). Its CV class is incidental to its main purpose. Adding it for one class (`CombinatorialPurgedCV`) brings in `cvxpy-base`, `clarabel` (convex solver), and `plotly>=5.22.0` as hard dependencies — substantial overhead.

**Decision: Implement PurgedKFold in-house in splitters.py (Option A).**

Reserve skfolio consideration for a future portfolio optimization milestone if that ever becomes scope.

**timeseriescv assessment:** PyPI package `timeseriescv==0.2` is inactive (no new releases). Do not use.

---

## Feature Area 5: Feature Experimentation Framework (Lifecycle)

### Recommendation: NO NEW LIBRARIES — file-based registry + existing DB

The feature lifecycle (experimental → promoted → deprecated) is a **metadata management problem**, not a library problem. The existing infrastructure covers every need:

| Need | Existing tool |
|------|--------------|
| Lifecycle state storage | New DB table (`cmc_feature_registry`) via Alembic migration |
| Feature configuration | YAML config files + `pyyaml` (already in core deps) |
| Status querying | SQLAlchemy 2.0 (already in core deps) |
| Compute reuse | Existing `BaseEMAFeature` / feature pipeline |
| IC evaluation | `feature_eval.py` extensions (Area 2) |

**What NOT to add:**
- **MLflow:** Experiment tracking at model-level granularity. Overkill for feature-level lifecycle in a single-developer quant lab. Adds an MLflow server process or file backend, a UI that duplicates what a Streamlit dashboard would provide, and tight coupling to MLflow's artifact storage patterns.
- **DVC (Data Version Control):** Designed for dataset versioning in git. The project tracks features in PostgreSQL, not files. DVC is architecturally mismatched.
- **Feast (feature store):** Enterprise-grade feature serving with an online/offline store separation. Far beyond current scale (22M rows, single PostgreSQL). The codebase's existing `cmc_features` table IS the feature store.
- **Weights & Biases / Neptune:** SaaS experiment trackers. Adds external service dependency to a self-contained research codebase.

---

## Feature Area 6: Streamlit Dashboard

### Recommendation: UPGRADE streamlit from 1.44.0 to >=1.54.0

**Current state:** streamlit 1.44.0 is installed in the system Python 3.12 environment. The `requirements-311.txt` freeze records it at 1.44.0. It is NOT in `pyproject.toml` as an optional dependency.

**Latest stable:** 1.54.0 (released 2026-02-04).

**Breaking changes from 1.44 to 1.54:**
- `st.experimental_get_query_params` and `st.experimental_set_query_params` removed (use `st.query_params`)
- `st.experimental_user` removed (use `st.user`)
- Widget identity now key-only (prevents unwanted state resets)

None of these affect a new dashboard (no legacy experimental API to migrate). The upgrade is safe for a greenfield Streamlit app.

**Add to pyproject.toml:**

```toml
[project.optional-dependencies]
research = [
  "streamlit>=1.44",        # Dashboard — upgrade to >=1.54.0 for latest fixes
  "jupyterlab>=4.5",        # Notebook environment
]
```

**Why Streamlit over alternatives:**
- **Dash (Plotly):** More flexible but requires callbacks and React component knowledge. Streamlit's reactive model is faster to build research explorers.
- **Panel:** Higher capability ceiling but more complex. Not needed for internal research tooling.
- **Gradio:** ML demo-focused. Wrong audience (researchers, not demo consumers).

**Streamlit + Plotly integration:** plotly 6.4.0 is already installed. `st.plotly_chart()` renders plotly figures natively. The existing `viz/all_plots.py` uses matplotlib; Streamlit dashboards should use plotly for interactivity.

**What NOT to add for Streamlit:**
- **streamlit-aggrid:** AgGrid for advanced table display. Useful but adds a JS bundle dependency. Standard `st.dataframe()` is sufficient for MVP.
- **streamlit-plotly-events:** For click-event callbacks on charts. Overkill for a research explorer.
- **Redis / streamlit-caching backends:** The default in-memory cache is sufficient for a single-user research dashboard.

---

## Feature Area 7: Jupyter Notebooks

### Recommendation: ADD jupyterlab>=4.5 to research optional group

**Current state:** `jupyterlab_widgets 3.0.16` is installed (a component), but `jupyterlab` itself is not installed.

**Latest stable:** JupyterLab 4.5.5 (released 2026-02-23, today). Notebook 7.5.3 (released 2026-01-26) is based on JupyterLab 4.5.

**Python requirements:** >=3.9 — fully compatible with Python 3.12.

**Installation:**
```bash
pip install jupyterlab>=4.5
```

JupyterLab 4.5 auto-installs `notebook>=7` as a dependency, providing the classic notebook interface too.

**Supporting packages for polished demo notebooks:**

| Package | Version | Purpose | Decision |
|---------|---------|---------|---------|
| jupyterlab | >=4.5.5 | Notebook IDE | ADD |
| jupytext | >=1.16 | Sync .ipynb ↔ .py (git-friendly) | OPTIONAL (see note) |
| nbconvert | >=7.0 | Convert notebooks to HTML/PDF for docs | OPTIONAL |

**jupytext note:** For notebooks committed to git, `jupytext` converts `.ipynb` files to `.py` format (percent format or light format), making diffs readable and preventing large JSON blob commits. If notebooks will be version-controlled, add jupytext. If notebooks are scratch space only, skip.

**What NOT to add:**
- **papermill:** Parameterized notebook execution. Useful for CI-run notebooks but adds complexity. Not needed for a research demo milestone.
- **nbformat:** Already a jupyterlab transitive dependency; do not pin separately.
- **ipywidgets:** Interactive widgets for notebooks. `jupyterlab_widgets 3.0.16` is already installed as a transitive dependency. `ipywidgets` itself can be added if specific interactive widgets are needed in demos.

---

## Dependency Conflict Assessment

### numpy 2.4.1 vs vectorbt 0.28.1

vectorbt's `setup.py` specifies `numpy>=1.16.5` (no upper bound). The installed numpy 2.4.1 is higher than tested. The codebase's `MEMORY.md` documents that vectorbt 0.28.1 works in production on this machine. The vbt_runner.py and orchestrator.py are complete and functional.

**Risk:** numpy 2.x introduced breaking changes in some internal C APIs. vectorbt 0.28.1 was released in 2022 and was not tested against numpy 2.x at release time. However, since the existing backtests already work (MEMORY.md: "All 3 signal generators work"), this is not a blocker for v0.9.0.

**Mitigation:** Do not upgrade numpy. Pin `numpy<3.0` in pyproject.toml to prevent accidental major upgrade.

### scipy 1.17.0 requirements

scipy 1.17.0 (2026-01-10) requires `numpy>=1.26.4`. The installed numpy 2.4.1 satisfies this. No conflict.

### scikit-learn 1.8.0

scikit-learn 1.8.0 requires numpy, scipy. Both present at compatible versions. No conflict.

### numba 0.64.0

numba 0.64.0 in the Python 3.12 environment. This is compatible with numpy 2.x (numba >=0.61 added numpy 2.0 support). No conflict.

**The .venv311 environment** has numba 0.57.1 with numpy 1.24.4. This is intentionally isolated and is not affected by the Python 3.12 environment changes.

---

## Complete pyproject.toml Changes for v0.9.0

```toml
[project.optional-dependencies]
# NEW: Research & experimentation tooling
research = [
  "streamlit>=1.44",         # Dashboard (upgrade from 1.44.0 to latest stable >=1.54.0)
  "jupyterlab>=4.5",         # Notebook environment
  "jupytext>=1.16",          # Git-friendly notebook format (optional but recommended)
]

# UPDATED: Existing viz group — add seaborn if IC heatmaps needed in notebooks
viz = [
  "matplotlib>=3.6",
  "seaborn>=0.13",           # ADD if notebooks need heatmap-style IC plots
]
```

**Core dependencies: NO CHANGES.**

The `pyproject.toml` core `dependencies` block does not need modification. scipy, numpy, scikit-learn, plotly are already installed in the environment. They should not be pinned in core deps unless they are direct imports in the library layer (they currently are not — they're used by scripts and analysis modules).

---

## What NOT to Add (Summary)

| Do Not Add | Why |
|------------|-----|
| TA-Lib | Requires C binary install on Windows (`C:\ta-lib`); KAMA/DEMA/TEMA/HMA are 30 lines each in numpy |
| pandas-ta 0.4.71b0 | Beta only; requires Python >=3.12 AND numba >=0.60; incompatible with .venv311; 4 indicators not worth beta dep |
| mlfinlab | Effectively discontinued on PyPI; moved to paid private tier |
| quantstats | Adds yfinance/requests overhead; conflicts with existing metrics.py API contract |
| skfolio | CombinatorialPurgedCV is one class; brings cvxpy-base + clarabel solver as hard deps |
| timeseriescv | PyPI version 0.2 is inactive; no new releases |
| alphalens-reloaded | Requires seaborn + statsmodels; IC math is 80 lines in scipy; plot style conflicts with existing viz |
| MLflow | Overkill for feature lifecycle in a single-developer lab; adds server process or file backend |
| DVC | Dataset versioning via git; mismatched with PostgreSQL-backed feature store |
| Feast | Enterprise feature serving (online/offline stores); far beyond current scale |
| papermill | Parameterized notebook execution; not needed for research demo milestone |
| Weights & Biases | SaaS external service dependency; self-contained codebase policy |
| Panel / Dash | More complex than Streamlit; not needed for internal research explorer |
| pypbo | PSR math is 15 lines; not worth a library dependency |

---

## Complete New Packages Summary

| Package | Recommended Version | Purpose | New or Already Installed |
|---------|---------------------|---------|--------------------------|
| streamlit | >=1.44 (upgrade to 1.54.0) | Research dashboard | ALREADY INSTALLED (1.44.0) — upgrade |
| jupyterlab | >=4.5.5 | Notebook environment | NEW |
| jupytext | >=1.16 | Git-friendly .ipynb format | NEW (optional) |
| seaborn | >=0.13.2 | Heatmap plots in notebooks | NEW (optional, only if needed) |

**scipy, numpy, scikit-learn, plotly:** Already installed at compatible versions. No installation needed. PSR, IC, Spearman, and PurgedKFold implementations use these directly.

**KAMA, DEMA, TEMA, HMA:** Implemented in-house with numpy. Zero new dependencies.

---

## Installation Commands

```bash
# Minimum required for v0.9.0 features
pip install "jupyterlab>=4.5"

# Upgrade Streamlit (already installed, bump to latest)
pip install "streamlit>=1.54.0"

# Optional: git-friendly notebooks
pip install "jupytext>=1.16"

# Optional: seaborn for IC heatmaps in notebooks
pip install "seaborn>=0.13.2"
```

**No pyproject.toml core dep changes required.** Add `research` optional group to pyproject.toml for documentation purposes.

---

## Sources

### HIGH Confidence (PyPI / Official Docs — verified February 2026)

- [streamlit PyPI](https://pypi.org/project/streamlit/) — version 1.54.0 confirmed
- [Streamlit 2026 release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2026) — breaking changes verified
- [jupyterlab PyPI](https://pypi.org/project/jupyterlab/) — version 4.5.5 confirmed (2026-02-23)
- [scikit-learn PyPI](https://pypi.org/project/scikit-learn/) — version 1.8.0 (2025-12-10) confirmed
- [scipy PyPI / Release Notes](https://docs.scipy.org/doc/scipy/release.html) — version 1.17.0 (2026-01-10), requires numpy>=1.26.4
- [seaborn PyPI](https://pypi.org/project/seaborn/) — version 0.13.2 (2024-01-25) confirmed; no 0.14 released
- [statsmodels PyPI](https://pypi.org/project/statsmodels/) — version 0.14.6 (2025-12-05) confirmed
- [alphalens-reloaded PyPI](https://pypi.org/project/alphalens-reloaded/) — version 0.4.6 (2025-06-02), Production/Stable
- [skfolio PyPI](https://pypi.org/project/skfolio/) — version 0.15.5 (2026-02-10), sklearn-compatible
- [TA-Lib PyPI](https://pypi.org/project/TA-Lib/) — version 0.6.8 (2025-10-20); C binary required on Windows
- [TA-Lib install docs](https://ta-lib.github.io/ta-lib-python/install.html) — Windows C binary requirement confirmed
- [pandas-ta PyPI](https://pypi.org/project/pandas-ta/) — version 0.4.71b0 (2025-09-14); beta only; requires Python>=3.12 + numba>=0.60
- [numba 0.57.1 PyPI](https://pypi.org/project/numba/0.57.1/) — Python 3.8-3.11 only
- [scikit-learn TimeSeriesSplit docs](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) — gap parameter confirmed
- [timeseriescv Snyk health](https://snyk.io/advisor/python/timeseriescv) — inactive status confirmed
- [rubenbriones/Probabilistic-Sharpe-Ratio](https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio/blob/master/src/sharpe_ratio_stats.py) — PSR formula uses scipy.stats.norm.cdf, skew, kurtosis
- Local `pip show` commands — confirmed installed versions for scipy 1.17.0, scikit-learn 1.8.0, numpy 2.4.1, plotly 6.4.0, arch 7.2.0, numba 0.64.0, streamlit 1.44.0

### MEDIUM Confidence (WebSearch verified with official source)

- [pandas-ta installation docs](https://www.pandas-ta.dev/getting-started/installation/) — numba >=0.60.0 requirement confirmed
- [mlfinlab GitHub](https://github.com/hudson-and-thames/mlfinlab) — discontinued PyPI releases, moved to paid tier (multiple sources agree)
- [skfolio model selection docs](https://skfolio.org/user_guide/model_selection.html) — CombinatorialPurgedCV sklearn compatibility confirmed
- [KAMA algorithm — Perry Kaufman](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average) — algorithm formula verified
- [HMA formula](https://medium.com/@basics.machinelearning/hull-moving-average-hma-using-python-48262e18d0fb) — WMA(2*WMA(n/2)-WMA(n), sqrt(n)) confirmed

---

*Stack research for: v0.9.0 Research & Experimentation*
*Researched: 2026-02-23*
