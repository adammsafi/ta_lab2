---
phase: 35-ama-engine
plan: 05
subsystem: database
tags: [ama, returns, kama, dema, tema, hma, sqlalchemy, pandas, incremental-refresh]

# Dependency graph
requires:
  - phase: 35-01
    provides: DDL for cmc_returns_ama_multi_tf (12 return columns, no _ema_bar family)
  - phase: 35-02
    provides: AMAParamSet, compute_params_hash, indicator+params_hash PK design
  - phase: 35-03
    provides: AMAStateManager pattern for (id, tf, indicator, params_hash) state tracking
provides:
  - AMAReturnsFeature class computing 12 return columns + 2 gap_days columns from AMA values
  - refresh_cmc_returns_ama.py script processing all 5 AMA table variants
affects:
  - Plan 35-06 and beyond (z-score computation via refresh_returns_zscore.py uses these tables)
  - Plan 35-07 (sync script may consume returns tables)
  - Phase 37 (IC evaluation reads from cmc_returns_ama_multi_tf for feature scoring)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Returns grouped by (id, tf, indicator, params_hash) for correct LAG: prevents diff() crossing param-set boundaries"
    - "Scoped DELETE + INSERT: write_returns deletes existing (id, tf) slice before inserting — matches MEMORY.md Feature write pattern"
    - "Roll columns on ALL rows, canonical columns NULL for roll=TRUE: same partition logic as EMA returns tables"
    - "ON CONFLICT DO NOTHING safety net: _pg_insert_on_conflict_nothing used as to_sql method override"
    - "Table-existence check before processing: _table_exists() skips sources that don't yet exist"

key-files:
  created:
    - src/ta_lab2/features/ama/ama_returns.py
    - src/ta_lab2/scripts/amas/refresh_cmc_returns_ama.py
  modified: []

key-decisions:
  - "AMAReturnsFeature is standalone (not a subclass of BaseAMAFeature) — different responsibility: reads values, computes returns vs. BaseAMAFeature reads bars, computes values"
  - "State table schema matches AMAStateManager pattern: (id, tf, indicator, params_hash) PK with last_ts watermark"
  - "No _ema_bar column family in AMA returns — DDL confirmed only 12 return columns total"
  - "Refresh script skips sources that don't exist or are empty — supports incremental rollout where only multi_tf is populated initially"
  - "NullPool engine in refresh script — sequential processing, no connection pooling needed"

patterns-established:
  - "Windows tz pitfall: pd.to_datetime(utc=True) used when loading ts from DB; .tolist() or .to_pydatetime() for tz-aware conversions"
  - "canon_mask = gdf['roll'] == False (noqa: E712) — consistent with refresh_returns_zscore.py pattern"
  - "c_delta1.values used when writing canonical column results back to gdf.loc[canon_idx] — avoids index alignment issues"

# Metrics
duration: 3min
completed: 2026-02-23
---

# Phase 35 Plan 05: AMA Returns Computation Layer Summary

**AMAReturnsFeature computes 12 return columns (6 roll + 6 canonical) from AMA values grouped by (indicator, params_hash), with refresh_cmc_returns_ama.py mapping all 5 AMA table variants to their returns tables**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-23T22:13:59Z
- **Completed:** 2026-02-23T22:17:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- AMAReturnsFeature: reads AMA values, groups by (id, tf, indicator, params_hash) for correct LAG, computes 6 roll columns on all rows + 6 canonical columns on roll=FALSE rows only
- refresh_cmc_returns_ama.py: TABLE_MAP covers all 5 AMA table variants (multi_tf, cal_us, cal_iso, cal_anchor_us, cal_anchor_iso); graceful skip when source table missing/empty
- Verified 12 return columns match DDL exactly (delta1_ama, delta2_ama, ret_arith_ama, delta_ret_arith_ama, ret_log_ama, delta_ret_log_ama + _roll variants); no _ema_bar columns

## Task Commits

Each task was committed atomically:

1. **Task 1: Create AMAReturnsFeature class** - `8dce8fb1` (feat)
2. **Task 2: Create refresh_cmc_returns_ama.py script** - `036784a9` (feat)

**Plan metadata:** (created below as docs commit)

## Files Created/Modified

- `src/ta_lab2/features/ama/ama_returns.py` - AMAReturnsFeature class: compute_returns(), _compute_group_returns(), _write_returns(), _update_state(), refresh()
- `src/ta_lab2/scripts/amas/refresh_cmc_returns_ama.py` - Refresh script with TABLE_MAP for all 5 AMA variants, --ids/--tf/--all-tfs/--source/--dry-run CLI

## Decisions Made

- AMAReturnsFeature is standalone (not a subclass of BaseAMAFeature). The responsibilities are different: BaseAMAFeature reads bars and computes indicator values; AMAReturnsFeature reads indicator values and computes return metrics. Sharing code would require awkward multi-level inheritance.
- State table is created inline by `_ensure_state_table()` rather than requiring a pre-existing DDL migration. The state schema mirrors AMAStateManager but with `last_ts` column name (matching the returns DDL) instead of `last_canonical_ts`.
- `c_delta1.values` (not `.array`) used when assigning canonical results back to the parent DataFrame via `.loc[canon_idx]`. This avoids pandas index alignment issues where the canonical subset index doesn't match the parent index.
- Refresh script uses `NullPool` engine — sequential ID/TF processing does not benefit from connection pooling, and NullPool prevents connection leaks when processing large numbers of assets.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Ruff lint fixed unused import and line-length violations in both files**

- **Found during:** Pre-commit hook on first commit attempt (both tasks)
- **Issue:** `import os` was unused in refresh script; line length exceeded 88 chars in several places; CRLF line endings on Windows
- **Fix:** ruff auto-fixed the violations (removed unused import, reformatted long lines); mixed-line-ending hook normalized to LF
- **Files modified:** src/ta_lab2/features/ama/ama_returns.py, src/ta_lab2/scripts/amas/refresh_cmc_returns_ama.py
- **Verification:** Pre-commit hooks passed on second attempt
- **Committed in:** 8dce8fb1 and 036784a9 (re-staged after auto-fix)

---

**Total deviations:** 1 auto-fixed (1 lint/formatting)
**Impact on plan:** Minor cleanup, no logic change.

## Issues Encountered

None — both tasks implemented cleanly on first pass (after ruff auto-fix).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- AMAReturnsFeature and refresh_cmc_returns_ama.py are ready for use after Plan 35-04 (AMA values) is populated
- Pipeline sequence: refresh_cmc_ama_multi_tf.py (Plan 04) → refresh_cmc_returns_ama.py (this plan) → refresh_returns_zscore.py (Plan 07 will extend for AMA tables)
- --dry-run confirmed: when AMA tables don't exist, script gracefully skips all sources with "table_missing" reason
- Z-score computation (12 columns: ret_arith_ama_zscore_30/90/365, ret_log_ama_zscore_30/90/365, roll variants) deferred to later plan — these columns are already in the DDL as NULL placeholders

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
