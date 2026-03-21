---
phase: 76-direct-to-u-price-bars-pilot
plan: "02"
subsystem: database
tags: [postgresql, price-bars, alignment_source, upsert, conflict_cols, venue_id, migration]

# Dependency graph
requires:
  - phase: 76-01
    provides: alignment_source in valid_cols for upsert_bars(); delete_bars_for_id_tf() alignment_source param; state tables bootstrapped

provides:
  - All 5 multi-TF price bar builders write directly to price_bars_multi_tf_u
  - alignment_source stamped on every row in every code path (full rebuild, incremental, from_1d)
  - All upsert_bars() calls in all 5 builders use explicit conflict_cols with alignment_source
  - Deletes scoped by alignment_source (no cross-alignment clobbering)
  - _load_last_snapshot_info() filters by alignment_source in all 3 CTEs across all 5 builders

affects:
  - 76-03 (bar builder wiring and run_all_bar_builders)
  - 77 (returns tables migration - same pattern)
  - 78 (drop siloed price bar tables - enabled by this plan)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ALIGNMENT_SOURCE class constant on each builder; stamped onto bars DataFrame before upsert"
    - "conflict_cols=(id, tf, bar_seq, venue_id, timestamp, alignment_source) for all _u table upserts"
    - "from_1d DELETE scoped: WHERE id=:id AND alignment_source=:alignment_source (not bare id delete)"
    - "venue_id = bars.get('venue_id', 1) unconditional assignment pattern before every upsert"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf.py
    - src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_us.py
    - src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_iso.py
    - src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_anchor_us.py
    - src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_anchor_iso.py

key-decisions:
  - "venue_id defaulted to 1 (CMC_AGG) via bars.get('venue_id', 1) - unconditional, never conditional"
  - "from_1d DELETE uses AND alignment_source filter to avoid wiping other variants' data from _u"
  - "AST-based verification used to confirm all upsert_bars() calls have conflict_cols"
  - "MultiTFBarBuilder._upsert_bars() wrapper method carries conflict_cols; cal builders use direct upsert_bars() calls"

patterns-established:
  - "ALIGNMENT_SOURCE class constant + bars stamp pattern: add constant, set bars['alignment_source'] = self.ALIGNMENT_SOURCE before upsert"
  - "Full 6-change migration checklist per builder: OUTPUT_TABLE, ALIGNMENT_SOURCE, bars stamp, conflict_cols, delete scope, venue_id, _load_last_snapshot_info SQL"

# Metrics
duration: 9min
completed: 2026-03-20
---

# Phase 76 Plan 02: Direct-to-U Price Bars Pilot Summary

**All 5 multi-TF price bar builders redirected to write to price_bars_multi_tf_u with alignment_source stamped on every row, scoped deletes, and PK-correct conflict_cols**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-03-20T13:23:45Z
- **Completed:** 2026-03-20T13:33:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Redirected all 5 builders from siloed tables to `public.price_bars_multi_tf_u` via `OUTPUT_TABLE` class constant change
- Added `ALIGNMENT_SOURCE` class constant to each builder with its specific value (`multi_tf`, `multi_tf_cal_us`, `multi_tf_cal_iso`, `multi_tf_cal_anchor_us`, `multi_tf_cal_anchor_iso`)
- Updated every `upsert_bars()` call across all 5 builders to use explicit `conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp", "alignment_source")` -- verified via AST analysis (zero calls without conflict_cols)
- Added `alignment_source` filter to `_load_last_snapshot_info()` in all 5 builders (3 CTEs each)
- Scoped `delete_bars_for_id_tf()` calls with `alignment_source=self.ALIGNMENT_SOURCE` in all builders
- Fixed from_1d DELETE to scope by `alignment_source` (was bare `WHERE id = :id`, now `WHERE id = :id AND alignment_source = :alignment_source`)
- Unconditionally set `venue_id` on all output DataFrames before upsert

## Task Commits

Each task was committed atomically:

1. **Task 1: Redirect refresh_price_bars_multi_tf.py to write to _u table** - `d800dd5c` (feat)
2. **Task 2: Redirect all 4 calendar builders to write to _u table** - `53e93540` (feat)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf.py` - OUTPUT_TABLE, ALIGNMENT_SOURCE='multi_tf', bars stamp, conflict_cols, delete scope, _load_last_snapshot_info + _load_last_bar_snapshot_row filters
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_us.py` - Same 6-change pattern, ALIGNMENT_SOURCE='multi_tf_cal_us', 4 upsert_bars paths updated
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_iso.py` - Same 6-change pattern, ALIGNMENT_SOURCE='multi_tf_cal_iso', 4 upsert_bars paths updated
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_anchor_us.py` - Same 6-change pattern, ALIGNMENT_SOURCE='multi_tf_cal_anchor_us', 2 upsert_bars paths updated
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_anchor_iso.py` - Same 6-change pattern, ALIGNMENT_SOURCE='multi_tf_cal_anchor_iso', 2 upsert_bars paths updated

## Decisions Made
- **`venue_id = bars.get("venue_id", 1)` unconditional**: Never wrapped in a conditional. The _u table PK requires venue_id to be present. Default 1 (CMC_AGG) since these builders only process CMC_AGG data today.
- **`from_1d` DELETE scoped by alignment_source**: Changed from `WHERE id = :id` to `WHERE id = :id AND alignment_source = :alignment_source`. Without this, the from_1d path would wipe all alignment variants for the given ID from the _u table, not just its own rows.
- **AST-based verification**: Used Python `ast` module to confirm zero upsert_bars() calls lack conflict_cols -- grep was misleading on multi-line calls.
- **`MultiTFBarBuilder._upsert_bars()` wrapper**: This builder routes through a wrapper method so conflict_cols only needed in one place; calendar builders call upsert_bars() directly so each call site was updated.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-commit ruff-format reformatted files on first commit attempt (long lines in conflict_cols tuples). Re-staged and committed a second time. No code logic changes required.

## Next Phase Readiness
- All 5 builders now write directly to `price_bars_multi_tf_u` with correct alignment_source and PK-matching conflict_cols
- State tables (bootstrapped in plan 01) will receive incremental watermark updates from the first direct-write run
- Plan 03 (wiring `run_all_bar_builders.py` and `sync_price_bars_multi_tf_u.py` cleanup) can proceed
- Phase 78 (drop siloed tables) is unblocked once plan 03 wiring is verified

---
*Phase: 76-direct-to-u-price-bars-pilot*
*Completed: 2026-03-20*
