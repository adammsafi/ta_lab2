---
phase: 77-direct-to-u-remaining-families
plan: "02"
subsystem: database
tags: [postgresql, ema, alignment_source, direct-to-u, migration, pandas]

# Dependency graph
requires:
  - phase: 77-01
    provides: bar returns direct-to-_u pattern (alignment_source in valid_cols, state scoping)
  - phase: 76-direct-to-u-price-bars-pilot
    provides: price bars _u upsert pattern (conflict_cols tuple, alignment_source stamping)
provides:
  - ema_multi_tf_u PK includes alignment_source (id, venue_id, ts, tf, period, alignment_source)
  - All 3 EMA builders (multi_tf, cal_us, cal_iso, cal_anchor_us, cal_anchor_iso) write directly to ema_multi_tf_u
  - BaseEMAFeature stamps alignment_source on DataFrame BEFORE to_sql/_pg_upsert call
  - EMAStateManager.update_state_from_output() scoped by alignment_source to avoid cross-source contamination
  - Row count parity confirmed: 55,796,615 total rows, all 5 sources MATCH
  - sync_ema_multi_tf_u.py disabled as no-op with DeprecationWarning
affects:
  - Phase 78 (cleanup: remove disabled sync scripts)
  - Phase 77-03 (EMA returns builders - same pattern applies)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - EMAFeatureConfig.alignment_source field gates PK extension and DataFrame stamp
    - alignment_source stamped on df_write BEFORE to_sql (not after) - critical for INSERT column inclusion
    - EMAStateManager alignment_source scoping: WHERE clause appended in both canonical_ts and multi_tf modes
    - ISO sources required backfill (1.7M + 1.6M rows) due to incomplete prior sync runs

key-files:
  created:
    - .planning/phases/77-direct-to-u-remaining-families/77-02-row-count-verification.txt
  modified:
    - src/ta_lab2/features/m_tf/base_ema_feature.py
    - src/ta_lab2/scripts/emas/refresh_ema_multi_tf_from_bars.py
    - src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_from_bars.py
    - src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py
    - src/ta_lab2/scripts/emas/ema_state_manager.py
    - src/ta_lab2/scripts/emas/base_ema_refresher.py
    - src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py

key-decisions:
  - "EMAFeatureConfig.alignment_source (Optional[str]=None) gates both PK extension and DataFrame stamp - single field controls both behaviors"
  - "alignment_source appended to PK list in _get_pk_columns() when set (not from subclass get_output_schema())"
  - "ISO backfill required: initial sync gaps of 1.7M (cal_iso) + 1.6M (cal_anchor_iso) rows backfilled via direct INSERT...ON CONFLICT DO NOTHING"
  - "sync_ema_multi_tf_u.py old ON CONFLICT (id, venue_id, ts, tf, period) DO NOTHING broke after PK change - script disabled as no-op"
  - "base_ema_refresher.py gets alignment_source from extra_config dict (not a new config field)"
  - "State table PK remains (id, venue_id, tf, period) - no alignment_source needed there"

patterns-established:
  - "alignment_source in EMAFeatureConfig: Optional[str] = None pattern (same as cal variant approach)"
  - "df_write[alignment_source] = self.config.alignment_source BEFORE to_sql in write_to_db()"
  - "WHERE alignment_source = :alignment_source appended to both canonical_ts and daily_range CTEs"
  - "alignment_filter = 'AND alignment_source = :alignment_source' if alignment_source else '' pattern in _update_multi_tf_mode"

# Metrics
duration: 35min
completed: 2026-03-20
---

# Phase 77 Plan 02: EMA Values Direct-to-_u Migration Summary

**ema_multi_tf_u PK fixed to include alignment_source; all 5 EMA variant builders redirected to _u with per-variant alignment_source stamped; 55.8M rows at parity; sync script disabled**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-03-20T~09:00Z
- **Completed:** 2026-03-20T~09:35Z
- **Tasks:** 3 (1a + 1b + 2)
- **Files modified:** 7

## Accomplishments

- DB schema fixed: `ema_multi_tf_u` PK now `(id, venue_id, ts, tf, period, alignment_source)` replacing old `(id, ts, tf, period, venue_id)`
- `EMAFeatureConfig` dataclass extended with optional `alignment_source` field that gates both PK extension and DataFrame stamp
- All 3 EMA builder scripts (multi_tf, cal, cal_anchor) redirect to `ema_multi_tf_u` with correct per-variant `alignment_source`
- `EMAStateManager` `update_state_from_output()` now accepts `alignment_source` parameter, scoping all CTEs to avoid cross-source contamination
- ISO backfill: +1,731,920 (multi_tf_cal_iso) + 1,637,309 (multi_tf_cal_anchor_iso) rows inserted to close sync gaps
- All 5 alignment_sources confirmed MATCH: 55,796,615 total rows in `ema_multi_tf_u`
- `sync_ema_multi_tf_u.py` replaced with no-op deprecation stub

## Task Commits

Each task was committed atomically:

1. **Tasks 1a+1b: DB PK fix + EMA builders + state manager alignment_source** - `8a518ed2` (feat)
2. **Task 2: Row count parity verification + sync script disabled** - `fa3cd2b6` (feat)

## Files Created/Modified

- `src/ta_lab2/features/m_tf/base_ema_feature.py` - EMAFeatureConfig.alignment_source field; _get_pk_columns() appends it; write_to_db() stamps before to_sql
- `src/ta_lab2/scripts/emas/refresh_ema_multi_tf_from_bars.py` - default out_table -> ema_multi_tf_u; alignment_source="multi_tf" in extra_config
- `src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_from_bars.py` - default out_us/iso -> ema_multi_tf_u; alignment_source=multi_tf_cal_{scheme}
- `src/ta_lab2/scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py` - default out_us/iso -> ema_multi_tf_u; alignment_source=multi_tf_cal_anchor_{scheme}
- `src/ta_lab2/scripts/emas/ema_state_manager.py` - update_state_from_output(alignment_source=None); both private methods scope by alignment_source
- `src/ta_lab2/scripts/emas/base_ema_refresher.py` - extracts alignment_source from extra_config, passes to state_manager in _run_incremental and _run_full_refresh
- `src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py` - replaced with no-op + DeprecationWarning
- `.planning/phases/77-direct-to-u-remaining-families/77-02-row-count-verification.txt` - row count verification artifact

## Decisions Made

- `EMAFeatureConfig.alignment_source` (Optional[str]=None): single optional field that gates both the PK extension in `_get_pk_columns()` and the DataFrame stamp in `write_to_db()`. Keeps the feature config interface clean.
- `alignment_source` appended to PK list from `_get_pk_columns()` rather than requiring all subclasses to update their `get_output_schema()` dict. Minimal-change approach.
- ISO sources required backfill: the old sync script used `ON CONFLICT (id, venue_id, ts, tf, period) DO NOTHING` which had silently skipped rows that conflicted on the old PK. After PK change, those rows were inserted via direct SQL backfill.
- `sync_ema_multi_tf_u.py` disabled immediately: after PK change the old script's ON CONFLICT clause was invalid (raises `InvalidColumnReference`), making it a broken no-op anyway. Replaced cleanly.
- State table PK remains `(id, venue_id, tf, period)` without `alignment_source` - all 5 EMA variants cover the same (id, tf, period) space and can share state rows.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ISO sync gaps required backfill before disabling sync script**
- **Found during:** Task 2 (row count parity check)
- **Issue:** `multi_tf_cal_iso` deficit of -1,731,920 rows and `multi_tf_cal_anchor_iso` deficit of -1,637,309 rows. Old sync script's watermark-based incremental had left gaps.
- **Fix:** Direct SQL `INSERT...ON CONFLICT (id, venue_id, ts, tf, period, alignment_source) DO NOTHING` using new PK to backfill both ISO tables
- **Files modified:** DB only (no Python files)
- **Verification:** Re-ran parity check; all 5 sources now show MATCH
- **Committed in:** fa3cd2b6 (Task 2 commit)

**2. [Rule 1 - Bug] Old sync script ON CONFLICT clause invalid after PK change**
- **Found during:** Task 2 (attempt to run old sync for backfill)
- **Issue:** `sync_ema_multi_tf_u.py` used `ON CONFLICT (id, venue_id, ts, tf, period) DO NOTHING` - references old PK. After PK change to include `alignment_source`, PostgreSQL raises `InvalidColumnReference`
- **Fix:** Performed backfill directly via Python using new PK columns; then disabled sync script as planned
- **Files modified:** `sync_ema_multi_tf_u.py` (replaced with no-op)
- **Verification:** `grep DEPRECATED` returns match; Python parses OK
- **Committed in:** fa3cd2b6 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2x Rule 1 bugs)
**Impact on plan:** Both auto-fixes necessary for data completeness and correctness. No scope creep.

## Issues Encountered

- Old sync script failed immediately on attempt to backfill ISO gaps: `InvalidColumnReference` because PK change made old ON CONFLICT clause invalid. Handled by running direct SQL INSERT with new PK.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 2 (EMA values) complete. `ema_multi_tf_u` is the sole write target for all 5 EMA variants.
- Wave 3 (EMA returns) can proceed with same pattern: `returns_ema_multi_tf_u` builders need same alignment_source treatment.
- Phase 78 (cleanup) can remove `sync_ema_multi_tf_u.py` and `sync_price_bars_multi_tf_u.py` and `sync_returns_bars_multi_tf_u.py` as all 3 are now no-ops.
- No blockers identified.

---
*Phase: 77-direct-to-u-remaining-families*
*Completed: 2026-03-20*
