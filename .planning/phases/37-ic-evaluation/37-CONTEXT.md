# Phase 37: IC Evaluation - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Score any feature column for predictive power across forward-return horizons, broken down by regime, with significance testing and results persisted to the database. Requirements: IC-01 through IC-08.

This phase delivers library functions, a CLI script, a DB table (via Alembic), and a simple plot helper. It does NOT include the ExperimentRunner (Phase 38), Streamlit dashboard (Phase 39), or notebooks (Phase 40).

</domain>

<decisions>
## Implementation Decisions

### Forward-return horizons
- Horizons are **bar-based** (1, 2, 3, 5, 10, 20, 60 bars), with calendar-day equivalent derived via `dim_timeframe.tf_days_nominal`
- Default horizon list is `[1, 2, 3, 5, 10, 20, 60]`, **overridable** by caller via parameter
- When asset has fewer bars than a requested horizon: **skip that horizon + log warning**, return NaN for it
- Forward returns computed as **both arithmetic and log** by default — both return types included in results
- Rolling IC window defaults to **63 bars**, overridable by caller
- IC decay plot helper included using **Plotly** (interactive, works in notebooks and Streamlit)

### IC invocation model
- Core `compute_ic()` takes a **single feature Series** — simple, composable API
- **Batch wrapper** `batch_compute_ic()` loops over a features DataFrame and concatenates results
- IC computed **per-asset** by default; **cross-asset pooled** mode supported via flag (`pool_assets=True`)
- Caller can pass raw pandas data directly (library stays DB-agnostic)
- **DB helper** function loads feature data from `cmc_features` or `cmc_ema_multi_tf_u` by column name, then feeds into `compute_ic`
- **CLI script** (`run_ic_eval.py`) with `--asset-id`, `--tf`, `--feature`, `--horizons` flags — writes to `cmc_ic_results`. Follows `compute_psr.py` pattern.

### Regime IC breakdown
- Split IC by **both `trend_state` and `vol_state`** from `cmc_regimes` — two independent breakdowns
- Sparse regime handling: **Claude's discretion** on threshold and behavior (minimum sample size guard)
- No regime data for an asset: **fall back to full-sample IC** with `regime_label='all'`
- Results stored as **separate rows per regime** in `cmc_ic_results` — one row per `(asset, feature, horizon, regime_col, regime_label)`

### Persistence and recompute
- CLI script writes to `cmc_ic_results`; library returns DataFrames without persisting
- **Separate `save_ic_results()` function** for persistence — CLI uses it, notebooks can too
- Default behavior: **append with computed_at timestamp** (keeps evaluation history)
- `--overwrite` flag enables **upsert** (ON CONFLICT DO UPDATE) for clean re-evaluation
- Unique key: `(asset_id, tf, feature, horizon, regime_col, regime_label, train_start, train_end)`
- `cmc_ic_results` table created via **Alembic migration** chained from Phase 36 head (`5f8223cfbf06`)

### Claude's Discretion
- Sparse regime threshold (minimum bars per regime before returning NaN vs computing)
- Internal implementation of cross-asset pooling
- Exact CLI flag names and help text
- `save_ic_results()` function signature details
- Batch wrapper parallelization strategy (if any)

</decisions>

<specifics>
## Specific Ideas

- `dim_timeframe.tf_days_nominal` for bar-to-calendar-day conversion (not `dim_period` which is for indicator lookback windows)
- Plotly for IC decay plot — interactive hover/zoom in both notebooks and Streamlit
- Append-by-default persistence matches the project's "audit trail" philosophy (psr_results also keeps history)
- train_start/train_end in the unique key allows evaluating the same feature on different train windows without collision

</specifics>

<deferred>
## Deferred Ideas

- Cross-sectional IC (quantile returns across assets) — v1.0+ ADV-01
- IC-driven automated feature selection — Phase 38 ExperimentRunner
- IC visualization in Streamlit dashboard — Phase 39
- IC exploration notebook — Phase 40

</deferred>

---

*Phase: 37-ic-evaluation*
*Context gathered: 2026-02-24*
