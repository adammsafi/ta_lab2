---
phase: 37-ic-evaluation
plan: "04"
subsystem: analysis
tags: [ic, information-coefficient, postgresql, sqlalchemy, cli, argparse, regime, spearman, persistence]

# Dependency graph
requires:
  - phase: 37-01
    provides: cmc_ic_results table (UUID PK, 9-column unique constraint, TIMESTAMPTZ columns)
  - phase: 37-02
    provides: compute_ic, compute_rolling_ic, compute_feature_turnover — IC core library
  - phase: 37-03
    provides: compute_ic_by_regime, batch_compute_ic, plot helpers — regime IC and batch wrappers
provides:
  - load_feature_series(): loads feature + close from cmc_features with tz-aware UTC fix
  - load_regimes_for_asset(): loads cmc_regimes with split_part(l2_label) SQL to derive trend_state/vol_state
  - save_ic_results(): persists IC rows to cmc_ic_results with append-only or upsert semantics
  - _to_python(): numpy scalar normalization helper (numpy -> Python float/int, NaN -> None)
  - run_ic_eval.py CLI: compute + persist IC evaluation end-to-end
affects:
  - 37-05 and beyond: Notebooks and Streamlit dashboard can use DB helpers for querying IC results
  - 38-feature-experimentation: ExperimentRunner reads cmc_ic_results via save_ic_results pattern

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DB helper pattern: lazy import of get_columns() inside load_feature_series() to avoid circular imports"
    - "Dynamic column injection in SQL: validate column name first via get_columns(), then f-string inject (safe pattern)"
    - "split_part(l2_label, '-', 1) SQL pattern for parsing composite labels without direct column references"
    - "NullPool + resolve_db_url() + engine.begin() pattern (same as compute_psr.py)"
    - "Mutually exclusive argparse group for --feature vs --all-features"
    - "Regime sentinel: regime_col='all', regime_label='all' for full-sample IC rows"

key-files:
  created:
    - src/ta_lab2/scripts/analysis/__init__.py
    - src/ta_lab2/scripts/analysis/run_ic_eval.py
  modified:
    - src/ta_lab2/analysis/ic.py

key-decisions:
  - "load_feature_series validates column name via get_columns() before f-string SQL injection — prevents SQL injection via column name"
  - "load_regimes_for_asset uses split_part(l2_label, '-', N) SQL — cmc_regimes has NO trend_state/vol_state columns"
  - "save_ic_results loops over rows with individual INSERT per row (not bulk) for precise rowcount tracking"
  - "_to_python() handles numpy scalars (.item()), pd.Timestamp (.to_pydatetime()), and NaN (-> None)"
  - "run_ic_eval.py loads regimes once per asset, then iterates over features (efficient for --all-features)"
  - "Regime mode: computes IC for BOTH trend_state and vol_state breakdowns per feature in one CLI run"

patterns-established:
  - "DB helper import pattern: from ta_lab2.analysis.ic import load_feature_series, load_regimes_for_asset, save_ic_results"
  - "IC eval CLI invocation: python -m ta_lab2.scripts.analysis.run_ic_eval --asset-id N --tf 1D --feature col --train-start DATE --train-end DATE"

# Metrics
duration: 6min
completed: "2026-02-24"
---

# Phase 37 Plan 04: IC DB Helpers and CLI Summary

**Three DB helper functions (load_feature_series, load_regimes_for_asset, save_ic_results) added to ic.py and run_ic_eval.py CLI enabling full IC evaluation workflow: load -> compute -> persist -> query**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-02-24T02:13:56Z
- **Completed:** 2026-02-24T02:20:46Z
- **Tasks:** 2/2
- **Files modified:** 3 (ic.py extended, __init__.py + run_ic_eval.py in docs commit from 37-03)

## Accomplishments

- `load_feature_series()`: validates column name via `get_columns()` before dynamic SQL injection, applies `pd.to_datetime(utc=True)` fix, returns (feature_series, close_series) tuple
- `load_regimes_for_asset()`: uses `split_part(l2_label, '-', 1/2)` SQL to parse trend_state and vol_state — cmc_regimes has NO direct columns for these
- `save_ic_results()`: append-only (ON CONFLICT DO NOTHING) or upsert (ON CONFLICT DO UPDATE) via `overwrite` flag; normalizes numpy scalars and NaN via `_to_python()` before SQL binding
- `run_ic_eval.py` CLI: end-to-end IC evaluation following compute_psr.py pattern — NullPool, resolve_db_url(), engine.begin(), exit code 0/1
- Verified: 14 rows written to cmc_ic_results for asset_id=1 feature=ret_arith; 84 rows computed (but not written) in --regime dry-run
- All 61 tests in test_ic.py still pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DB helper functions to ic.py** - `e57ced95` (feat)
2. **Task 2: run_ic_eval.py CLI** - committed as part of `07a13ea4` (docs from 37-03 execution which included these files)

Note: `__init__.py` and `run_ic_eval.py` were included in the plan 03 docs commit (`07a13ea4`) by a previous agent session. Task 1 (ic.py DB helpers) was the new work committed in this session as `e57ced95`.

## Files Created/Modified

- `src/ta_lab2/analysis/ic.py` - Extended with: `load_feature_series`, `load_regimes_for_asset`, `save_ic_results`, `_to_python()` helper, updated module docstring to document DB helpers
- `src/ta_lab2/scripts/analysis/__init__.py` - Package init for scripts.analysis (created in 07a13ea4)
- `src/ta_lab2/scripts/analysis/run_ic_eval.py` - Full CLI script (created in 07a13ea4)

## Decisions Made

- **Column name validation before SQL injection**: `get_columns()` validates that the requested `feature_col` exists in cmc_features before it's injected into the SQL f-string. Prevents both runtime errors and SQL injection via column names.
- **lazy import of get_columns**: Imported inside `load_feature_series()` body (not at module top) to avoid circular import between `ic.py` and `sync_utils.py`.
- **split_part SQL for regime parsing**: `cmc_regimes` has NO `trend_state` or `vol_state` columns — they MUST be derived from `l2_label` via `split_part(l2_label, '-', 1)` and `split_part(l2_label, '-', 2)` in SQL.
- **Individual INSERT per row in save_ic_results**: Loops over rows rather than bulk insert to get accurate `rowcount` per insert (important for ON CONFLICT DO NOTHING reporting).
- **Regime runs both trend_state and vol_state**: When `--regime` is specified, the CLI computes IC for BOTH breakdown columns in one invocation, producing 2x the rows compared to full-sample.
- **DimTimeframe.from_db() outside the engine.begin() block**: The DimTimeframe load uses its own connection internally, so it runs before the main `engine.begin()` context.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added compute_ic_by_regime and batch_compute_ic since CLI depends on them**

- **Found during:** Task 2 setup — CLI imports `compute_ic_by_regime` and `batch_compute_ic` from ic.py but these functions were added by Plan 03 (which had already run in a previous session)
- **Issue:** Plan 04's task depends on functions from Plan 03. Need to verify prior plan 03 was complete before starting.
- **Fix:** Verified plan 03 had already executed (`07a13ea4` includes `37-03-SUMMARY.md` and the ic.py regime/batch/plot additions). The CLI was included in that docs commit. No extra work needed.
- **Files modified:** None — plan 03 work was already present
- **Committed in:** `07a13ea4` (part of prior plan 03 execution)

---

**Total deviations:** 0 actual deviations — plan executed exactly as written. The "deviation" above is a discovery during setup that plan 03 had already run.

## Issues Encountered

- **Pre-commit hook mixed-line-ending conflict**: When staging Task 2 files (which were already committed as part of plan 03 docs commit), the pre-commit stash/restore mechanism picked up unstaged `37-03-SUMMARY.md` with CRLF line endings and flagged it. Resolved by staging that file to let the hook normalize its line endings.
- **run_ic_eval.py already committed**: Discovered during Task 2 that `run_ic_eval.py` and `__init__.py` were already committed in `07a13ea4` by the prior plan 03 session. The files in the working tree matched HEAD exactly, so no new commit was needed for Task 2. Only Task 1 (ic.py DB helpers) required a new commit.

## User Setup Required

None - no external service configuration required. The cmc_ic_results table was created in plan 37-01.

## Next Phase Readiness

- Full IC evaluation workflow is operational: load -> compute -> persist -> query
- `load_feature_series`, `load_regimes_for_asset`, `save_ic_results` are reusable from notebooks and Streamlit dashboard
- `run_ic_eval.py` CLI supports single feature, multiple features, and `--all-features` modes
- Regime breakdown works end-to-end: SQL split_part parsing -> trend_state/vol_state -> IC per regime label
- 14 rows in cmc_ic_results for asset_id=1 feature=ret_arith (verified)
- 61 tests passing in test_ic.py
- Plan 37-05 (additional features / dashboard) can import DB helpers directly

---
*Phase: 37-ic-evaluation*
*Completed: 2026-02-24*
