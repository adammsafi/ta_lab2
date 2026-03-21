---
phase: 78-table-drops-script-cleanup
plan: 06
subsystem: ema
tags: [ema, price_bars, alignment_source, unified_table, feature_classes, state_manager]

# Dependency graph
requires:
  - phase: 76-bar-builder-consolidation
    provides: price_bars_multi_tf_u with 5 alignment_sources (multi_tf, multi_tf_cal_us, multi_tf_cal_iso, multi_tf_cal_anchor_us, multi_tf_cal_anchor_iso)
  - phase: 77-ema-ama-returns-migration
    provides: EMAFeatureConfig.alignment_source field; ema_multi_tf_u with alignment_source PK column
  - phase: 78-01
    provides: Siloed bar tables dropped; alignment_source for base table is 'multi_tf'
provides:
  - EMA feature classes (MultiTFEMAFeature, CalendarEMAFeature, CalendarAnchorEMAFeature) read from price_bars_multi_tf_u with alignment_source filters
  - EMA builder scripts default bars_table = price_bars_multi_tf_u
  - EMAStateConfig carries alignment_source; bar_metadata CTE scoped when reading from _u table
  - Zero references to dropped siloed bar tables in EMA pipeline
affects:
  - Phase 79 daily pipeline operations (EMA refresh now reads from _u)
  - Any future EMA pipeline changes

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "alignment_source filter pattern in bar-read SQL: compute alignment_source from scheme, add AND alignment_source = :alignment_source to WHERE clause"
    - "EMAStateConfig.alignment_source field gates bar_metadata CTE scope in state update SQL"

key-files:
  created: []
  modified:
    - src/ta_lab2/features/m_tf/ema_multi_timeframe.py
    - src/ta_lab2/features/m_tf/ema_multi_tf_cal.py
    - src/ta_lab2/features/m_tf/ema_multi_tf_cal_anchor.py
    - src/ta_lab2/scripts/emas/refresh_ema_multi_tf_from_bars.py
    - src/ta_lab2/scripts/emas/base_ema_refresher.py
    - src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_from_bars.py
    - src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py
    - src/ta_lab2/scripts/emas/ema_state_manager.py

key-decisions:
  - "Cal/cal_anchor feature classes compute alignment_source from self.scheme.lower() at query time (not stored as instance attr), keeping scheme as the single source of truth"
  - "EMAStateConfig.alignment_source field added; bar_metadata CTE uses effective_alignment_source = alignment_source or config.alignment_source to prevent cross-source bar_seq contamination"
  - "Pre-filter TF queries in compat wrappers (write_multi_timeframe_ema_*_to_db) also scope by alignment_source to prevent wrong TF list when using _u table"

patterns-established:
  - "Bar-read SQL alignment filter: alignment_source = f'multi_tf_cal_{self.scheme.lower()}' computed inline; separate param key :alignment_source or :bar_alignment_source"
  - "State config alignment_source propagates through both temp and final EMAStateConfig in from_cli_args_for_scheme()"

# Metrics
duration: 8min
completed: 2026-03-21
---

# Phase 78 Plan 06: EMA Bar Source Redirect Summary

**All EMA builders and feature classes redirected from dropped siloed bar tables to price_bars_multi_tf_u with scheme-specific alignment_source filters**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-21T14:36:00Z
- **Completed:** 2026-03-21T14:44:55Z
- **Tasks:** 2/2
- **Files modified:** 8

## Accomplishments

- All 3 EMA feature classes (MultiTFEMAFeature, CalendarEMAFeature, CalendarAnchorEMAFeature) now default `bars_table` to `price_bars_multi_tf_u` with alignment_source filter in every bar-read SQL query
- All 3 EMA builder scripts default `bars_table` to `price_bars_multi_tf_u`; `EMAStateConfig` constructions pass `alignment_source` in all 6 call sites
- `EMAStateConfig` gains `alignment_source` field; bar_metadata CTE in `_update_canonical_ts_mode` scoped by `effective_alignment_source` to prevent cross-source bar_seq contamination
- Zero references to dropped tables `price_bars_multi_tf`, `price_bars_multi_tf_cal_us`, `price_bars_multi_tf_cal_iso`, `price_bars_multi_tf_cal_anchor_us`, `price_bars_multi_tf_cal_anchor_iso` remain in any EMA file

## Task Commits

1. **Task 1: Update EMA feature classes** - `f860f686` (feat)
2. **Task 2: Update EMA builder scripts and state manager** - `3ecf6c10` (feat)

## Files Created/Modified

- `src/ta_lab2/features/m_tf/ema_multi_timeframe.py` - bars_table default -> _u, alignment_source filter in preload_bar_closes + _load_bar_closes SQL, compat wrapper default updated
- `src/ta_lab2/features/m_tf/ema_multi_tf_cal.py` - self.bars_table -> price_bars_multi_tf_u (both schemes), alignment_source filter in preload_canonical_closes + _load_canonical_closes SQL, pre-filter TF query scoped
- `src/ta_lab2/features/m_tf/ema_multi_tf_cal_anchor.py` - self.bars_table -> price_bars_multi_tf_u (both schemes), alignment_source filter in preload_anchor_bars + _load_anchor_bars SQL, pre-filter TF query scoped
- `src/ta_lab2/scripts/emas/refresh_ema_multi_tf_from_bars.py` - 3 defaults updated, alignment_source='multi_tf' added to both EMAStateConfig constructions
- `src/ta_lab2/scripts/emas/base_ema_refresher.py` - docstring example updated to price_bars_multi_tf_u
- `src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_from_bars.py` - self.bars_table -> _u, both EMAStateConfig bars_table -> _u + alignment_source=multi_tf_cal_{scheme}
- `src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py` - same pattern with multi_tf_cal_anchor_{scheme}
- `src/ta_lab2/scripts/emas/ema_state_manager.py` - alignment_source field added to EMAStateConfig; bar_metadata CTE WHERE TRUE + bar_alignment_filter; effective_alignment_source merges method arg and config field

## Decisions Made

- Cal/cal_anchor feature classes compute `alignment_source = f"multi_tf_cal_{self.scheme.lower()}"` inline at query time rather than storing as instance attribute. The `scheme` field is already the single source of truth; computing alignment_source on demand avoids a parallel attribute that could drift.
- `EMAStateConfig.alignment_source` field is separate from the method-arg `alignment_source` in `_update_canonical_ts_mode`. `effective_alignment_source = alignment_source or config.alignment_source` merges both sources so bar_metadata CTE is always scoped, regardless of whether alignment_source was passed at call time or baked into the config.
- Pre-filter TF queries in backward-compat wrappers (`write_multi_timeframe_ema_cal_to_db` and `write_multi_timeframe_ema_cal_anchor_to_db`) must also scope by alignment_source, otherwise they would see all 5 variants' TFs from the _u table, causing wrong TF filtering.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all changes applied cleanly. Ruff auto-fixed a minor formatting issue in one file on first commit attempt (second commit succeeded).

## Next Phase Readiness

- EMA pipeline fully redirected to price_bars_multi_tf_u; all daily EMA refreshes should now function correctly
- Zero siloed bar table references remain in EMA layer
- Phase 79 (VWAP consolidation + null return row pruning) can proceed without EMA pipeline blockers

---
*Phase: 78-table-drops-script-cleanup*
*Completed: 2026-03-21*
