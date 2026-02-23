# Phase 36: PSR + Purged K-Fold - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Statistically sound Sharpe ratio estimates (PSR, DSR, MinTRL) and leakage-free cross-validation (PurgedKFold, CPCV) for backtest results and feature sets. Alembic migration renames existing psr column. Does NOT include IC evaluation (Phase 37), feature experimentation (Phase 38), or new signal generators.

</domain>

<decisions>
## Implementation Decisions

### PSR Formula Behavior
- SR* (benchmark Sharpe) is configurable, default 0 — callers pass `sr_star` param
- Minimum sample: n < 30 returns NaN + log WARNING; n < 100 logs WARNING (matches existing warn-and-continue pattern)
- DSR accepts both modes: full list of Sharpe ratios (exact) OR (best_sharpe, n_trials) tuple (Bailey approximation)
- DSR requires full returns series per trial — computes moments internally for accuracy
- MinTRL returns both bars (n_obs) and approximate calendar days using tf_days_nominal
- MinTRL accepts configurable target_psr threshold (default 0.95)
- PSR auto-persists after backtest AND offers standalone recompute script for historical runs (both paths)

### Alembic Migration Strategy
- Two separate Alembic revisions: (1) rename psr→psr_legacy + add new psr column as NULL, (2) create psr_results table
- Existing rows: copy psr value to psr_legacy, set psr to NULL — recompute on demand later
- psr_results is a separate table (not columns on cmc_backtest_metrics) — keeps metrics table lean
- psr_results includes formula_version column (e.g., 'lopez_de_prado_v1') for future-proofing
- Migration auto-check on startup: run_daily_refresh.py checks alembic current vs head, warns or auto-upgrades

### CV Splitter Interface
- PurgedKFoldSplitter implements sklearn BaseCrossValidator — full compatibility with cross_val_score, GridSearchCV
- t1_series required argument — ValueError when not provided
- Default embargo: max(1, int(0.01 * n)) — 1% of sample size, scaling with data (Lopez de Prado recommended)
- PurgedKFold is splitter-only — yields (train_idx, test_idx), no built-in train/evaluate runner

### Integration Points
- Standalone CLI for PSR: python -m ta_lab2.scripts.backtest.compute_psr --run-id 42 (or --all) plus Python API
- PurgedKFold is splitter-only — caller handles the train/predict/score loop

### Claude's Discretion
- Negative Sharpe handling for PSR (compute normally vs short-circuit to 0)
- Annualization helper inclusion in PSR module
- PSR return type (float vs PSRResult dataclass with raw statistics)
- Module file organization (single psr.py vs separate files)
- CPCV path generation strategy (all combinatorial vs sampled subset)
- psr_results row structure (wide with PSR+DSR+MinTRL per row vs metric_type EAV)
- Downgrade behavior for psr_results table (drop vs leave)
- Package location for PSR/CV modules (stats/ vs evaluation/ vs other)
- Whether backtest runner auto-computes PSR or requires opt-in flag

</decisions>

<specifics>
## Specific Ideas

- PSR must match Lopez de Prado formula exactly (using scipy skew/kurtosis) — not a simplified version
- PurgedKFold from scratch — do NOT use mlfinlab (discontinued, known bug in PurgedKFold issue #295)
- Alembic migration psr→psr_legacy MUST run before any PSR formula code (column name collision risk)
- CPCV generates the combinatorial path matrix required for PBO analysis in Phase 38+

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 36-psr-purged-k-fold*
*Context gathered: 2026-02-23*
