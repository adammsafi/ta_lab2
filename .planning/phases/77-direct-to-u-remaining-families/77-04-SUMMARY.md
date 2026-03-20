---
phase: 77-direct-to-u-remaining-families
plan: "04"
subsystem: database
tags: [ama, ama_multi_tf_u, alignment_source, direct-to-u, wave4]

# Dependency graph
requires:
  - phase: 77-03
    provides: EMA returns direct-to-_u migration pattern (alignment_source in PK + DELETE scope)
  - phase: 74-02
    provides: alignment_source CHECK constraints on _u tables, 5 valid values
provides:
  - AMAFeatureConfig.alignment_source field (Optional[str]) for _u table writes
  - BaseAMAFeature.write_to_db() DELETE scoped by alignment_source
  - BaseAMAFeature._get_pk_columns() extended with alignment_source for _u tables
  - All 3 AMA builders writing to ama_multi_tf_u with correct alignment_source
  - sync_ama_multi_tf_u.py disabled as no-op
  - Row count parity confirmed: 170,447,220 rows, all 5 sources MATCH
affects:
  - 77-05 (AMA returns wave, if applicable)
  - 78 (cleanup phase removing sync scripts)
  - Phase 79 (any AMA-consuming downstream work)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - alignment_source Optional field in feature config gates PK extension and DELETE scope
    - get_alignment_source() hook on BaseAMARefresher (default None for backward compat)
    - SCHEME_MAP now includes alignment_source key alongside output_table
    - AMAWorkerTask.alignment_source propagated to AMAFeatureConfig in worker

key-files:
  created:
    - .planning/phases/77-direct-to-u-remaining-families/77-04-row-count-verification.txt
  modified:
    - src/ta_lab2/features/ama/base_ama_feature.py
    - src/ta_lab2/scripts/amas/base_ama_refresher.py
    - src/ta_lab2/scripts/amas/refresh_ama_multi_tf.py
    - src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_from_bars.py
    - src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_anchor_from_bars.py
    - src/ta_lab2/scripts/amas/sync_ama_multi_tf_u.py

key-decisions:
  - "AMAFeatureConfig.alignment_source (Optional[str]=None) gates PK extension and DELETE scope"
  - "alignment_source stamped on df_write after column filtering in write_to_db()"
  - "get_alignment_source() hook on BaseAMARefresher defaults None for backward compat"
  - "SCHEME_MAP alignment_source key replaces per-scheme output_table CLI args"
  - "AMA parity confirmed: all 5 sources MATCH (170,447,220 total rows)"
  - "sync_ama_multi_tf_u.py disabled as no-op; Phase 78 will remove it"

patterns-established:
  - "alignment_source in AMAFeatureConfig: Optional field defaults None, set for _u writes"
  - "DELETE scope: if alignment_source -> AND alignment_source = :alignment_source"
  - "PK: if alignment_source -> append 'alignment_source' to list"
  - "Stamp: df_write['alignment_source'] = self.config.alignment_source after filtering"

# Metrics
duration: 10min
completed: 2026-03-20
---

# Phase 77 Plan 04: AMA Values Direct-to-_u Migration Summary

**AMAFeatureConfig gains alignment_source; all 3 AMA builders redirect to ama_multi_tf_u with scoped DELETE preventing cross-source data corruption; 170.4M rows verified MATCH**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-03-20T18:33:20Z
- **Completed:** 2026-03-20T18:43:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Added `alignment_source` to `AMAFeatureConfig` and wired it through `write_to_db()` (DELETE scope + DataFrame stamp + PK extension)
- Added `alignment_source` to `AMAWorkerTask` and `get_alignment_source()` hook to `BaseAMARefresher`
- Redirected all 3 AMA builders to `ama_multi_tf_u` with correct alignment_source values
- Row count parity confirmed: all 5 alignment_sources show exact MATCH (170,447,220 total rows)
- Disabled `sync_ama_multi_tf_u.py` as no-op with deprecation message

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix BaseAMAFeature for alignment_source support and redirect all 3 AMA builders to _u** - `d1a5ddcb` (feat)
2. **Task 2: Verify AMA row count parity and disable sync script** - `4f630799` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `src/ta_lab2/features/ama/base_ama_feature.py` - Added alignment_source to AMAFeatureConfig; _get_pk_columns() appends it; write_to_db() scopes DELETE + stamps column
- `src/ta_lab2/scripts/amas/base_ama_refresher.py` - alignment_source field on AMAWorkerTask; get_alignment_source() hook; passes to AMAFeatureConfig
- `src/ta_lab2/scripts/amas/refresh_ama_multi_tf.py` - Output -> ama_multi_tf_u, alignment_source='multi_tf'
- `src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_from_bars.py` - SCHEME_MAP output_table -> ama_multi_tf_u, alignment_source per scheme
- `src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_anchor_from_bars.py` - SCHEME_MAP output_table -> ama_multi_tf_u, alignment_source per scheme
- `src/ta_lab2/scripts/amas/sync_ama_multi_tf_u.py` - Replaced with no-op + DEPRECATED message
- `.planning/phases/77-direct-to-u-remaining-families/77-04-row-count-verification.txt` - Parity verification results

## Decisions Made
- `AMAFeatureConfig.alignment_source` is `Optional[str] = None`. `None` means siloed table (no alignment_source column). Set value means _u table write with scoped DELETE.
- DELETE scope is critical: without `AND alignment_source = :alignment_source`, one builder's DELETE would wipe rows from other alignment_sources in the shared _u table.
- `alignment_source` is stamped on `df_write` AFTER column filtering (not before). This is intentional: the source DataFrame never has this column; we add it post-filter so `to_sql()` includes it.
- `get_alignment_source()` defaults to `None` on `BaseAMARefresher` for backward compatibility with any subclasses not yet migrated.
- AMA SCHEME_MAP now stores `alignment_source` key instead of using per-scheme `--out-us`/`--out-iso` CLI args for the output table.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The ruff formatter reformatted `sync_ama_multi_tf_u.py` (trailing whitespace/blank line style) on first commit attempt, requiring a re-stage and second commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Wave 4 (AMA values) complete. All 3 AMA builders write directly to `ama_multi_tf_u`.
- Wave 5 (AMA returns) should follow the same pattern if needed. Check `returns_ama_multi_tf_u` status.
- Phase 78 cleanup can now remove all disabled sync scripts.
- No blockers.

---
*Phase: 77-direct-to-u-remaining-families*
*Completed: 2026-03-20*
