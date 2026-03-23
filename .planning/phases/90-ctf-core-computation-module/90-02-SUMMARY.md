---
phase: 90-ctf-core-computation-module
plan: 02
subsystem: features
tags: [cross-timeframe, ctf, slope, divergence, agreement, crossover, scoped-delete, sqlalchemy, pandas, polyfit]

# Dependency graph
requires:
  - phase: 90-01
    provides: CTFConfig, CTFFeature with loading/alignment methods
  - phase: 89-ctf-schema-dimension-table
    provides: public.ctf fact table (PK: id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)
provides:
  - Complete CTF computation engine: all 4 composite functions + orchestrator + DB write
  - _compute_slope: vectorized rolling polyfit slope (raw=True, expression_engine pattern)
  - _compute_divergence: (base - ref) / rolling_std z-score with configurable window
  - _compute_agreement: rolling sign-match fraction, respects is_directional flag
  - _compute_crossover: +1/-1/0 for directional, NaN for non-directional
  - _write_to_db: scoped DELETE (id, venue_id, base_tf, ref_tf, indicator_ids, alignment_source) + to_sql INSERT
  - compute_for_ids: top-level orchestrator over all YAML TF/source combos
  - 1,755,512 rows in ctf table for id=1 (BTC) across 15 TF pairs
affects:
  - 91-ctf-refresh-script: daily refresh script calling compute_for_ids
  - 92+: CTF features available to signal and ML layers

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Vectorized rolling polyfit: np.arange fixed x-array pre-computed, raw=True in .apply()"
    - "Scoped DELETE + to_sql INSERT: DELETE scope matches (id, venue_id, base_tf, ref_tf, indicator_ids, alignment_source)"
    - "Per-asset computation loop: avoids cross-asset contamination in rolling windows"
    - "venue_id filter on ALL source tables: all 4 tables have multiple venues in PK, filter required"
    - "astype(float) before computation: converts None (DB NULL) to NaN for safe numpy arithmetic"
    - "min_periods = min(window, max(5, window//3)): cap min_periods to not exceed window size"

key-files:
  created: []
  modified:
    - src/ta_lab2/features/cross_timeframe.py

key-decisions:
  - "ALL 4 source tables require venue_id filter (plan 01 decision was incomplete -- returns_bars_multi_tf_u and all others also have multiple venues)"
  - "Series.astype(float) before any numpy computation: DB NULLs come back as Python None which breaks numpy diff/sign"
  - "min_periods = min(window, max(5, window//3)): standard formula but must be capped at window"
  - "Unused yaml_section_map removed (F841 ruff): _compute_one_source receives full yaml_cfg dict"
  - "Per-indicator _write_to_db calls (not batched): each indicator has its own DELETE scope by indicator_id"

patterns-established:
  - "CTF write pattern: per-indicator scoped DELETE + to_sql append (matches features write pattern)"
  - "Float coercion at computation layer: all input series coerced to float before rolling math"

# Metrics
duration: 38min
completed: 2026-03-23
---

# Phase 90 Plan 02: CTF Computation Engine Complete Summary

**Complete CTF engine: 4 composite functions (slope/divergence/agreement/crossover) + scoped DELETE+INSERT write + compute_for_ids orchestrator; produces 1,755,512 rows in ctf for BTC across 15 TF pairs**

## Performance

- **Duration:** 38 min (includes full BTC computation run: ~8 min)
- **Started:** 2026-03-23T20:06:53Z
- **Completed:** 2026-03-23T20:44:54Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- 4 module-level computation helpers added to `cross_timeframe.py`:
  - `_compute_slope(series, window)`: rolling OLS slope via polyfit (expression_engine.py pattern, raw=True)
  - `_compute_divergence(base, ref, window)`: (base - ref) / rolling_std z-score
  - `_compute_agreement(base, ref, is_directional, window=20)`: rolling sign-match fraction (sign of value for directional, sign of diff for non-directional)
  - `_compute_crossover(base, ref, is_directional)`: +1/-1/0 for directional, all-NaN for non-directional
- `CTFFeature._write_to_db(df, base_tf, ref_tf, indicator_ids)`: scoped DELETE + to_sql INSERT, idempotent
- `CTFFeature._compute_one_source(ids, base_tf, ref_tf, source_table, source_indicators, yaml_config)`: per-indicator alignment + per-asset computation + write
- `CTFFeature.compute_for_ids(ids)`: top-level orchestrator iterating all (base_tf, ref_tf) x source_table combos from YAML
- Integration test passed: 1,755,512 rows across 15 TF pairs for BTC (id=1)
- Idempotency verified: re-run produces same row count (11,228 rows before == after)

## Task Commits

1. **Task 1: Add composites, write method, orchestrator** - `3a3faa27` (feat)

## Files Created/Modified

- `src/ta_lab2/features/cross_timeframe.py` - Complete CTF engine (469 lines added, 15 modified)

## Decisions Made

- ALL 4 source tables require `venue_id = :venue_id` WHERE filter: confirmed all 4 (ta, vol, returns_bars_multi_tf_u, features) have multiple venues in PK. Plan 01 decision was incomplete (only features got the filter).
- `Series.astype(float)` before numpy computation: DB NULL values arrive as Python `None`, which breaks `.diff()`, `np.sign()` arithmetic. Cast to float before all rolling operations.
- `min_periods = min(window, max(5, window // 3))`: ensures min_periods never exceeds window parameter (would cause ValueError in pandas).
- Unused `yaml_section_map` removed: pre-commit hook caught F841. Full `yaml_cfg` dict passed to `_compute_one_source` directly; section map was not needed.
- Per-indicator `_write_to_db` calls (not batched): clean DELETE scope per indicator_id, no risk of cross-indicator contamination.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] venue_id filter missing for returns_bars_multi_tf_u (and implicit for ta/vol)**

- **Found during:** Task 1 integration test (UniqueViolation on indicator_id=19, returns table)
- **Issue:** Plan 01 summary stated "only features gets venue_id filter", but all 4 source tables have venue_id in PK and multiple venues. Without filter, duplicate (id, ts, tf, alignment_source) rows exist per venue.
- **Fix:** Changed `if source_table in ("ta", "vol", "features")` to apply `venue_id = :venue_id` filter unconditionally (all 4 tables). Params dict always includes `venue_id`.
- **Files modified:** `cross_timeframe.py` - `_load_indicators_batch`
- **Commit:** `3a3faa27`

**2. [Rule 1 - Bug] Python None from DB causes TypeError in numpy arithmetic**

- **Found during:** Task 1 integration test (TypeError: unsupported operand '-': NoneType - NoneType)
- **Issue:** DB NULL values for RSI/MACD during warmup period are deserialized by pandas as Python `None` (not numpy NaN). Calling `.diff()` or `np.sign()` on a Series with `None` values raises TypeError.
- **Fix:** Added `base_f = base_series.astype(float)` / `ref_f = ref_series.astype(float)` at start of each computation helper. Float coercion converts `None` to `np.nan`.
- **Files modified:** `cross_timeframe.py` - `_compute_slope`, `_compute_divergence`, `_compute_agreement`, `_compute_crossover`
- **Commit:** `3a3faa27`

**3. [Rule 1 - Bug] min_periods exceeded window in _compute_agreement for small test windows**

- **Found during:** Sanity check with window=3 (test helper check)
- **Issue:** `max(5, window // 3)` = `max(5, 1)` = 5, which exceeds `window=3`. pandas raises ValueError.
- **Fix:** `min_periods = min(window, max(5, window // 3))` caps min_periods at window size.
- **Files modified:** `cross_timeframe.py` - `_compute_agreement`
- **Commit:** `3a3faa27`

## Issues Encountered

- Integration test took ~8 min for BTC (1 asset, 22 indicators, 15 TF pairs). For all 99 assets this would be ~13 hours single-threaded. Phase 91 refresh script will need multiprocessing by asset batch.

## User Setup Required

None.

## Next Phase Readiness

- `CTFFeature.compute_for_ids(ids)` is the primary API for Phase 91 refresh script
- 15 TF pairs x 22 indicators x ~5,600 bars = ~1.75M rows per asset (BTC as reference)
- Scoped DELETE + INSERT is idempotent: refresh script can call compute_for_ids without pre-cleanup
- No blockers

---
*Phase: 90-ctf-core-computation-module*
*Completed: 2026-03-23*
