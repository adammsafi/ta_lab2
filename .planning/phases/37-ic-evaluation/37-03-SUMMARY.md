---
phase: 37-ic-evaluation
plan: 03
subsystem: analysis
tags: [ic, information-coefficient, regime, plotly, spearman, batch, visualization]

# Dependency graph
requires:
  - phase: 37-02
    provides: compute_ic, compute_rolling_ic, compute_feature_turnover, _compute_single_ic, _ic_t_stat, _ic_p_value — IC core library (421 lines, 44 tests)
provides:
  - compute_ic_by_regime: IC split by regime label with sparse-regime guard and empty/None fallback
  - batch_compute_ic: loops over multiple feature columns and concatenates results with 'feature' column
  - plot_ic_decay: Plotly bar chart of IC vs horizon with royalblue/lightgray significance coloring
  - plot_rolling_ic: Plotly line chart of rolling IC over time with zero reference line
  - Extended test suite: 61 tests (44 existing + 17 new), all passing
affects: [37-04, 38-feature-experimentation, 39-streamlit-dashboard, 40-notebooks]

# Tech tracking
tech-stack:
  added: [plotly.graph_objects (go.Figure, go.Bar, go.Scatter, add_hline)]
  patterns:
    - regime-conditional IC: pre-built regimes_df accepted by library; l2_label parsing delegated to CLI/DB layer
    - sparse-regime guard: min_obs_per_regime=30 skips regimes with insufficient bars
    - empty/None fallback: compute_ic_by_regime returns full-sample IC with regime_label='all' when no regime data
    - batch wrapper: batch_compute_ic loops compute_ic per column, appends 'feature' col, concatenates
    - significance coloring: royalblue (p < 0.05) vs lightgray (p >= 0.05) in plot_ic_decay
    - zero reference line: add_hline(y=0) in plot_rolling_ic for visual orientation

key-files:
  created: []
  modified:
    - src/ta_lab2/analysis/ic.py
    - tests/analysis/test_ic.py

key-decisions:
  - "Library layer does NOT load from DB: compute_ic_by_regime accepts pre-built regimes_df; l2_label parsing (split('-') -> trend_state/vol_state) happens in CLI/DB helper layer (Plan 04)"
  - "Sparse-regime guard at min_obs_per_regime=30: regimes with fewer bars are silently skipped (no NaN rows stored)"
  - "All-sparse fallback: when ALL regime subsets are below min_obs threshold, fall back to full-sample IC with regime_label='all' rather than returning empty DataFrame"
  - "regime_col and regime_label as output columns (not 'trend_state'/'vol_state'): parameterized so same function handles both column families"
  - "batch_compute_ic excludes 'close' from auto-detected feature_cols by name convention"
  - "Regime-window train bounds: use min/max of common_ts (feature-close intersection within regime) as regime_train_start/regime_train_end"

patterns-established:
  - "Pre-built DataFrame pattern: analytical library functions accept caller-provided DataFrames, no DB coupling"
  - "Significance coloring threshold: 0.05 as sig_threshold default for royalblue/lightgray split"
  - "Plot subtitle pattern: optional horizon + return_type in parentheses after feature name"

# Metrics
duration: 6min
completed: 2026-02-24
---

# Phase 37 Plan 03: IC Regime Breakdown, Batch Wrapper, and Plotly Visualization Summary

**Regime-conditional IC with sparse guard + batch wrapper + Plotly IC decay/rolling charts — 61 tests passing, all 4 new functions exported**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-24T02:11:47Z
- **Completed:** 2026-02-24T02:17:50Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `compute_ic_by_regime()` splits IC by regime label with sparse-regime guard (skip < 30 bars), falls back to full-sample IC with regime_label='all' when regimes_df is None/empty
- `batch_compute_ic()` loops over multiple feature columns and concatenates results into a single DataFrame with a 'feature' column
- `plot_ic_decay()` returns go.Figure bar chart with royalblue/lightgray significance coloring and p-value text annotations
- `plot_rolling_ic()` returns go.Figure line chart with zero reference line and optional horizon/return_type subtitle
- 17 new tests added (5 regime, 4 batch, 4 plot-decay, 4 plot-rolling) on top of 44 existing; all 61 pass

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: regime IC, batch, and Plotly helpers** - `e57ced95` — already committed in the repository as feat(37-04) context (ic.py functions were pre-committed)
2. **Extended test suite** - `64d30446` (test(37-03): add regime IC, batch, and plot test suites)

**Plan metadata:** (to be committed in docs(37-03) final commit)

## Files Created/Modified

- `src/ta_lab2/analysis/ic.py` — Extended with 4 new functions: compute_ic_by_regime (L442), batch_compute_ic (L623), plot_ic_decay (L704), plot_rolling_ic (L773); 1098 lines total
- `tests/analysis/test_ic.py` — Extended with 4 new test classes (TestComputeICByRegime, TestBatchComputeIC, TestPlotICDecay, TestPlotRollingIC); 61 total tests

## Decisions Made

- **Library layer does NOT load from DB:** compute_ic_by_regime accepts pre-built regimes_df. The l2_label parsing (`split('-')` to extract trend_state / vol_state) happens in the CLI/DB helper layer (Plan 04), not here. This keeps the library pure and testable without a DB connection.
- **Sparse-regime guard at min_obs_per_regime=30:** Regimes with fewer bars are silently skipped (no NaN rows stored). If ALL regimes are sparse, falls back to full-sample IC to always return a non-empty DataFrame.
- **regime_col and regime_label as parameterized output columns:** Same function handles both 'trend_state' and 'vol_state' families. The regime_col parameter is echoed as an output column for downstream joins.
- **Regime-window train bounds from common_ts:** Uses min/max of the feature-close intersection within a regime label as synthetic train_start/train_end, preventing boundary masking from nulling all bars.
- **batch_compute_ic excludes 'close' by name:** Auto-detected feature_cols = all numeric columns except 'close', consistent with the convention that close is a separate argument.

## Deviations from Plan

None - plan executed exactly as written. Note: ic.py functions were found pre-committed at HEAD (from plan 37-04 context which ran before this plan in the repository history), so only the test file required a new commit.

## Issues Encountered

- ic.py was discovered to already contain all 4 new functions at HEAD (committed as `e57ced95` feat(37-04)). This is because plan 37-04 context had run previously and added DB helpers alongside the regime/batch/plot functions. The test file (64d30446) was the only new commit needed for this plan. All 61 tests confirmed correct behavior.
- ruff-format pre-commit hook reformatted test_ic.py on first commit attempt; re-staged and committed successfully on second attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- IC library is complete: compute_ic, compute_ic_by_regime, batch_compute_ic, plot_ic_decay, plot_rolling_ic all exported
- Plan 37-04 (DB CLI layer) ready to proceed: load_feature_series, load_regimes_for_asset, save_ic_results already implemented in ic.py
- Phase 38 (Feature Experimentation) can use batch_compute_ic as the scoring engine for ExperimentRunner
- Phase 39 (Streamlit Dashboard) can use plot_ic_decay and plot_rolling_ic for Research Explorer
- Phase 40 (Notebooks) can use all IC functions for interactive feature analysis

---
*Phase: 37-ic-evaluation*
*Completed: 2026-02-24*
