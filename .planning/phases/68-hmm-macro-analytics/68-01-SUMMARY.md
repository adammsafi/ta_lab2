---
phase: 68-hmm-macro-analytics
plan: 01
subsystem: database
tags: [alembic, postgresql, hmmlearn, hmm, macro, lead-lag, transition-matrix, migration]

# Dependency graph
requires:
  - phase: 67-macro-regime-classifier
    provides: cmc_macro_regimes and cmc_macro_hysteresis_state tables; macro regime pipeline
  - phase: 66-fred-derived-features
    provides: fred.fred_macro_features with net_liquidity, vixcls, hy_oas_level columns (HMM inputs)
provides:
  - cmc_hmm_regimes table (PK: date, n_states, model_run_date) for HMM state labels
  - cmc_macro_lead_lag_results table (PK: macro_feature, asset_col, computed_at) for cross-correlation
  - cmc_macro_transition_probs table (PK: regime_source, window_type, window_end_date, from_state, to_state)
  - hmmlearn>=0.3.3 installed and declared in macro_analytics optional-dependency group
affects:
  - 68-02 (HMM classifier writes to cmc_hmm_regimes)
  - 68-03 (lead-lag scanner writes to cmc_macro_lead_lag_results; transition writer to cmc_macro_transition_probs)

# Tech tracking
tech-stack:
  added: ["hmmlearn==0.3.3 (GaussianHMM, Viterbi + Baum-Welch, BIC/AIC model selection)"]
  patterns:
    - "Public schema tables (no schema= arg) for analytics results vs fred schema for raw FRED data"
    - "Partial indexes on boolean flags (is_bic_winner, is_significant) for filtered queries"
    - "JSON text columns (state_means_json, corr_by_lag_json) for storing array/dict results without schema lock-in"
    - "server_default func.now() pattern for ingested_at columns"

key-files:
  created:
    - "alembic/versions/e0d8f7aec87a_hmm_macro_analytics_tables.py"
  modified:
    - "pyproject.toml"

key-decisions:
  - "Used cmc_ prefix for all 3 tables (consistent with existing cmc_macro_regimes, cmc_backtest_runs etc.) rather than context's suggestion to drop prefix -- plan spec took precedence"
  - "Stored corr_by_lag_json as TEXT (not JSONB) to keep migration DB-agnostic for potential non-Postgres testing"
  - "Partial index on is_bic_winner for fast winner queries; full index on date DESC for time-range scans"
  - "window_days nullable: NULL for static (derives from full history), integer for rolling windows"
  - "n_features column in cmc_hmm_regimes: enables detecting model drift when feature set changes"

patterns-established:
  - "Phase 68 analytics tables live in public schema (not fred schema) -- rule: fred schema = raw/derived FRED data; public = computed analytics"
  - "BIC/AIC winner selection stored in table via is_bic_winner boolean: allows querying best model without recomputing"
  - "Transition probability table unified for both rule_based and hmm sources via regime_source column: single query interface for both"

# Metrics
duration: 3min
completed: 2026-03-03
---

# Phase 68 Plan 01: HMM & Macro Analytics Foundation Summary

**Three analytics tables + hmmlearn installed: cmc_hmm_regimes (BIC-selected HMM states), cmc_macro_lead_lag_results (macro vs asset cross-correlation), cmc_macro_transition_probs (rule_based + HMM transition matrices)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-03T10:54:20Z
- **Completed:** 2026-03-03T10:57:18Z
- **Tasks:** 2 of 2
- **Files modified:** 2

## Accomplishments

- hmmlearn 0.3.3 installed and declared in pyproject.toml `macro_analytics` optional-dependency group
- Alembic migration `e0d8f7aec87a` created, chaining from Phase 67 head `d5e6f7a8b9c0` (discovered dynamically via `alembic heads`)
- `cmc_hmm_regimes` table: supports 2-state vs 3-state model comparison via BIC/AIC, partial index on winning model
- `cmc_macro_lead_lag_results` table: stores best lag, correlation, significance, and full JSON profile per (feature, asset, date)
- `cmc_macro_transition_probs` table: unified for rule_based and hmm sources, static and rolling windows

## Task Commits

Each task was committed atomically:

1. **Task 1: Install hmmlearn and update pyproject.toml** - `c67f5443` (chore)
2. **Task 2: Create Alembic migration for 3 Phase 68 tables** - `7ac38681` (feat)

## Files Created/Modified

- `alembic/versions/e0d8f7aec87a_hmm_macro_analytics_tables.py` - DDL for cmc_hmm_regimes, cmc_macro_lead_lag_results, cmc_macro_transition_probs with PKs, indexes, and downgrade
- `pyproject.toml` - Added `[project.optional-dependencies.macro_analytics]` group with hmmlearn>=0.3.3

## Decisions Made

- **cmc_ prefix retained:** Plan spec uses cmc_ prefix consistently; context file suggested dropping it but the plan's column spec took precedence. Maintains naming consistency with cmc_macro_regimes (Phase 67).
- **TEXT vs JSONB for JSON columns:** Used `sa.Text()` for `corr_by_lag_json` and `state_means_json` to keep migration portable. JSONB is PostgreSQL-specific; Phase 68-02/03 can migrate to JSONB if query-time JSON parsing becomes a bottleneck.
- **Partial indexes on booleans:** `idx_cmc_hmm_regimes_winner` (WHERE is_bic_winner = true) and `idx_lead_lag_significant` (WHERE is_significant = true) keep these small and fast for the common "show me winners/significant results" query pattern.
- **window_days nullable:** NULL for static windows (total history length is derived, not fixed); integer for rolling windows. Avoids sentinel values.
- **n_features column:** Enables model drift detection -- if Phase 68-02 adds a 4th input feature, rows with n_features=3 vs 4 can be compared to assess impact.

## Deviations from Plan

None - plan executed exactly as written. The actual Alembic head (`d5e6f7a8b9c0`, Phase 67) differed from the example in the plan (`c4d5e6f7a8b9`, Phase 66) but this was expected and the plan explicitly required dynamic discovery via `alembic heads`. No unplanned fixes needed.

## Issues Encountered

- `alembic upgrade head --sql` (dry-run mode) failed mid-chain on migration `adf582a23467` which uses a conditional `_column_exists()` helper requiring a live DB connection. This is a pre-existing limitation of that legacy migration, not related to Phase 68. The Phase 68 migration itself is syntactically valid and correctly chained (verified via AST parse, `alembic heads` single-head check, and revision metadata inspection).

## User Setup Required

None - no external service configuration required. hmmlearn is a pure Python library with no credentials or external services.

## Next Phase Readiness

- Phase 68-02 (HMM Classifier): Can write to `cmc_hmm_regimes` immediately after migration is applied. Input features (net_liquidity_365d_zscore, vixcls, hy_oas_level) are in fred.fred_macro_features via Phase 66.
- Phase 68-03 (Lead-Lag + Transition): Can write to `cmc_macro_lead_lag_results` and `cmc_macro_transition_probs`. Rule-based source labels come from `cmc_macro_regimes` (Phase 67); HMM labels from `cmc_hmm_regimes` (Phase 68-02).
- No blockers.

---
*Phase: 68-hmm-macro-analytics*
*Completed: 2026-03-03*
