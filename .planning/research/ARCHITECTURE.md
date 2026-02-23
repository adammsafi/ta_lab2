# Architecture Patterns

**Domain:** Quant research & experimentation platform (v0.9.0 milestone)
**Existing codebase:** ta_lab2 v0.8.0 — multi-TF pipeline with 50+ tables, 22M+ rows
**Researched:** 2026-02-23
**Confidence:** HIGH (direct codebase inspection, no guesswork)

---

## Existing Architecture Summary

The v0.8.0 system is a layered, database-centric quant pipeline. Understanding it precisely
is prerequisite to integrating the v0.9.0 features without breaking what already works.

### Pipeline Stages (current)

```
cmc_price_histories7
        |
        v
[Bar Builders] --> cmc_price_bars_multi_tf (+ 4 cal variants + _u)
        |
        v
[EMA Refreshers] --> cmc_ema_multi_tf (+ 4 cal variants + _u)
        |           PK: (id, ts, tf, period)
        |
        v
[Returns] --> cmc_returns_bars_multi_tf (+ 4 cal variants + _u)
              cmc_returns_ema_multi_tf (+ 4 cal variants + _u)
        |
        v
[Feature Refresh] --> cmc_vol, cmc_ta --> cmc_features
                      PK: (id, ts, tf, alignment_source)
        |
        v
[Regime Refresh] --> cmc_regimes, cmc_regime_flips,
                     cmc_regime_stats, cmc_regime_comovement
        |
        v
[Signal Generators] --> cmc_signals_ema_crossover,
                        cmc_signals_rsi_mean_revert,
                        cmc_signals_atr_breakout
        |
        v
[Backtest] --> cmc_backtest_runs, cmc_backtest_trades, cmc_backtest_metrics
```

### Key Abstractions (existing, do not break)

| Abstraction | Location | Pattern | Constraints |
|-------------|----------|---------|-------------|
| `BaseEMAFeature` | `features/m_tf/base_ema_feature.py` | Template Method | PK: (id, ts, tf, period); `period` is an integer count in units of tf |
| `BaseEMARefresher` | `scripts/emas/base_ema_refresher.py` | Template Method | State table per refresher; NullPool workers; TF-split parallelism |
| `BaseFeature` | `scripts/features/base_feature.py` | Template Method | Scoped DELETE+INSERT per (ids, tf); `_get_table_columns()` for DDL sync |
| `BaseBarBuilder` | `scripts/bars/base_bar_builder.py` | Template Method | All bar tables share same column contract |
| `run_daily_refresh.py` | `scripts/run_daily_refresh.py` | Subprocess orchestrator | bars->EMAs->regimes->stats; FAIL-gated stats |

---

## Critical Design Question: Adaptive MAs and the EMA Table Structure

The central architectural question for v0.9.0 is whether KAMA, DEMA, TEMA, and HMA
(Adaptive Moving Averages, or AMAs) can share the existing `cmc_ema_multi_tf*` tables
or need their own table family.

### Why Sharing Is Incompatible

The existing EMA table family has this PK: `(id, ts, tf, period)`

The `period` column is an integer that means "EMA period in units of tf."
This is meaningful and unambiguous for standard EMAs: period=21 on tf=1D means
a 21-bar exponential moving average.

Adaptive MAs do not have a single `period` parameter:
- **KAMA** (Kaufman Adaptive MA): `efficiency_ratio_period`, `fast_period`, `slow_period`
- **DEMA** (Double EMA): `period` (equivalent to EMA, but computed differently — not a drop-in)
- **TEMA** (Triple EMA): `period` (same parameter name, different computation)
- **HMA** (Hull MA): `period` (same parameter name, uses WMA internally)

Forcing KAMA's three parameters into a single integer `period` column would require:
- A synthetic key (e.g., a lookup table mapping integer IDs to parameter tuples)
- That lookup to be joined on every query — adding complexity and breaking the
  clean query pattern `WHERE period IN (9, 21, 50)`

Additionally, the existing `cmc_ema_multi_tf_u` unified table has:
```sql
PRIMARY KEY (id, ts, tf, period)
```
KAMA rows would collide with EMA rows if they happened to share the same period integer,
because the table has no `indicator_type` discriminator column.

### Recommended Design: Separate AMA Table Family

Create a new table family for adaptive MAs:

**New table:** `cmc_ama_multi_tf`
**PK:** `(id, ts, tf, indicator, params_hash)`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER NOT NULL | Asset ID, FK to dim_assets |
| `ts` | TIMESTAMPTZ NOT NULL | Bar close timestamp |
| `tf` | TEXT NOT NULL | Timeframe, FK to dim_timeframe.tf |
| `indicator` | TEXT NOT NULL | 'KAMA', 'DEMA', 'TEMA', 'HMA' |
| `params_hash` | TEXT NOT NULL | SHA-256 of JSON params (12 chars, collision-safe at this scale) |
| `ama` | DOUBLE PRECISION | Adaptive MA value |
| `d1` | DOUBLE PRECISION | First derivative (per-bar diff) |
| `d2` | DOUBLE PRECISION | Second derivative |
| `params_json` | JSONB | Full parameter set: {"er_period":10,"fast":2,"slow":30} |
| `tf_days` | INTEGER | Denormalized from dim_timeframe |
| `roll` | BOOLEAN NOT NULL DEFAULT false | Consistent with EMA table convention |
| `ingested_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | For sync watermark |

**Companion dim table:** `dim_ama_params`
| Column | Type | Notes |
|--------|------|-------|
| `params_hash` | TEXT NOT NULL | PK — SHA-256 of canonical JSON |
| `indicator` | TEXT NOT NULL | 'KAMA', 'DEMA', 'TEMA', 'HMA' |
| `params_json` | JSONB NOT NULL | Full parameters |
| `label` | TEXT | Human-readable: "KAMA_10_2_30" |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | |

This design:
- Avoids polluting the EMA table family with a different semantic
- Allows querying all AMA types in a single table
- Stores full params without a synthetic integer key
- The `params_hash` approach is familiar to anyone working with MLflow experiment tracking

**No unified _u table in phase 1.** The existing _u tables unify across alignment variants
(multi_tf + cal_iso + cal_us + cal_anchor_us + cal_anchor_iso). For v0.9.0, only the
canonical multi_tf alignment is needed. Add cal variants in a future milestone.

### AMA Hierarchy: Reuse BaseEMAFeature Pattern

The existing `BaseEMAFeature` hierarchy is clean and can be extended. DEMA, TEMA, and HMA
are single-parameter — they fit the `period` slot cleanly (just computed differently
from a standard EMA). KAMA is the outlier with three parameters.

**Recommended class hierarchy:**

```
BaseAMAFeature (new, analogous to BaseEMAFeature)
    |
    +-- DEMAFeature    (period -> maps to integer, period=N computes DEMA(N))
    +-- TEMAFeature    (period -> maps to integer)
    +-- HMAFeature     (period -> maps to integer)
    +-- KAMAFeature    (params: er_period, fast_period, slow_period)
```

`BaseAMAFeature` is NOT a subclass of `BaseEMAFeature` because:
- Output table is different (`cmc_ama_multi_tf` vs `cmc_ema_multi_tf`)
- PK columns are different (`params_hash` vs `period`)
- The `write_to_db` upsert logic differs (conflict on `params_hash` not `period`)

However, `BaseAMAFeature` can copy the same Template Method pattern: `load_source_data`,
`get_tf_specs`, `compute_ama_for_tf`, `write_to_db`. The bar loading logic
(`load_source_data`) can be shared by importing the same helper used in EMA subclasses.

**Refresher class:** `BaseAMARefresher` (analogous to `BaseEMARefresher`)

- Reuses same state management pattern: `EMAStateManager` or a new `AMAStateManager`
  with same schema (id, indicator, params_hash, last_ts)
- Reuses same worker function pattern (NullPool, per-ID workers)
- CLI arguments: `--indicator KAMA,DEMA,TEMA,HMA`, `--params-set default`

**Integration into orchestrator:**
`run_all_ema_refreshes.py` should be renamed or supplemented with `run_all_ma_refreshes.py`
which runs both EMA and AMA refreshers. The daily orchestrator `run_daily_refresh.py`
adds `--amas` flag (or includes AMAs in `--emas` flag — the simpler choice is to
fold AMAs into the existing `--emas` stage, since they share the same dependency on bars).

---

## IC Evaluation: New Component

**What it is:** Spearman Information Coefficient (IC) between features and forward returns,
IC decay across lags, IC turnover.

**Where it lives:** `src/ta_lab2/analysis/ic_eval.py` (new file)

**Source data:** `cmc_features` (feature store) + `cmc_returns_bars_multi_tf_u` (forward returns)

**Integration points:**

| Touch point | Change type | Notes |
|-------------|-------------|-------|
| `analysis/feature_eval.py` | Extend | Current `feature_target_correlations()` uses Pearson; add Spearman IC version |
| `analysis/ic_eval.py` | New | IC, IC decay, ICIR, IC turnover |
| New DB table: `cmc_ic_results` | New | (id, feature_name, tf, lag, ic, ic_ir, computed_at) |

**Schema for `cmc_ic_results`:**
```sql
CREATE TABLE IF NOT EXISTS public.cmc_ic_results (
    run_id          TEXT NOT NULL,         -- UUID or timestamp-based run identifier
    feature_name    TEXT NOT NULL,
    tf              TEXT NOT NULL,
    lag             INTEGER NOT NULL,      -- forward return horizon in bars
    ic              DOUBLE PRECISION,      -- Spearman IC
    ic_ir           DOUBLE PRECISION,      -- IC / std(IC) = IC information ratio
    ic_mean         DOUBLE PRECISION,      -- rolling mean of IC
    n_obs           INTEGER,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, feature_name, tf, lag)
);
```

**No changes to daily refresh pipeline.** IC evaluation is on-demand analysis,
not a scheduled refresh step. It runs from notebooks or CLI scripts in the analysis
tier, not from `run_daily_refresh.py`.

---

## PSR: Replace Placeholder in metrics.py

**Current state:** `backtests/metrics.py` contains `psr_placeholder()` — a sigmoid
approximation that is acknowledged as a stub. The comment explicitly calls for
"the full PSR (Lopez de Prado) or use mlfinlab."

**Recommended approach:** Implement PSR natively in `metrics.py` (no new library).

Lopez de Prado's PSR formula (from "The Sharpe Ratio Efficient Frontier", 2012):
```
PSR(SR*) = Phi(((SR_hat - SR*) * sqrt(T-1)) / sqrt(1 - skew*SR_hat + (kurtosis-1)/4 * SR_hat^2))
```
Where `Phi` is the standard normal CDF.

This requires: scipy.stats.norm.cdf — scipy is already in the environment.

**Integration:**
- Modify `backtests/metrics.py`: Replace `psr_placeholder()` with `psr()` that takes
  `returns: pd.Series, benchmark_sr: float = 0.0` and returns a float in (0, 1).
- Add `dsr()` function (Deflated Sharpe Ratio — accounts for multiple testing).
- No schema changes — PSR is a scalar metric stored in `cmc_backtest_metrics` already.
- Update `summarize()` to call the real implementation.

**Confidence:** MEDIUM — the formula is well-documented but the exact scaling
(T-1 vs T, population vs sample moments) needs verification against a reference
implementation before trusting outputs.

---

## Purged K-Fold: New Component in backtests/

**Current state:** `backtests/splitters.py` has expanding walk-forward by calendar years.
No purging, no embargo. This is inadequate for financial ML (label overlap creates
look-ahead bias in CV).

**What purged K-fold adds:**
- Embargo: N bars dropped after each train fold boundary (prevents label overlap)
- Purging: removes training samples whose labels overlap with test period
- Lopez de Prado's CPCV (Combinatorial Purged Cross-Validation) is the gold standard

**Recommended design:**

```python
# backtests/splitters.py additions

@dataclass
class PurgedKFoldSplit:
    """One fold of purged time-series K-fold."""
    fold: int
    train_idx: np.ndarray
    test_idx: np.ndarray
    embargo_idx: np.ndarray    # excluded indices between train and test


def purged_kfold_splits(
    index: pd.DatetimeIndex,
    n_splits: int = 5,
    embargo_pct: float = 0.01,   # fraction of total samples to embargo
) -> list[PurgedKFoldSplit]:
    """
    Purged K-fold splitter for time-series data.
    Implements the approach from Lopez de Prado (2018), Chapter 7.
    """
    ...
```

**Integration points:**

| Touch point | Change type | Notes |
|-------------|-------------|-------|
| `backtests/splitters.py` | Add functions | Add `purged_kfold_splits()`, `PurgedKFoldSplit` |
| `backtests/orchestrator.py` | Optional | Plumb purged CV into parameter sweep if desired |
| `analysis/parameter_sweep.py` | Optional | Support new splitter type |

No schema changes — purged K-fold is a computation utility, results go into
existing `cmc_backtest_metrics`.

---

## Feature Experimentation Framework: New Subsystem

**What it is:** A config-driven registry that tracks feature lifecycle
(experimental -> promoted -> deprecated) and enables systematic IC evaluation
across features without ad-hoc scripting.

**Design notes from MEMORY.md:**
> Config-driven feature registry with lifecycle: experimental -> promoted -> deprecated
> Compute engine reuses existing indicator functions on persisted base data
> Evaluation layer for IC, feature importance, stability across assets/TFs

**Recommended architecture:**

### New Tables

**`dim_feature_registry`** — tracks feature definitions and lifecycle:
```sql
CREATE TABLE IF NOT EXISTS public.dim_feature_registry (
    feature_id      SERIAL PRIMARY KEY,
    feature_name    TEXT NOT NULL UNIQUE,    -- e.g. 'kama_10_2_30_d1'
    indicator_type  TEXT NOT NULL,           -- 'AMA', 'TA', 'VOL', 'RETURNS'
    params_json     JSONB,                   -- {"er_period":10, "fast":2, "slow":30}
    status          TEXT NOT NULL DEFAULT 'experimental',  -- experimental/promoted/deprecated
    source_table    TEXT NOT NULL,           -- 'cmc_ama_multi_tf' or 'cmc_features'
    source_column   TEXT NOT NULL,           -- column name in source table
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at     TIMESTAMPTZ,
    deprecated_at   TIMESTAMPTZ,
    notes           TEXT
);
```

**`cmc_feature_experiments`** — IC evaluation results linked to registry:
```sql
CREATE TABLE IF NOT EXISTS public.cmc_feature_experiments (
    experiment_id   TEXT NOT NULL,           -- e.g. 'exp_kama_2026_02_23'
    feature_id      INTEGER REFERENCES dim_feature_registry(feature_id),
    tf              TEXT NOT NULL,
    lag             INTEGER NOT NULL,
    ic_mean         DOUBLE PRECISION,
    ic_ir           DOUBLE PRECISION,
    ic_decay_half   INTEGER,                 -- lag at which IC drops to 50% of peak
    n_assets        INTEGER,
    n_obs           INTEGER,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (experiment_id, feature_id, tf, lag)
);
```

### New Python Module: `src/ta_lab2/research/`

This is a new top-level module (not under `scripts/` or `analysis/`) because it
spans computation, evaluation, and persistence in ways that do not fit cleanly into
the existing layer structure.

```
src/ta_lab2/research/
    __init__.py
    registry.py          # FeatureRegistry class -- CRUD on dim_feature_registry
    experiment.py        # ExperimentRunner -- run IC eval for a set of features
    ic_eval.py           # IC computation (imported from analysis/ or standalone)
    lifecycle.py         # promote(), deprecate(), compare_generations()
    reports.py           # summary tables, markdown reports
```

**`FeatureRegistry`** is a thin wrapper over `dim_feature_registry`:
- `register(feature_name, indicator_type, params, source_table, source_column)`
- `promote(feature_name)` / `deprecate(feature_name)`
- `list_by_status(status)` -> list of feature definitions
- `get(feature_name)` -> single feature definition

**`ExperimentRunner`**:
- Accepts a list of feature names from the registry
- Loads feature values from their `source_table.source_column`
- Computes IC against forward returns from `cmc_returns_bars_multi_tf_u`
- Writes results to `cmc_feature_experiments`
- No side effects on the main pipeline tables

**Integration with existing pipeline:**
None required for the framework itself. The framework reads from existing tables;
it does not write back to them. New AMA values (from `cmc_ama_multi_tf`) become
candidates for registration in `dim_feature_registry` and inclusion in experiments.

---

## Streamlit Dashboard: New Application

**What it is:** Two-panel research explorer and pipeline monitor.

**Where it lives:** `apps/dashboard/` at project root (not inside src/).

**Rationale for `apps/` not `src/ta_lab2/viz/`:** Streamlit apps are not library code.
They should not be importable as package modules and should not affect the package's
import graph. Dashboard code in the package root would pollute package imports, add
Streamlit as a hard dependency, and slow down test collection.

```
apps/
    dashboard/
        __init__.py     (empty)
        app.py          # Streamlit entry point
        pages/
            01_pipeline_monitor.py
            02_feature_explorer.py
            03_backtest_results.py
            04_regime_view.py
        components/
            charts.py   # plotly wrappers
            tables.py   # st.dataframe helpers
            db.py       # cached DB queries via st.cache_data
```

**Data flow:** All DB reads, no writes. Queries existing tables directly via SQLAlchemy.
Streamlit's `st.cache_data` (TTL-based) handles query caching to avoid hammering the DB.

**Integration points:**

| Touch point | Change type | Notes |
|-------------|-------------|-------|
| `src/ta_lab2/config.py` | Read-only | Dashboard imports `resolve_db_url()` for connection |
| `src/ta_lab2/analysis/` | Read-only | Dashboard calls existing `evaluate_signals()`, `sharpe()`, etc. |
| `pyproject.toml` | Add optional dep group | `[project.optional-dependencies] viz = ["streamlit", "plotly"]` |
| No pipeline tables modified | None | Dashboard is read-only |

**CI:** Dashboard is excluded from test coverage. Add a basic
`streamlit run apps/dashboard/app.py --headless` smoke-test in CI only if Streamlit is
installed (conditional on optional dep group being installed).

---

## Jupyter Notebooks: Integration Pattern

**Where they live:** `notebooks/` at project root (already conventional for quant projects).

**Pattern:** All notebooks import from `ta_lab2` package. They do not copy-paste pipeline
code. This enforces that notebook code is a thin consumer of library functions.

```
notebooks/
    01_ama_exploration.ipynb
    02_ic_evaluation_walkthrough.ipynb
    03_purged_kfold_demo.ipynb
    04_feature_experimentation_demo.ipynb
    05_regime_overlay_backtest.ipynb
```

**No architectural changes needed** — notebooks are consumers, not producers.
The `resolve_db_url()` connection helper already works from any Python context.

---

## Component Boundaries

### New vs Modified

| Component | New or Modified | Description |
|-----------|-----------------|-------------|
| `cmc_ama_multi_tf` (table) | New | Adaptive MA values, PK: (id, ts, tf, indicator, params_hash) |
| `dim_ama_params` (table) | New | Human-readable parameter set registry |
| `dim_feature_registry` (table) | New | Feature lifecycle tracking |
| `cmc_feature_experiments` (table) | New | IC evaluation results |
| `cmc_ic_results` (table) | New | Per-feature IC by lag |
| `features/m_tf/ama_operations.py` | New | Pure AMA computation functions (KAMA, DEMA, TEMA, HMA) |
| `features/m_tf/base_ama_feature.py` | New | Template Method for AMA computation |
| `features/m_tf/ama_multi_timeframe.py` | New | Concrete AMAFeature subclasses |
| `scripts/emas/refresh_cmc_ama_multi_tf.py` | New | Refresher for AMA table |
| `scripts/emas/run_all_ma_refreshes.py` | New | Orchestrate both EMA and AMA |
| `backtests/metrics.py` | Modify | Replace `psr_placeholder()` with real PSR/DSR |
| `backtests/splitters.py` | Modify | Add `purged_kfold_splits()`, `PurgedKFoldSplit` |
| `analysis/ic_eval.py` | New | Spearman IC, IC decay, ICIR |
| `analysis/feature_eval.py` | Modify | Add Spearman variant alongside existing Pearson |
| `research/` module | New | FeatureRegistry, ExperimentRunner, lifecycle |
| `apps/dashboard/` | New | Streamlit app (outside src/) |
| `notebooks/` | New | End-to-end demo notebooks |
| `run_daily_refresh.py` | Modify | Add `--amas` flag or fold into `--emas` stage |
| `pyproject.toml` | Modify | Add optional `[viz]` dependency group |
| `sql/features/` | New files | DDL for new tables |
| Alembic migrations | New revisions | Schema changes go through Alembic (v0.8.0 MIGR-03) |

### Components That Must NOT Change

| Component | Why |
|-----------|-----|
| `cmc_ema_multi_tf*` table family | Existing PK is (id,ts,tf,period); altering breaks all queries |
| `cmc_ema_multi_tf_u` | Unified view with existing alignment_source tracking; stable contract for signal generators |
| `BaseEMAFeature` / `BaseEMARefresher` | Signal generators depend on the EMA table schema indirectly |
| `cmc_features` 112-column schema | Signal generators query this directly; column changes require migration + signal regeneration |
| `run_daily_refresh.py` stage ordering | bars->EMAs->regimes->stats ordering is a hard dependency |

---

## Data Flow Changes

### Adding AMAs to the Pipeline

```
[Existing bars] --> cmc_price_bars_multi_tf_u
                        |
          +-------------+
          |             |
          v             v
  [EMA Refreshers]  [AMA Refreshers]    -- new parallel branch
   cmc_ema_multi_tf  cmc_ama_multi_tf   -- new table
          |             |
          +------+-------+
                 |
                 v (signal generators can optionally JOIN cmc_ama_multi_tf)
         [Signal Generators]
```

AMAs are a parallel branch, not a replacement. The existing EMA branch is unchanged.
Signal generators can optionally JOIN `cmc_ama_multi_tf` for AMA-based crossover signals
in a future milestone, using the same LEFT JOIN pattern as EMA queries.

### Adding IC Evaluation

```
cmc_features + cmc_ama_multi_tf --> [IC Evaluator] --> cmc_ic_results
cmc_returns_bars_multi_tf_u --------^                  cmc_feature_experiments
dim_feature_registry ---------------^
```

This is a read-from-pipeline, write-to-research-tables pattern. No pipeline tables
are modified by IC evaluation.

---

## Schema Changes Needed

All schema changes must go through Alembic (established in v0.8.0 MIGR-03).

| Migration | Priority | Description |
|-----------|----------|-------------|
| `revision_1_ama_tables` | Phase 1 | Create `cmc_ama_multi_tf`, `dim_ama_params` |
| `revision_2_registry_tables` | Phase 2 | Create `dim_feature_registry`, `cmc_feature_experiments`, `cmc_ic_results` |
| No changes to existing tables | — | AMA design deliberately avoids altering existing EMA tables |

---

## Build Order Recommendation

Dependencies define the only valid build order:

**Phase 1: AMA Computation Engine**
- `ama_operations.py` (pure functions, no DB)
- `base_ama_feature.py` (template class)
- `ama_multi_timeframe.py` (concrete subclasses)
- Alembic migration: `cmc_ama_multi_tf`, `dim_ama_params`
- `refresh_cmc_ama_multi_tf.py` (refresher script)
- Wire into `run_daily_refresh.py`

Rationale: AMA values must exist before they can be registered in the feature
registry or used in IC evaluation. Building the compute engine first also validates
the table schema before dependent code is written.

**Phase 2: PSR + Purged K-Fold**
- Modify `metrics.py` (standalone, no DB dependency)
- Add to `splitters.py` (standalone)

These are self-contained modifications with no inter-phase dependencies.
Can be done in parallel with Phase 1 if needed.

**Phase 3: IC Evaluation**
- `analysis/ic_eval.py` (depends on cmc_features existing — already present)
- Alembic migration: `cmc_ic_results`

Works immediately on existing `cmc_features` columns without Phase 1 being complete.
Phase 1 completion unlocks IC evaluation of AMA columns.

**Phase 4: Feature Experimentation Framework**
- `research/registry.py`
- `research/experiment.py`
- Alembic migration: `dim_feature_registry`, `cmc_feature_experiments`

Requires: IC evaluation working (Phase 3) to power the experiment runner.

**Phase 5: Streamlit Dashboard**
- `apps/dashboard/` (read-only, depends on all preceding tables existing)

Requires all data layers operational. Dashboard adds no new data; it visualizes existing.

**Phase 6: Notebooks**
- End-to-end demos referencing all new components.
- Requires all preceding phases complete.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Adding `indicator_type` to cmc_ema_multi_tf

**What:** Adding a discriminator column to the existing EMA table family to store AMAs.
**Why bad:** Requires a nullable column with backward-compat NULL for all existing rows.
Breaks the clean integer `period` semantics. Forces period=NULL for multi-param AMAs.
Requires migration of 14.8M+ rows. Breaks all queries that assume `period` is the only
disambiguation needed.
**Instead:** Separate `cmc_ama_multi_tf` table with `params_hash` PK column.

### Anti-Pattern 2: Storing KAMA as period=synthetic_int

**What:** Using a lookup table `dim_kama_params` where `param_id` (integer) is stored
in the EMA table's `period` column.
**Why bad:** Period integers in the EMA table are meaningful to operators and signal
generators. Mixing semantic ints (EMA periods) with opaque lookup IDs in the same
column is a maintenance hazard. The dim_signals table already uses a similar pattern
and required extra care — do not repeat it here.
**Instead:** `params_hash` in a new table, no sharing of the period column.

### Anti-Pattern 3: IC Evaluation in the Daily Refresh Pipeline

**What:** Running IC evaluation as a stage in `run_daily_refresh.py`.
**Why bad:** IC evaluation over 109 TFs and dozens of features across 100+ assets is
potentially hours of computation. Running it daily would make the refresh pipeline
unreliable. IC is also inherently a research/analysis operation — it should not block
daily data production.
**Instead:** On-demand via CLI or notebooks. Daily refresh is strictly
bars->EMAs->AMAs->regimes->stats.

### Anti-Pattern 4: Streamlit Dashboard Inside src/ta_lab2/

**What:** Putting the dashboard in `src/ta_lab2/viz/dashboard/`.
**Why bad:** Dashboard imports are not package imports. Streamlit requires running as a
script, not as a module. Dashboard code in the package root would pollute package
imports, add Streamlit as a hard dependency, and slow down test collection.
**Instead:** `apps/dashboard/` at project root, with Streamlit in optional dep group.

### Anti-Pattern 5: Notebooks That Copy-Paste Pipeline Code

**What:** Notebooks that re-implement feature computation or database queries inline.
**Why bad:** Diverges from the library. Notebook results become non-reproducible as
the library evolves. Creates two sources of truth.
**Instead:** Notebooks import from `ta_lab2`. Library functions are the single
implementation.

---

## Scalability Considerations

| Concern | Current (22M rows) | With AMA addition | Mitigation |
|---------|-------------------|-------------------|------------|
| cmc_ama_multi_tf row count | 0 | ~6-8M rows (4 indicators x 109 TFs x ~15K rows/asset/indicator) | Index on (id, tf, indicator); partial index on canonical rows |
| IC evaluation query latency | N/A | Potentially slow over full history | Partition by tf; run per-asset batches, aggregate offline |
| dim_feature_registry size | 0 | Tens to hundreds of rows | Negligible — no performance concern |
| Dashboard query latency | N/A | Reads from 50+ tables | `st.cache_data` TTL; materialized views for common aggregations |

---

## Open Questions for Phase-Level Research

1. **KAMA parameter sets:** What specific parameter values are canonical for this project?
   (Standard defaults: er_period=10, fast=2, slow=30.) Need to decide before building
   `dim_ama_params` seed data.

2. **AMA in daily refresh:** Should AMAs run in the same subprocess as EMAs (extending
   `run_all_ema_refreshes.py`) or in a separate orchestrator step? Simpler path is to
   extend the EMA orchestrator. Cleaner path is a new `--amas` step.

3. **Signal generators for AMAs:** Will v0.9.0 add AMA-based signals, or just compute
   AMA values for research? If signals are in scope, a new `cmc_signals_ama_crossover`
   table is needed.

4. **PSR benchmark Sharpe:** The PSR formula requires a benchmark Sharpe ratio `SR*`.
   Industry convention is `SR* = 0` (beat cash) or `SR* = 1.0` (bar for live strategy).

5. **Notebook execution in CI:** Should notebooks run as part of CI? Requires DB
   connection. Typically excluded from CI in quant projects; test by converting to
   scripts with `--headless` instead.

---

## Sources

All findings are from direct codebase inspection at commit 26678109 (2026-02-23).

- `src/ta_lab2/features/m_tf/base_ema_feature.py` — Template Method pattern, PK design
- `src/ta_lab2/scripts/emas/base_ema_refresher.py` — Refresher pattern, state management
- `src/ta_lab2/scripts/features/base_feature.py` — Feature write pattern
- `src/ta_lab2/scripts/run_daily_refresh.py` — Orchestrator stage ordering
- `src/ta_lab2/backtests/metrics.py` — Confirmed `psr_placeholder()` stub
- `src/ta_lab2/backtests/splitters.py` — Confirmed no purging/embargo
- `src/ta_lab2/analysis/feature_eval.py` — Confirmed Pearson-only IC
- `sql/features/030_cmc_ema_multi_tf_u_create.sql` — Confirmed PK: (id, ts, tf, period)
- `sql/features/042_cmc_ta.sql` — Confirmed feature table schema pattern
- `.planning/codebase/ARCHITECTURE.md` — Prior architecture mapping (2026-01-21)
- `.planning/milestones/v0.8.0-REQUIREMENTS.md` — Deferred features list confirmed
- MEMORY.md — feature_experimentation.md design notes, AMA status
- PSR formula: Lopez de Prado (2012) "The Sharpe Ratio Efficient Frontier" (MEDIUM confidence on implementation details)
