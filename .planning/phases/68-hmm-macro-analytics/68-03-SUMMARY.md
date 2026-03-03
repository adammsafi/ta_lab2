---
phase: 68-hmm-macro-analytics
plan: 03
subsystem: macro-analytics
tags: [transition-matrix, hmm, lead-lag, markov, regime, daily-refresh, pipeline, cli]

# Dependency graph
requires:
  - phase: 68-01-hmm-macro-analytics-foundation
    provides: cmc_macro_transition_probs table (Alembic migration e0d8f7aec87a)
  - phase: 68-02-hmm-macro-analytics-classifiers
    provides: HMMClassifier and LeadLagAnalyzer classes importable from ta_lab2.macro
  - phase: 67-macro-regime-classifier
    provides: cmc_macro_regimes table with rule-based regime labels (profile='default')
provides:
  - TransitionProbMatrix class: static + rolling transition matrices for rule-based and HMM sources
  - get_transition_prob() module-level wrapper for programmatic access
  - refresh_macro_analytics.py CLI: unified entry point for all three Phase 68 tools
  - run_daily_refresh.py updated: macro_analytics stage wired after macro_regimes, before regimes
affects:
  - 69+ (transition probabilities available for downstream regime duration estimation)
  - daily pipeline --all now includes macro_analytics stage

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DISTINCT ON (date) ORDER BY date, model_run_date DESC: deduplicates expanding-window HMM refits so each date maps to exactly one state label"
    - "Row-normalized transition matrices: zero-count rows produce 0.0 (not NaN, not omitted)"
    - "get_transition_prob() scopes MAX(window_end_date) to regime_source + window_type (not global): prevents cross-contamination when sources have different date ranges"
    - "Per-tool try/except in refresh_macro_analytics.py: one failure does not kill remaining tools"

key-files:
  created:
    - "src/ta_lab2/macro/transition_probs.py -- TransitionProbMatrix (716 lines)"
    - "src/ta_lab2/scripts/macro/refresh_macro_analytics.py -- unified CLI (313 lines)"
  modified:
    - "src/ta_lab2/macro/__init__.py -- Added TransitionProbMatrix and get_transition_prob to public API"
    - "src/ta_lab2/scripts/run_daily_refresh.py -- Added run_macro_analytics() + TIMEOUT_MACRO_ANALYTICS + --macro-analytics/--no-macro-analytics flags"

key-decisions:
  - "Rolling window = 252 days (1 trading year): balances recency vs. statistical stability for transition counting"
  - "Zero-count (from, to) pairs emit probability 0.0: every state remains in the output matrix even if never observed -- prevents downstream KeyError on rare regime pairs"
  - "get_transition_prob() with window_end_date=None works for both static and rolling (no ValueError): uses COALESCE with MAX scoped per regime_source+window_type"
  - "DISTINCT ON scoped per (regime_source, window_type) in MAX subquery: rule-based and HMM sources started collecting data at different dates; a global MAX would silently return the wrong date"

patterns-established:
  - "Transition matrix storage: flat row-per-cell format (from_state, to_state, probability, count) -- one DB row per matrix cell, not JSON blob per matrix"
  - "Pipeline stage ordering: macro_features -> macro_regimes -> macro_analytics -> regimes (per-asset)"

# Metrics
duration: 6min
completed: 2026-03-03
---

# Phase 68 Plan 03: TransitionProbMatrix + CLI + Pipeline Wiring Summary

**Regime transition probability matrices (static + 252-day rolling, rule-based + HMM sources) with DISTINCT ON deduplication, row-normalized output, and unified CLI orchestrating all three Phase 68 tools into the daily refresh pipeline**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-03T11:15:28Z
- **Completed:** 2026-03-03T11:21:24Z
- **Tasks:** 2 of 2
- **Files modified:** 4

## Accomplishments

- TransitionProbMatrix (716 lines): compute_static() + compute_rolling() + compute_all() + upsert_results() with DISTINCT ON deduplication for HMM sources and row-normalized probability matrices
- get_transition_prob() module-level wrapper with scoped MAX(window_end_date) per regime_source + window_type -- no cross-source contamination, works for both static and rolling with None date
- refresh_macro_analytics.py (313 lines): unified CLI running all three Phase 68 tools with per-tool --hmm-only/--lead-lag-only/--transition-only flags and independent try/except isolation
- run_daily_refresh.py: run_macro_analytics() function with TIMEOUT_MACRO_ANALYTICS=900s, pipeline ordering macro_features -> macro_regimes -> macro_analytics -> regimes, --all includes stage

## Task Commits

Each task was committed atomically:

1. **Task 1: Build TransitionProbMatrix module** - `55205617` (feat)
2. **Task 2: Create refresh_macro_analytics.py CLI and wire into daily refresh** - `1f279561` (feat)

## Files Created/Modified

- `src/ta_lab2/macro/transition_probs.py` -- TransitionProbMatrix: static + rolling matrices for rule_based and hmm sources; get_transition_prob() wrapper; DISTINCT ON HMM deduplication; row-normalized output with 0.0 zero-count rows
- `src/ta_lab2/scripts/macro/refresh_macro_analytics.py` -- Unified CLI for HMM + lead-lag + transition probs; per-tool flags; per-tool try/except; --dry-run/--verbose/--full/--force-refit/--covariance-type
- `src/ta_lab2/macro/__init__.py` -- Extended public API with TransitionProbMatrix and get_transition_prob in both imports and __all__
- `src/ta_lab2/scripts/run_daily_refresh.py` -- run_macro_analytics() function, TIMEOUT_MACRO_ANALYTICS=900, --macro-analytics/--no-macro-analytics flags, execution block between macro_regimes and regimes

## Decisions Made

- **DISTINCT ON deduplication in _load_hmm_regimes:** HMM expanding-window refits produce multiple rows per date (one per model_run_date). `DISTINCT ON (date) ORDER BY date, model_run_date DESC` ensures the most recent model_run_date wins per date, preventing duplicate transitions in the matrix computation.
- **Zero-count rows emit 0.0, not omitted:** Every (from_state, to_state) pair that ever appeared in the label sequence is included in the output matrix, even if never observed as a transition. This prevents downstream KeyError and allows consumers to distinguish "never observed" (0.0) from "not computed" (missing row).
- **MAX(window_end_date) scoped to regime_source + window_type:** Rule-based and HMM sources may have different date ranges (e.g. HMM fitting requires minimum 504 rows). The subquery in get_transition_prob() is scoped to the matching source and window type to prevent cross-source date contamination.
- **TIMEOUT_MACRO_ANALYTICS=900s:** HMM fitting (10 random restarts x 2-3 state models) on ~5 years of FRED data can take 2-5 minutes; lead-lag scanning 38 features x 2 assets x 121 lags adds another 1-2 minutes. 15 minutes provides comfortable headroom without blocking the daily refresh.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `max_date` variable in compute_rolling()**
- **Found during:** Task 1 verification (ruff check)
- **Issue:** `max_date = dates[-1]` was assigned but never used (F841)
- **Fix:** Removed the unused variable assignment
- **Files modified:** src/ta_lab2/macro/transition_probs.py
- **Verification:** ruff check -- All checks passed
- **Committed in:** 55205617 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 -- lint correctness)
**Impact on plan:** Trivial fix. No scope changes, no architectural impact.

## Issues Encountered

- Pre-commit hook (ruff-format) reformatted both Task 1 and Task 2 files on first commit attempt. Required re-staging reformatted files. Normal pre-commit hook behavior, not a code issue.

## User Setup Required

None - no external service configuration required. All modules require only an SQLAlchemy engine connected to the marketdata database.

## Next Phase Readiness

- Phase 68 is now complete (all 3 plans). MREG-10 (HMM), MREG-11 (lead-lag), MREG-12 (transitions) all have operational classes and CLI + pipeline integration.
- Daily refresh `--all` automatically runs macro_analytics after macro_regimes.
- Downstream consumers (Phase 69+) can query cmc_macro_transition_probs via get_transition_prob() for regime duration estimation and path analysis.
- No blockers.

---
*Phase: 68-hmm-macro-analytics*
*Completed: 2026-03-03*
