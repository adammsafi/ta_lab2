---
phase: 77-direct-to-u-remaining-families
plan: "05"
subsystem: database
tags: [ama, returns_ama_multi_tf_u, alignment_source, direct-to-u, wave5]

# Dependency graph
requires:
  - phase: 77-04
    provides: AMA values direct-to-_u migration (ama_multi_tf_u with alignment_source)
  - phase: 74-02
    provides: alignment_source CHECK constraints on _u tables, 5 valid values
provides:
  - refresh_returns_ama.py writing all 5 AMA returns variants to returns_ama_multi_tf_u
  - TABLE_MAP restructured from 3-tuples to 4-tuples with alignment_source
  - Source reads scoped by alignment_source (prevents cross-source LAG contamination)
  - alignment_source in INSERT column list, ON CONFLICT, and DELETE scope
  - sync_returns_ama_multi_tf_u.py disabled as no-op
  - Row count parity confirmed: 113,125,842 rows, all 5 sources MATCH
affects:
  - 78 (cleanup phase removing sync scripts)
  - Phase 79 (any AMA returns-consuming downstream work)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TABLE_MAP 4-tuple pattern (src, dst, state_table, alignment_source) for _u migrations
    - WHERE clause always scoped by alignment_source when reading from shared _u source table
    - DELETE scope includes alignment_source to prevent cross-source deletion in _u table
    - SQL literal '{alignment_source}'::text in SELECT for stamping alignment_source on every row

key-files:
  created:
    - .planning/phases/77-direct-to-u-remaining-families/77-05-row-count-verification.txt
  modified:
    - src/ta_lab2/scripts/amas/refresh_returns_ama.py
    - src/ta_lab2/scripts/amas/sync_returns_ama_multi_tf_u.py

key-decisions:
  - "TABLE_MAP 4-tuple: (source_table, returns_table, state_table, alignment_source)"
  - "All 5 source entries read from ama_multi_tf_u scoped by alignment_source"
  - "All 5 output entries write to returns_ama_multi_tf_u"
  - "WHERE clause scoped by alignment_source prevents cross-source LAG contamination"
  - "AMA returns parity confirmed: all 5 sources MATCH (113,125,842 total rows)"
  - "sync_returns_ama_multi_tf_u.py disabled as no-op; Phase 78 will remove it"

patterns-established:
  - "TABLE_MAP 4-tuple: add alignment_source as 4th element in all _u migration scripts"
  - "Source scoping: WHERE alignment_source = '...' prevents mixing rows from different variants"
  - "DELETE+INSERT: both scoped by alignment_source for safe _u table upsert"

# Metrics
duration: 5min
completed: 2026-03-20
---

# Phase 77 Plan 05: AMA Returns Direct-to-_u Migration Summary

**refresh_returns_ama.py fully migrated to returns_ama_multi_tf_u: TABLE_MAP restructured to 4-tuples, all 5 variants read from ama_multi_tf_u scoped by alignment_source, 113.1M rows verified MATCH**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-20T18:42:04Z
- **Completed:** 2026-03-20T18:47:06Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Restructured TABLE_MAP from 3-tuples to 4-tuples (adding `alignment_source` as 4th element)
- Redirected all 5 source entries to read from `ama_multi_tf_u` (scoped by `alignment_source`)
- Redirected all 5 output entries to write to `returns_ama_multi_tf_u`
- `alignment_source` added to INSERT column list, SQL literal in SELECT, ON CONFLICT, and DELETE scope
- Updated all unpacking sites: `main()`, `_process_source()`, `_worker()`, `_resolve_ids()`, `_resolve_tfs()`
- Row count parity confirmed: all 5 alignment_sources show exact MATCH (113,125,842 total rows)
- Disabled `sync_returns_ama_multi_tf_u.py` as no-op with deprecation message
- Phase 77 Wave 5 complete: all 5 families now write directly to their `_u` tables

## Task Commits

Each task was committed atomically:

1. **Task 1: Redirect refresh_returns_ama.py to write to returns_ama_multi_tf_u and read from ama_multi_tf_u** - `b970de92` (feat)
2. **Task 2: Verify AMA returns row count parity and disable sync script** - `3017949a` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `src/ta_lab2/scripts/amas/refresh_returns_ama.py` - TABLE_MAP restructured to 4-tuples; all 5 variants read from ama_multi_tf_u scoped by alignment_source; writes to returns_ama_multi_tf_u with alignment_source in INSERT/CONFLICT/DELETE
- `src/ta_lab2/scripts/amas/sync_returns_ama_multi_tf_u.py` - Replaced with no-op + DEPRECATED message
- `.planning/phases/77-direct-to-u-remaining-families/77-05-row-count-verification.txt` - Parity verification results (all 5 MATCH)

## Decisions Made
- `TABLE_MAP` restructured from `dict[str, tuple[str, str, str]]` to `dict[str, tuple[str, str, str, str]]`. The 4th element is `alignment_source`, making the structure self-describing and eliminating the need to derive alignment_source from the key name.
- All 5 `TABLE_MAP` entries read from the same `ama_multi_tf_u` table but are scoped by `alignment_source` in the WHERE clause. This is critical: the LAG window functions would produce incorrect results if rows from different `alignment_source` variants were mixed in the same partition.
- `DELETE` scope includes `AND alignment_source = '{alignment_source}'` to prevent one variant's DELETE from wiping other variants' rows in the shared `_u` table.
- `alignment_source` is stamped using `'{alignment_source}'::text` as a SQL literal in the final SELECT (format-time substitution), consistent with the EMA/bar returns pattern established in Phases 77-01 to 77-03.
- State tables remain per-variant (each `TABLE_MAP` entry keeps its own state table). This allows each `alignment_source` to track its own watermark independently.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The ruff formatter reformatted `refresh_returns_ama.py` (line length/style) on first commit attempt, requiring a re-stage and second commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Wave 5 (AMA returns) complete. Phase 77 is now fully complete — all 5 remaining families migrated to direct-to-_u writes.
- Phase 78 cleanup can now remove all 6 disabled sync scripts (price_bars, bar returns, EMA, EMA returns, AMA, AMA returns).
- No blockers.

---
*Phase: 77-direct-to-u-remaining-families*
*Completed: 2026-03-20*
