---
phase: 77-direct-to-u-remaining-families
plan: "01"
subsystem: database
tags: [postgres, sqlalchemy, bar-returns, alignment_source, unified-table, migration]

# Dependency graph
requires:
  - phase: 76-direct-to-u-price-bars-pilot
    provides: alignment_source pattern, _u migration approach, conflict_cols tuple, sync-disabled pattern

provides:
  - All 5 bar returns builders writing directly to returns_bars_multi_tf_u
  - ALIGNMENT_SOURCE constant stamped on every row per builder
  - ON CONFLICT includes alignment_source as 5th conflict column
  - full-refresh DELETE scoped by alignment_source
  - sync_returns_bars_multi_tf_u.py disabled as no-op
  - Row count parity confirmed: 12,019,640 rows, all 5 sources MATCH

affects:
  - 77-02 (EMA returns migration)
  - 77-03 (AMA returns migration)
  - 78-drop-siloed-tables
  - 79-cleanup

# Tech tracking
tech-stack:
  added: []
  patterns:
    - ALIGNMENT_SOURCE module-level constant per builder
    - CAST(:alignment_source AS text) in INSERT...SELECT CTE
    - ON CONFLICT (id, timestamp, tf, venue_id, alignment_source) pattern
    - full-refresh DELETE scoped by alignment_source to protect _u cross-source rows
    - DeprecationWarning + print no-op pattern for disabled sync scripts

key-files:
  created:
    - .planning/phases/77-direct-to-u-remaining-families/77-01-row-count-verification.txt
  modified:
    - src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf.py
    - src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_us.py
    - src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_iso.py
    - src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_us.py
    - src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_iso.py
    - src/ta_lab2/scripts/returns/sync_returns_bars_multi_tf_u.py

key-decisions:
  - "ALIGNMENT_SOURCE constant (not argument) per builder script mirrors Phase 76 price bars pattern"
  - "full-refresh DELETE scoped by alignment_source to avoid wiping other variants' _u rows"
  - "del_state uses separate params dict (no alignment_source) since state table has no alignment_source column"
  - "Row count parity confirmed from existing _u data; no need to re-run builders"
  - "sync script replaced with DeprecationWarning no-op; physical deletion deferred to Phase 78"

patterns-established:
  - "Bar returns _u migration pattern: identical to price bars pilot (Phase 76)"
  - "del_state_params split from del_out params since state table lacks alignment_source column"

# Metrics
duration: 4min
completed: 2026-03-20
---

# Phase 77 Plan 01: Bar Returns Direct-to-_u Migration Summary

**All 5 bar returns builders redirected to write directly to returns_bars_multi_tf_u with alignment_source stamped per row; row count parity confirmed at 12,019,640 rows across all alignment_sources**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-20T17:46:28Z
- **Completed:** 2026-03-20T17:50:53Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Applied 6 consistent changes to all 5 bar returns builder scripts: ALIGNMENT_SOURCE constant, DEFAULT_OUT_TABLE redirected to _u, alignment_source in _INSERT_COLS, CAST in SELECT, ON CONFLICT updated, full-refresh DELETE scoped
- Confirmed row count parity: all 5 alignment_sources show exact MATCH (12,019,640 total rows)
- Disabled sync_returns_bars_multi_tf_u.py as a no-op with DeprecationWarning

## Task Commits

Each task was committed atomically:

1. **Task 1: Redirect all 5 bar returns builders to returns_bars_multi_tf_u** - `9209004a` (feat)
2. **Task 2: Disable sync script and document row count parity** - `4cd8fa0d` (feat)

**Plan metadata:** see final docs commit

## Files Created/Modified
- `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf.py` - ALIGNMENT_SOURCE="multi_tf", writes to _u
- `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_us.py` - ALIGNMENT_SOURCE="multi_tf_cal_us", writes to _u
- `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_iso.py` - ALIGNMENT_SOURCE="multi_tf_cal_iso", writes to _u
- `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_us.py` - ALIGNMENT_SOURCE="multi_tf_cal_anchor_us", writes to _u
- `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_iso.py` - ALIGNMENT_SOURCE="multi_tf_cal_anchor_iso", writes to _u
- `src/ta_lab2/scripts/returns/sync_returns_bars_multi_tf_u.py` - Replaced with no-op deprecation notice
- `.planning/phases/77-direct-to-u-remaining-families/77-01-row-count-verification.txt` - Row count parity evidence

## Decisions Made
- **del_state_params split:** The state tables have no `alignment_source` column, so the DELETE from state tables uses a separate params dict. Only the output table DELETE is scoped by alignment_source.
- **Row count source:** The _u table already contained all rows from the previous sync script. Row counts were confirmed via SELECT COUNT(*) per alignment_source — no need to re-run builders.
- **Sync script replacement:** Replaced entire sync script with DeprecationWarning no-op pattern, consistent with Phase 76 price bars sync disabled pattern.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None. All 5 scripts followed the identical pattern, making systematic application straightforward.

## Next Phase Readiness
- Bar returns family migration complete; all builders writing directly to _u
- Same pattern ready to apply to EMA returns (Phase 77-02) and AMA returns (Phase 77-03)
- sync_returns_bars_multi_tf_u.py disabled; Phase 78 will remove it

---
*Phase: 77-direct-to-u-remaining-families*
*Completed: 2026-03-20*
