---
phase: 77-direct-to-u-remaining-families
plan: "03"
subsystem: database
tags: [postgresql, ema-returns, alignment_source, direct-to-u, migration, sqlalchemy]

# Dependency graph
requires:
  - phase: 77-02
    provides: ema_multi_tf_u as source (all 5 EMA variants in _u with alignment_source)
  - phase: 77-01
    provides: bar returns direct-to-_u pattern (ALIGNMENT_SOURCE constant, ON CONFLICT scope, del_state split)
provides:
  - All 3 EMA returns builders write directly to returns_ema_multi_tf_u with per-variant alignment_source
  - Source reads scoped by alignment_source to prevent cross-source LAG contamination
  - Row count parity confirmed: 48,830,818 total rows, all 5 alignment_sources MATCH
  - sync_returns_ema_multi_tf_u.py disabled as no-op with deprecation message
affects:
  - Phase 78 (cleanup: remove disabled sync scripts)
  - Phase 77-04+ (AMA returns if any)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - ALIGNMENT_SOURCE_US / ALIGNMENT_SOURCE_ISO dual-constant pattern for dual-scheme builders
    - _tables_for_scheme() returns 4-tuple (ema_table, ret_table, state_table, alignment_source)
    - _load_keys() scoped by alignment_source when source is _u table (avoids enumerating all variants' keys)
    - source WHERE clause: AND alignment_source = :alignment_source prevents cross-source LAG windows
    - del_state_params split from del_out_params (state table lacks alignment_source column)

key-files:
  created:
    - .planning/phases/77-direct-to-u-remaining-families/77-03-row-count-verification.txt
  modified:
    - src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf.py
    - src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf_cal.py
    - src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf_cal_anchor.py
    - src/ta_lab2/scripts/returns/sync_returns_ema_multi_tf_u.py

key-decisions:
  - "EMA returns builders read from ema_multi_tf_u (not siloed tables) - critical: source must be _u since siloed EMA tables are being retired"
  - "Source _load_keys() scoped by alignment_source: prevents enumerating keys from all 5 variants when querying _u source table"
  - "Source CTE scoped by alignment_source: prevents cross-source LAG window contamination (this is the key difference from bar returns which reads from price_bars, not from another _u table)"
  - "_tables_for_scheme() extended to return 4-tuple including alignment_source to propagate cleanly through the execution chain"
  - "Row count parity confirmed at 48,830,818 total rows; no backfill needed"
  - "sync_returns_ema_multi_tf_u.py disabled as no-op; Phase 78 will remove it"

patterns-established:
  - "dual-scheme _u migration: both schemes write to same _u table; alignment_source distinguishes them"
  - "ALIGNMENT_SOURCE_US / ALIGNMENT_SOURCE_ISO module-level constants per dual-scheme builder"
  - "source CTE always includes AND alignment_source = :alignment_source when source is a _u table"

# Metrics
duration: 8min
completed: 2026-03-20
---

# Phase 77 Plan 03: EMA Returns Direct-to-_u Migration Summary

**All 3 EMA returns builders redirected to returns_ema_multi_tf_u with alignment_source-scoped source reads; 48.8M rows at parity across all 5 variants; sync script disabled**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-20T18:22:44Z
- **Completed:** 2026-03-20T18:30:43Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- All 3 EMA returns builders (`multi_tf`, `cal`, `cal_anchor`) redirected to read from `ema_multi_tf_u` (not siloed EMA tables) and write to `returns_ema_multi_tf_u`
- Source reads scoped by `AND alignment_source = :alignment_source` in both `seed` and `src` CTEs to prevent cross-source LAG window contamination
- `_load_keys()` in all 3 builders now scopes DISTINCT key enumeration by `alignment_source` when reading from the `_u` source table
- Row count parity confirmed: all 5 alignment_sources MATCH at 48,830,818 total rows
- `sync_returns_ema_multi_tf_u.py` replaced with no-op deprecation stub

## Task Commits

Each task was committed atomically:

1. **Task 1: Redirect all 3 EMA returns builders to returns_ema_multi_tf_u** - `d4d7fe67` (feat)
2. **Task 2: Row count parity verification + disable sync script** - `8880ab5b` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf.py` - ALIGNMENT_SOURCE='multi_tf'; DEFAULT_EMA_TABLE/DEFAULT_OUT_TABLE->_u; source scoped by alignment_source; ON CONFLICT includes alignment_source
- `src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf_cal.py` - ALIGNMENT_SOURCE_US/ISO constants; both defaults->_u; dual-scheme alignment_source flow through _load_keys/_full_refresh/_run_one_key/_run_one_key_mp/main
- `src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf_cal_anchor.py` - same as cal; _tables_for_scheme() extended to return 4-tuple with alignment_source
- `src/ta_lab2/scripts/returns/sync_returns_ema_multi_tf_u.py` - replaced with no-op + deprecation print
- `.planning/phases/77-direct-to-u-remaining-families/77-03-row-count-verification.txt` - row count parity evidence

## Decisions Made

- **Source scoping critical difference from bar returns:** Bar returns reads from `price_bars_multi_tf` (which has no `alignment_source` column). EMA returns reads from `ema_multi_tf_u` which has all 5 variants mixed together. Without `AND alignment_source = :alignment_source` in the source CTE, the LAG windows would span rows from multiple variants, producing incorrect returns.
- **`_load_keys()` scoping:** When querying `ema_multi_tf_u` for distinct (id, tf, period, venue_id) keys, we must filter by `alignment_source` too — otherwise a `multi_tf` builder would enumerate keys from all 5 variants and attempt to process them all.
- **`_tables_for_scheme()` 4-tuple extension:** The `cal_anchor` script uses `_tables_for_scheme()` to get table names per scheme. Extended to return `alignment_source` as 4th element, making the alignment_source flow cleaner through the main loop.
- **State tables unchanged:** State tables (`returns_ema_multi_tf_state`, etc.) remain per-variant and have no `alignment_source` column. State DELETE uses separate params dict without `alignment_source`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The dual-scheme builders (cal, cal_anchor) required more changes than the single-scheme builder (multi_tf) due to the need to propagate `alignment_source` through additional function parameters, but the pattern was straightforward.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 3 (EMA returns) complete. `returns_ema_multi_tf_u` is the sole write target for all 5 EMA returns variants.
- Phase 78 (cleanup) can now remove `sync_returns_ema_multi_tf_u.py`, `sync_ema_multi_tf_u.py`, `sync_price_bars_multi_tf_u.py`, and `sync_returns_bars_multi_tf_u.py` — all are now no-ops.
- No blockers identified.

---
*Phase: 77-direct-to-u-remaining-families*
*Completed: 2026-03-20*
