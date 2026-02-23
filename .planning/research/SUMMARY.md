# Research Summary: v0.9.0 Research & Experimentation

**Project:** ta_lab2
**Domain:** Quant research platform — adaptive indicators, statistical evaluation, purged CV, feature lifecycle, visualization
**Researched:** 2026-02-23
**Confidence:** HIGH (all four research files grounded in codebase inspection + verified library versions)

---

## Executive Summary

v0.9.0 adds the evaluation and experimentation layer that v0.8.0's polished pipeline was built to feed into. The six feature groups — adaptive MAs, IC evaluation, PSR, purged CV, feature experimentation, and Streamlit dashboard — are architecturally separable and build in a clear dependency order without touching any production pipeline table. The core insight from research is that nearly every new capability can be implemented with zero new library dependencies: scipy, numpy, scikit-learn, and plotly are already installed at compatible versions, and all four adaptive MA algorithms reduce to 30-100 lines of numpy each. The only genuinely new dependency is `jupyterlab>=4.5`.

The central architectural decision for the milestone is that adaptive MAs (KAMA, DEMA, TEMA, HMA) must get their own table family — `cmc_ama_multi_tf` with a `params_hash` PK column — and must not share the existing `cmc_ema_multi_tf` namespace. Mixing them would silently corrupt signal generators because every LEFT JOIN in the signal layer queries `cmc_ema_multi_tf_u WHERE period = :p` with no indicator-type discriminator. The new `BaseAMAFeature` / `BaseAMARefresher` hierarchy follows the same Template Method pattern as the EMA layer and wires into `run_daily_refresh.py` as a parallel branch that leaves the EMA branch entirely untouched.

The highest single risk in the milestone is the PSR column in `cmc_backtest_metrics`: the existing `psr_placeholder()` is a logistic sigmoid with no statistical meaning, and its values are stored under the column name `psr`. A database migration that renames those rows to `psr_legacy` must be the first step in the PSR phase — before any formula code is written — or historical and real PSR values will be silently mixed in every downstream query and dashboard. The second highest risk is the fragile numpy/numba/vectorbt version triangle: the baseline environment must be locked (`pip freeze > requirements-lock-v0.9.0-baseline.txt`, `numpy>=2.4,<2.5` pinned in `pyproject.toml`) before any dependency additions.

---

## Key Findings

Cross-cutting discoveries that affect multiple phases:

1. **Zero new core library dependencies.** scipy 1.17.0, numpy 2.4.1, scikit-learn 1.8.0, and plotly 6.4.0 already cover PSR (norm.cdf, skew, kurtosis), IC/Spearman correlation, BH correction, the PurgedKFold BaseCrossValidator interface, and all adaptive MA math. This holds true only if the version triangle (numpy/numba/vectorbt) is locked before any pip installs.

2. **The AMA table must be a new family, not an extension of the EMA family.** KAMA's three parameters (er_period, fast_period, slow_period) cannot fit the integer `period` column without either a synthetic lookup key or a discriminator column. Either approach breaks the existing signal generator join pattern. The clean solution — `cmc_ama_multi_tf` with `(id, ts, tf, indicator, params_hash)` PK — is a one-time schema decision that must be made in DDL before any computation code is written.

3. **IC must never be computed over the full history for feature selection.** IC at time t uses future return at t+h, so IC computed over full history integrates signal from the most recent bars. If that IC drives feature promotion, features are selected with implicit future-information leakage. The fix is structural: `train_start` and `train_end` must be required (not optional) parameters on every IC function.

4. **PSR and the psr_legacy migration are a unit.** The sigmoid values stored as `psr` in `cmc_backtest_metrics` produce rankings incompatible with real PSR values. Both must be addressed atomically: Alembic migration to rename the column → then implement the formula. Doing them in any other order creates a contaminated column.

5. **Feature promotion requires Benjamini-Hochberg correction.** Evaluating 50 experimental features simultaneously at IC threshold 0.05 produces 2-3 expected false discoveries by chance. Promoted noise features reach live strategies. `scipy.stats.false_discovery_control()` is already available in scipy 1.17.0 and must be a hard gate in the promotion logic.

6. **The Streamlit engine must use NullPool.** The codebase already uses NullPool throughout to avoid connection pooling issues in multiprocessing (MEMORY.md). Using the default QueuePool in the dashboard engine conflicts with this and causes connection errors during `run_daily_refresh --all` executions.

---

## Recommended Stack

All v0.9.0 features are implemented in-house using already-installed libraries. See `.planning/research/STACK.md` for full version details.

**Already installed — reuse directly:**
- `scipy 1.17.0` — PSR formula (norm.cdf, skew, kurtosis), Spearman IC (spearmanr), BH correction (false_discovery_control)
- `numpy 2.4.1` — all four adaptive MA algorithms (KAMA, DEMA, TEMA, HMA are single-pass or two-pass array operations)
- `scikit-learn 1.8.0` — BaseCrossValidator interface for PurgedKFold
- `plotly 6.4.0` — Streamlit renders it natively via st.plotly_chart()
- `streamlit 1.44.0` — already installed; upgrade to 1.54.0 (no breaking changes for a greenfield app)

**Genuinely new:**
- `jupyterlab >= 4.5.5` — notebook environment (not currently installed)
- `jupytext >= 1.16` — optional; git-friendly .ipynb format
- `seaborn >= 0.13.2` — optional; only if IC heatmaps in notebooks require it

**What not to add:**
- TA-Lib: requires C binary install to `C:\ta-lib` on Windows; breaks CI reproducibility
- pandas-ta 0.4.71b0: beta-only; incompatible with .venv311 environment
- mlfinlab: effectively discontinued on PyPI (moved to paid tier)
- alphalens-reloaded: adds seaborn + statsmodels for 80 lines of scipy math
- skfolio: CombinatorialPurgedCV is one class; pulls in cvxpy-base + clarabel solver
- MLflow / DVC / Feast / W&B: architecturally mismatched for a single-developer PostgreSQL quant lab

**pyproject.toml changes needed:**
- Pin `numpy>=2.4,<2.5` and `numba>=0.64,<0.65` in core deps (locks the fragile triangle)
- Add `[project.optional-dependencies] research = ["streamlit>=1.44", "jupyterlab>=4.5", "jupytext>=1.16"]`

---

## Expected Features

See `.planning/research/FEATURES.md` for full table-stakes / differentiators / anti-features per area.

**Must have for v0.9.0 (table stakes — each area has critical gaps vs mature platforms):**

Adaptive MAs:
- Correct formula for each type: KAMA with Efficiency Ratio, DEMA as 2*EMA - EMA(EMA), TEMA as 3*EMA1 - 3*EMA2 + EMA3, HMA using WMA (not EWM)
- Full multi-TF pipeline parity with EMAs: (id, ts, tf, indicator, params_hash) PK, d1/d2 derivatives, min-obs guard
- Efficiency Ratio (ER) as a stored column in KAMA table — it is itself an IC candidate

IC Evaluation:
- Spearman (rank) IC, not Pearson — Pearson is dominated by crypto's fat-tailed return outliers
- IC decay table across horizons [1, 2, 3, 5, 10, 20, 60 bars]
- Rolling IC time series (63-bar window) and IC-IR (mean / std)
- IC computed only on training windows; train_start/train_end as required parameters

PSR:
- Replace psr_placeholder() stub with full Lopez de Prado formula using scipy
- Minimum sample guard (return NaN when n < 30; warn when n < 100)
- Alembic migration to rename legacy sigmoid values to psr_legacy before any real PSR is stored

Purged K-Fold:
- Embargo gap + label purging
- PurgedKFoldSplitter class accepting t1_series (label end timestamps) as a required input
- Compatible with sklearn BaseCrossValidator interface

Feature Experimentation Framework:
- YAML-based registry with lifecycle states: experimental / promoted / deprecated
- Compute experimental features on demand from base data (no DB persistence until promotion)
- IC evaluation wired into ExperimentRunner for systematic feature scoring
- Benjamini-Hochberg correction as a hard gate before any promotion decision

Streamlit Dashboard:
- Pipeline Monitor (Mode B) first: reads existing tables (asset_data_coverage, stats), zero new infrastructure
- Research Explorer (Mode A) second: IC score table, equity curves, regime timeline, feature comparison

**Should have (differentiators that add research value):**
- IC by regime (join IC computation with cmc_regimes labels)
- IC significance testing (t-stat and p-value on rolling IC)
- Feature version history in registry (added_version, promoted_version, deprecated_version)
- DSR (Deflated Sharpe Ratio) — implement after purged CV and organized trial tracking
- MinTRL (Minimum Track Record Length) — inverse of PSR
- CPCV (Combinatorial Purged Cross-Validation) — required for PBO; high value, high complexity

**Defer to v1.0+ (complexity or architecture dependency not met):**
- Quantile returns analysis — requires cross-sectional asset universe, not per-asset time series
- KAMA crossover signal generator — compute and evaluate AMA values first; signal after IC validates them
- Automated Alembic migration on feature promotion — build registry first, promotion path second
- PBO (Probability of Backtest Overfitting) via CPCV — requires CPCV + organized trial tracking
- Notebooks — build after IC and PSR are working; notebooks showcase those capabilities

---

## Architecture Approach

v0.9.0 adds three structural layers to the existing system without modifying any production pipeline table. See `.planning/research/ARCHITECTURE.md` for full schemas, class hierarchies, and file-level component map.

**Layer 1: Data computation — AMAs parallel to EMAs**

The AMA branch mirrors the EMA branch structurally but is entirely separate. New `cmc_ama_multi_tf` table with `(id, ts, tf, indicator, params_hash)` PK; companion `dim_ama_params` for human-readable labels. New `BaseAMAFeature` hierarchy (NOT a subclass of `BaseEMAFeature` — different PK, different write logic, different table). `BaseAMARefresher` reuses NullPool worker pattern. AMAs wire into `run_daily_refresh.py` as a parallel branch after bars, at the same dependency level as EMAs.

**Layer 2: Analysis — research, not production pipeline**

`analysis/ic_eval.py` (new): Spearman IC, decay, ICIR — reads cmc_features + cmc_returns_bars_multi_tf_u. `cmc_ic_results` table: on-demand results, never part of daily refresh. `backtests/metrics.py` (modify): replace psr_placeholder with real PSR/DSR. `backtests/splitters.py` (modify): add PurgedKFoldSplit and purged_kfold_splits(). IC evaluation is on-demand only — not a daily refresh stage. Running IC over 109 TFs and 100+ assets could take hours; it must never block the production pipeline.

**Layer 3: Research subsystem + presentation**

New `src/ta_lab2/research/` module: FeatureRegistry, ExperimentRunner, lifecycle management. New tables: `dim_feature_registry`, `cmc_feature_experiments`. Dashboard lives at `apps/dashboard/` at project root — not inside `src/` (Streamlit is not library code; keeping it outside prevents package import pollution and avoids adding streamlit as a hard dep). Notebooks live at `notebooks/` at project root — thin consumers of ta_lab2 package, never re-implementors.

**Major components (new and modified):**
1. `cmc_ama_multi_tf` + `dim_ama_params` tables — adaptive MA value store with params_hash PK
2. `BaseAMAFeature` + `BaseAMARefresher` + concrete subclasses — computation hierarchy
3. `analysis/ic_eval.py` — Spearman IC, IC decay, ICIR, cmc_ic_results persistence
4. `backtests/metrics.py` — PSR formula replacement (psr_legacy migration first)
5. `backtests/splitters.py` — PurgedKFoldSplitter with t1_series input
6. `src/ta_lab2/research/` — FeatureRegistry, ExperimentRunner, lifecycle
7. `dim_feature_registry` + `cmc_feature_experiments` tables — registry and experiment results
8. `apps/dashboard/` — Streamlit pipeline monitor + research explorer
9. `notebooks/` — end-to-end demo notebooks

**Components that must not change:**
- `cmc_ema_multi_tf*` table family and PK — signal generators depend on it directly
- `cmc_features` 112-column schema — signal generators query this; changes require migration + signal regen
- `run_daily_refresh.py` stage ordering (bars → EMAs → regimes → stats)
- `BaseEMAFeature` and `BaseEMARefresher` — leave undisturbed; extend by analogy, not modification

---

## Critical Pitfalls

See `.planning/research/PITFALLS.md` for full details, warning signs, and phase assignments.

**1. AMA namespace collision corrupts signal generators silently (CRITICAL)**
Inserting AMA data into the `cmc_ema_multi_tf` namespace contaminates every signal generator's LEFT JOIN. Row counts stay correct; backtest metrics shift without any error. Prevention: define `cmc_ama_multi_tf` DDL with `(id, ts, tf, indicator, params_hash)` PK as the first deliverable of Phase 1, before any computation code is written.

**2. PSR sigmoid values mixed with real PSR values in the same DB column (CRITICAL)**
The existing `psr_placeholder()` sigmoid is stored as `psr` in `cmc_backtest_metrics`. A strategy with SR=1.5 scores ~0.82 from the sigmoid and potentially ~0.97 from real PSR — radically different rankings, silently mixed. Prevention: Alembic migration renaming `psr` → `psr_legacy` for all pre-migration rows must be committed before any real PSR code is written.

**3. IC over full history leaks future information into feature selection (CRITICAL)**
IC is backward-looking but feature selection based on full-history IC uses information from near-current bars that overlap with any subsequent test period. Prevention: `train_start` and `train_end` must be required (not optional) parameters on every IC function from day one. Exploratory IC over full history is labeled separately.

**4. PurgedKFold without t1_series under-purges multi-bar labels (CRITICAL)**
A 30-bar forward return at bar t spans [t, t+30]. Date-range-based purging misses training samples whose labels extend into the test period. The mlfinlab library has a documented bug (issue #295) with exactly this behavior. Prevention: implement PurgedKFoldSplitter from scratch with `t1_series` as a required input; add post-construction fold validation assertions.

**5. numpy/numba/vectorbt version triangle breaks silently on any pip install (CRITICAL)**
vectorbt 0.28.1 was not tested against numpy 2.x. Any new package that declares numpy as a dependency may trigger resolution that bumps numpy above 2.4.x and silently breaks backtests. Prevention: capture `pip freeze > requirements-lock-v0.9.0-baseline.txt` and pin `numpy>=2.4,<2.5` and `numba>=0.64,<0.65` in `pyproject.toml` before any dependency additions. Run `python -c "import vectorbt; import numba; print('ok')"` after every pip install.

**6. KAMA warm-up on incremental refresh produces wrong values (CRITICAL)**
KAMA's recurrence requires a correct seed from full history. An incremental refresh loading only recent bars starts from a wrong seed, producing values that look plausible but are numerically incorrect. Prevention: load `max(period) * 10` bars before the first date being persisted — the `start - warmup_days` pattern already established in `BaseEMARefresher`.

**7. Streamlit re-runs entire script on every widget interaction, hammering the DB (CRITICAL)**
A `SELECT * FROM cmc_features WHERE tf='1D'` returning 2M+ rows runs on every filter change. Prevention: wrap all DB queries in `@st.cache_data(ttl=300)`; pre-aggregate IC scores server-side in `cmc_ic_results`; design DB-side aggregation before writing any dashboard UI.

**8. IC-based feature promotion without multiple-comparisons correction promotes noise (CRITICAL)**
Evaluating 50 features simultaneously at IC threshold 0.05 produces 2-3 expected false discoveries. Prevention: `scipy.stats.false_discovery_control()` (Benjamini-Hochberg) must be a hard gate in `ExperimentRunner.promote()`, not an optional enhancement. Require features to pass IC evaluation on a held-out period before promotion.

**Additional pitfalls (moderate priority):**
- HMA uses WMA not EWM — the existing `_ema()` helper cannot be reused; implement `_wma()` separately and unit-test against reference values
- Existing `fillna(method='ffill')` in `feature_eval.py` and `performance.py` will raise TypeError in pandas 3.0 — fix before adding any IC code
- Streamlit on Windows: Watchdog file watcher causes spurious restarts — add `.streamlit/config.toml` with `fileWatcherType = "poll"` in first dashboard commit
- `src/` layout requires `pip install -e .` before Streamlit or notebooks can import `ta_lab2` — document in setup instructions
- Import layer contract: IC/PSR/CV code in `analysis/` must query the DB directly, not import from `signals/` or `scripts/` sibling layers — run `lint-imports` before every PR

---

## Implications for Roadmap

Research establishes a clean dependency DAG. Build order is not arbitrary — each phase unlocks the next.

### Phase 1: AMA Computation Engine

**Rationale:** AMA values must exist before they can be registered in the feature registry or evaluated with IC. Building the compute engine first also validates the table schema (params_hash approach, `indicator` discriminator) before dependent code references it. This is also the riskiest design decision in the milestone — resolving it first prevents the worst-case silent signal corruption.

**Delivers:** `cmc_ama_multi_tf` and `dim_ama_params` DDL + Alembic migration; `ama_operations.py` (pure functions: KAMA, DEMA, TEMA, HMA); `BaseAMAFeature` and `BaseAMARefresher` hierarchies; concrete KAMA/DEMA/TEMA/HMA feature and refresher classes; `run_all_ma_refreshes.py`; AMA stage wired into `run_daily_refresh.py`.

**Avoids:** AMA namespace collision (separate table with params_hash PK, not shared with EMA family); KAMA warm-up corruption (load max(period)*10 bars before first persisted date); HMA computation error (implement _wma() separately, not via _ema()).

**Research flag:** No additional research needed. EMA hierarchy patterns transfer directly; adaptive MA formulas are verified. Open configuration decision: canonical KAMA parameter set (recommended default: er_period=10, fast=2, slow=30 per Kaufman original).

---

### Phase 2: PSR + Purged K-Fold

**Rationale:** Both are self-contained modifications to existing files (`metrics.py`, `splitters.py`) with no dependencies on Phase 1. They can run in parallel with Phase 1. Logically grouped together because both improve backtest validity and the PSR migration is the single highest-risk action in the milestone.

**Delivers:** Alembic migration renaming `psr` → `psr_legacy` for pre-migration rows; real PSR formula in `metrics.py` using scipy (verified against rubenbriones reference implementation); `PurgedKFoldSplitter` class with `t1_series` required input and post-construction fold validation; embargo gap parameterized by label duration in bars (not percentage of observations).

**Avoids:** PSR column mixing (migration-first, formula-second ordering is mandatory); mlfinlab PurgedKFold bug (implement from scratch, never from mlfinlab); embargo under-sizing (compute embargo as `ceil(label_bars / 2)` minimum, not `0.01 * n_obs`).

**Research flag:** No additional research needed. PSR formula is unambiguous; the one implementation detail to verify is T vs T-1 scaling in the denominator — validate against the rubenbriones/Probabilistic-Sharpe-Ratio reference before storing values.

---

### Phase 3: IC Evaluation Engine

**Rationale:** IC evaluation is the primary research metric for v0.9.0 and the scoring engine for the feature experimentation framework. It can run immediately against existing `cmc_features` data (112 columns, already populated) without Phase 1 being complete. Phase 1 completion then unlocks IC evaluation on AMA columns as a natural extension.

**Delivers:** `analysis/ic_eval.py` with spearman_ic(), rolling_ic(), ic_decay_table(), ic_by_regime(); `cmc_ic_results` DB table; Spearman variant added to `feature_eval.py` alongside existing Pearson. Existing `fillna(method='ffill')` deprecated calls in `feature_eval.py` and `performance.py` fixed before any new IC code is added.

**Avoids:** IC future-leakage (train_start/train_end required params, never full-history selection IC); Pearson-on-crypto (Spearman default; Pearson retained for reference); IC instability masking regime-conditional signal (output schema includes asset_id, tf, regime, window_start, window_end from day one).

**Research flag:** No additional research needed. The one item to verify mechanically: the forward-return join alignment — feature at ts t joined with return at ts t+h must use `cmc_returns_bars_multi_tf_u` correctly without look-ahead. Add a unit test that verifies no future data is accessed.

---

### Phase 4: Feature Experimentation Framework

**Rationale:** The framework is the integration layer that wires IC evaluation (Phase 3) into a systematic lifecycle for new features. It depends on IC being solid before feature scores feed the promotion decision. Building it after Phase 3 means BH correction can be added directly to the promotion logic rather than retrofitted.

**Delivers:** `src/ta_lab2/research/` module (FeatureRegistry, ExperimentRunner, lifecycle.py, reports.py); `dim_feature_registry` and `cmc_feature_experiments` Alembic migration; YAML config schema; compute-on-demand for experimental features; promotion path with BH correction gate.

**Avoids:** Zombie features (status field + deprecated_at + retire_after_date in schema from day one; daily refresh filters to `status IN ('experimental', 'active')`); multiple-comparisons promotion of noise (BH correction is a hard gate, not optional); parameter inconsistency corruption (params locked at first write, validated against registry on re-run).

**Research flag:** Needs phase research. The feature registry design is custom — no authoritative quant-specific reference exists (Medium confidence in FEATURES.md). Before implementation, validate the config schema structure and DB table design against the codebase's existing `dim_assets` / `dim_timeframe` / `dim_feature_registry` conventions.

---

### Phase 5: Streamlit Dashboard

**Rationale:** Read-only visualization layer — depends on all preceding data layers being operational. Start with Mode B (Pipeline Monitor) because it reads existing tables with zero new infrastructure; Mode A (Research Explorer) follows once IC results and AMA data are available.

**Delivers:** `apps/dashboard/` with `app.py`, `pages/` (01_pipeline_monitor.py, 02_feature_explorer.py, 03_backtest_results.py, 04_regime_view.py), `components/` (charts.py, tables.py, db.py with NullPool engine); `.streamlit/config.toml` with `fileWatcherType = "poll"` for Windows.

**Avoids:** Query hammering (all DB queries in @st.cache_data(ttl=300)); NullPool conflict (consistent with existing codebase pattern); Streamlit Windows watchdog restarts (.streamlit/config.toml committed in first dashboard PR); src/ layout import failure (pip install -e . documented in dashboard README).

**Research flag:** No additional research needed. Streamlit architecture patterns (apps/ outside src/, pages/ structure, @st.cache_data) are well-documented.

---

### Phase 6: Jupyter Notebooks

**Rationale:** Notebooks are demonstration artifacts. They import from the ta_lab2 package and showcase all v0.9.0 capabilities. Building them last ensures the APIs they call are stable and that notebooks serve as integration tests for the public API surface.

**Delivers:** 3-5 focused notebooks: IC evaluation walkthrough, AMA exploration, purged K-fold demo, feature experimentation demo, regime overlay backtest. Each parameterized with ASSET_ID / TF / START_DATE constants at top. All passing "Restart and Run All" before commit. CI job running `nbconvert --execute` on committed notebooks.

**Avoids:** Hidden cell state non-reproducibility (CI nbconvert --execute); notebook divergence from library (import from ta_lab2, never copy-paste pipeline code); src/ layout import failure (notebook preamble checks sys.path or enforces pip install -e .).

**Research flag:** No additional research needed. JupyterLab 4.5 is well-documented. Decision to make before starting: whether to use jupytext for git-friendly format — recommended yes.

---

### Phase Ordering Rationale

- Phase 1 before Phase 4: AMA values must exist before they can be registered in the experimentation framework.
- Phase 3 before Phase 4: IC evaluation is the scoring engine inside ExperimentRunner; the framework calls IC, not the reverse.
- Phase 2 parallel to Phase 1: PSR and PurgedKFold modify only existing files with no cross-dependencies on the AMA pipeline.
- Phase 5 after Phases 1–4: dashboard has nothing meaningful to display until the data layers are populated.
- Phase 6 last: notebooks are thin consumers; they need stable APIs and populated data.

### Research Flags Summary

| Phase | Research Needed | Reason |
|-------|----------------|--------|
| Phase 1 (AMA Engine) | No | EMA patterns transfer directly; formulas verified; open decision is KAMA parameter defaults |
| Phase 2 (PSR + CV) | No | PSR formula is published; PurgedKFold mechanics are textbook-standard |
| Phase 3 (IC Eval) | No | Spearman IC is well-documented; forward-return join alignment is mechanical verification |
| Phase 4 (Registry) | Yes | Custom design — YAML schema and DB table structure need validation against codebase conventions |
| Phase 5 (Dashboard) | No | Streamlit architecture patterns are well-documented |
| Phase 6 (Notebooks) | No | JupyterLab 4.5 is standard; one optional decision (jupytext) |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI on 2026-02-23; installed versions confirmed via pip show; dependency conflict analysis complete; no experimental packages recommended |
| Features | HIGH | IC/PSR/PurgedKFold standards drawn from primary sources (Lopez de Prado papers, official library docs, QuantConnect implementations); Adaptive MA formulas from Kaufman original source |
| Architecture | HIGH | Based on direct codebase inspection at commit 26678109; all file paths, PK schemas, and class hierarchies verified against actual source files |
| Pitfalls | HIGH | Critical pitfalls confirmed by: codebase inspection (psr_placeholder exists as sigmoid; deprecated fillna calls exist; no t1_series in splitters; numpy/numba unpinned); official changelogs (pandas 2.3 FutureWarning); documented bugs (mlfinlab issue #295) |

**Overall confidence: HIGH**

The one area of Medium confidence is the feature registry design pattern — there is no authoritative quant-specific reference for a single-developer feature lifecycle system. The design is sound architecturally but should be validated against codebase conventions (dim_assets, dim_timeframe patterns) before implementation begins.

### Gaps to Address

**1. KAMA canonical parameter set.** What parameters does this project standardize on? Standard default: er_period=10, fast=2, slow=30 (Kaufman original). If multiple parameter sets are desired from day one, the `dim_ama_params` seed data and refresher CLI (`--params-set`) must accommodate that from the start. Decide before Phase 1 DDL is finalized.

**2. AMA stage in daily refresh — new flag vs extend EMA orchestrator.** Two options: (a) extend `run_all_ema_refreshes.py` to include AMAs (simpler, one fewer step); (b) add `--amas` as a separate stage in `run_daily_refresh.py` (cleaner separation). No clear winner from research; judgment call in Phase 1 planning.

**3. PSR benchmark Sharpe rate (SR*).** The PSR formula requires a benchmark SR*. Industry conventions: SR*=0 (beat cash) or SR*=1.0 (bar for live strategy). The stored value should include `sr_benchmark` and `freq_per_year` as columns in `cmc_backtest_metrics` so PSR is interpretable without code inspection. Decide before writing PSR or the column schema will require a follow-up migration.

**4. AMA-based signals in v0.9.0 scope.** FEATURES.md defers KAMA crossover signal to post-MVP. Confirm this decision holds — if AMA signals are in scope, a `cmc_signals_ama_crossover` table must be added to Phase 1 scope.

**5. PSR formula denominator scaling (T vs T-1).** Several reference implementations differ on whether the denominator uses `n-1` or `n`. The difference is negligible for n > 100 but must be verified against the rubenbriones reference implementation before values are stored. Annotate the code with the specific Bailey/Lopez de Prado 2012 equation number.

**6. Notebook execution in CI.** Should notebooks run in CI (requires DB connection)? Typical quant practice excludes them; a `jupyter nbconvert --to script` syntax check is a lighter alternative. Decide before Phase 6 planning.

---

## Sources

### Primary (HIGH confidence — verified against official docs or direct codebase inspection)

- Local `pip show` commands — confirmed numpy 2.4.1, scipy 1.17.0, scikit-learn 1.8.0, plotly 6.4.0, numba 0.64.0, streamlit 1.44.0
- [streamlit PyPI](https://pypi.org/project/streamlit/) — v1.54.0 confirmed; breaking changes from 1.44 to 1.54 verified against 2026 release notes
- [jupyterlab PyPI](https://pypi.org/project/jupyterlab/) — v4.5.5 confirmed (2026-02-23)
- [scipy PyPI / Release Notes](https://docs.scipy.org/doc/scipy/release.html) — v1.17.0 (2026-01-10); numpy>=1.26.4 requirement
- [scikit-learn PyPI](https://pypi.org/project/scikit-learn/) — v1.8.0 (2025-12-10); TimeSeriesSplit gap parameter confirmed
- [pandas 2.2 changelog](https://pandas.pydata.org/docs/whatsnew/v2.2.0.html) — fillna method deprecation confirmed
- [Streamlit docs: st.cache_resource thread safety](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource) — NullPool recommendation
- [Lopez de Prado: Advances in Financial Machine Learning](https://philpapers.org/rec/LPEAIF) — PSR formula, purged CV mechanics, embargo theory
- [mlfinlab issue #295](https://github.com/hudson-and-thames/mlfinlab/issues/295) — PurgedKFold training-events-overlap-test-events bug documented and confirmed
- Codebase inspection at commit 26678109: `backtests/metrics.py` (psr_placeholder as sigmoid), `analysis/feature_eval.py` (Pearson IC + deprecated fillna at lines 78 and 81), `backtests/splitters.py` (no t1_series), `sql/features/030_cmc_ema_multi_tf_u_create.sql` (PK confirmed), `pyproject.toml` (numpy/numba unpinned confirmed)

### Secondary (MEDIUM confidence — multiple sources agree, practitioner-verified)

- [Quantdare: Probabilistic Sharpe Ratio](https://quantdare.com/probabilistic-sharpe-ratio/) — four-moment PSR formula verified against paper
- [StockCharts: KAMA warm-up requirements](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama) — 10x period warm-up recommendation
- [PyQuant News: IC standard practice](https://www.pyquantnews.com/free-python-resources/real-factor-alpha-how-to-measure-it-with-information-coefficient-and-alphalens-in-python) — IC-IR > 0.5 threshold; Spearman as standard
- [skfolio model selection docs](https://skfolio.org/user_guide/model_selection.html) — CombinatorialPurgedCV mechanics
- [mlfinlab GitHub](https://github.com/hudson-and-thames/mlfinlab) — discontinued PyPI; moved to paid tier
- [TA-Lib install docs](https://ta-lib.github.io/ta-lib-python/install.html) — Windows C binary requirement confirmed
- [pandas-ta installation docs](https://www.pandas-ta.dev/getting-started/installation/) — numba >= 0.60.0 requirement confirmed

### Tertiary (informing design, not implementation)

- [Two Sigma: ML approach to regime modeling](https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/) — IC by regime concept
- [Bailey/Lopez de Prado: Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) — DSR formula and multiple testing context
- [Aalto Scientific Computing: Jupyter notebook pitfalls](https://scicomp.aalto.fi/scicomp/jupyter-pitfalls/) — hidden cell state risks

---

*Research completed: 2026-02-23*
*Ready for roadmap: yes*
