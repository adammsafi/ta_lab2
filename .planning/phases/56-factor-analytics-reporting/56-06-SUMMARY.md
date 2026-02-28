---
phase: 56-factor-analytics-reporting
plan: 06
subsystem: feature-pipeline
tags: [cross-sectional, normalization, window-functions, postgresql, cmc-features, analytics]

# Dependency graph
requires:
  - phase: 56-01
    provides: "6 CS-norm columns added to cmc_features via Alembic migration"
  - phase: 56-03
    provides: "Quintile returns engine reading cmc_features"
provides:
  - "refresh_cmc_cs_norms.py: CLI script computing CS z-scores and PERCENT_RANK via PARTITION BY window functions"
  - "Cross-sectional normalization for 3 pilot features: ret_arith, rsi_14, vol_parkinson_20"
  - "refresh_cs_norms(engine, tf) -> int callable for programmatic use"
  - "CS norms step wired into run_all_feature_refreshes.py Phase 3 (runs after cmc_features)"
affects: ["56-07", "quintile-engine", "ic-sweep", "factor-analytics"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PARTITION BY (ts, tf) CTE pattern for single-pass CS normalization"
    - "n_assets >= 5 guard on COUNT(*) OVER window to skip sparse timestamps"
    - "NULLIF(cs_std, 0) division guard against constant-value assets"
    - "ImportError guard on optional module import in orchestrator"
    - "Separate refresh script for CS columns (not written by existing feature pipeline)"

key-files:
  created:
    - "src/ta_lab2/scripts/features/refresh_cmc_cs_norms.py"
  modified:
    - "src/ta_lab2/scripts/features/run_all_feature_refreshes.py"

key-decisions:
  - "CS norms are computed by a separate refresh script, not by the existing feature pipeline's _get_table_columns() auto-discovery path"
  - "refresh_cs_norms() returns int (sum of cursor.rowcount) for clean orchestrator integration as rows_inserted"
  - "n_assets >= 5 threshold: CS z-scores are meaningless with fewer than 5 comparable assets at a timestamp"
  - "Single transaction per TF: all 3 UPDATE statements wrapped in engine.begin() for atomicity"
  - "NullPool engine in CLI: one-shot connection pattern for standalone invocation"

patterns-established:
  - "Cross-sectional refresh pattern: separate script, runs after feature pipeline, UPDATE only"
  - "ImportError guard: try/except ImportError on optional module import in orchestrator prevents crashes if module missing"

# Metrics
duration: 15min
completed: 2026-02-28
---

# Phase 56 Plan 06: Cross-Sectional Normalization Refresh Summary

**PostgreSQL PARTITION BY window function script that computes CS z-scores and PERCENT_RANK for 3 pilot features (ret_arith, rsi_14, vol_parkinson_20), wired into the feature refresh orchestrator as Phase 3**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-02-28T06:34:27Z
- **Completed:** 2026-02-28T06:50:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created `refresh_cmc_cs_norms.py` with full CLI (--tf, --all-tfs, --dry-run), callable function, and PostgreSQL CTE-based UPDATE pattern
- Populated 95,863 rows across 3 pilot columns for 1D TF: 17,349 non-NULL ret_arith_cs_zscore, 30,368 rsi_14_cs_zscore, 30,082 vol_parkinson_20_cs_zscore
- Verified CS rank values are strictly in [0, 1]; z-score range is [-2.26, +2.26] (well-bounded)
- Wired CS norms step into run_all_feature_refreshes.py as Phase 3 (sequential, after cmc_features)

## Task Commits

1. **Task 1: Create refresh_cmc_cs_norms.py** - `99423b03` (feat)
2. **Task 2: Wire CS norms into run_all_feature_refreshes.py** - `55d05ac1` (included in docs commit due to pre-commit hook auto-staging)

## Files Created/Modified
- `src/ta_lab2/scripts/features/refresh_cmc_cs_norms.py` - New CLI script and callable for CS z-score/rank computation via PARTITION BY window functions
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` - Added refresh_cs_norms_step() and Phase 3 CS norms call after cmc_features

## Decisions Made
- **Separate script approach**: CS norm columns must NOT be written by the existing feature pipeline's auto-discovery mechanism (`_get_table_columns()`). Those columns exist in the DDL but remain NULL after the feature pipeline, then get populated by this dedicated refresh. This prevents mixing row-level feature computation (per asset) with cross-sectional computation (across all assets at same ts/tf).
- **int return type**: `refresh_cs_norms()` returns `int` (sum of cursor.rowcount across all 3 UPDATEs) so orchestrator can use it directly as `rows_inserted` in RefreshResult without type conversion.
- **n_assets >= 5 threshold**: Timestamps where fewer than 5 assets have non-NULL source values get NULL CS norms. With 1-4 assets the cross-sectional distribution is meaningless for factor ranking.
- **NullPool for CLI**: Standalone script uses `create_engine(..., poolclass=NullPool)` to avoid lingering connections on one-shot runs.
- **ImportError guard in orchestrator**: The import of `refresh_cmc_cs_norms` is wrapped in `try/except ImportError` with `_CS_NORMS_AVAILABLE` flag so the orchestrator degrades gracefully if the module is missing.

## Deviations from Plan

None — plan executed exactly as written.

Note: Task 2 commit ended up in commit `55d05ac1` (labeled as `docs(56-05)`) due to the pre-commit hook auto-staging the file during a concurrent plan execution. The code changes are correctly in HEAD and verified working.

## Issues Encountered
- Pre-commit hook (`check-added-large-files`) auto-staged `run_all_feature_refreshes.py` into an adjacent docs commit (`55d05ac1`) because ruff-format rewrote the file during the hook run and git picked it up. The code changes are identical to what was planned — only the commit label is non-ideal. All verification checks pass.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- CS norm columns (ret_arith_cs_zscore, ret_arith_cs_rank, rsi_14_cs_zscore, rsi_14_cs_rank, vol_parkinson_20_cs_zscore, vol_parkinson_20_cs_rank) are populated for 1D TF
- `python -m ta_lab2.scripts.features.refresh_cmc_cs_norms --all-tfs` can populate all TFs if needed
- Daily feature refresh (`run_all_feature_refreshes`) now automatically refreshes CS norms as Phase 3
- Factor analytics reporting (Phase 56 remaining plans) can now read CS norm columns from cmc_features

---
*Phase: 56-factor-analytics-reporting*
*Completed: 2026-02-28*
