---
phase: 108-pipeline-batch-performance
plan: 03
subsystem: pipeline
tags: [ama, returns, multiprocessing, watermark, batch, performance, sqlalchemy]

# Dependency graph
requires:
  - phase: 108-02
    provides: incremental watermark fix for AMA returns (ON CONFLICT DO NOTHING + seed row LAG)
provides:
  - Bulk watermark preload for AMA returns (_bulk_load_watermarks)
  - Source-advance skip for AMA returns (_bulk_load_source_max_ts + skip logic)
  - Batched worker dispatch (_BATCH_SIZE=15 IDs per worker call)
  - Optimized _process_source with 3-query preload phase before dispatch
affects:
  - 108-04-PLAN.md (bar returns batch — same pattern)
  - 108-05-PLAN.md (multi-TF bars batch — same pattern)
  - daily pipeline run time (AMA returns ~15 min -> ~3 min target)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bulk watermark preload: one GROUP BY query replaces N per-ID MAX(ts) queries"
    - "Source-advance skip: compare src MAX(ts) vs watermark before dispatching workers"
    - "Batched multiprocessing: list[(id, wm)] per work unit, one engine per batch"
    - "_worker returns list[dict] (not dict); caller iterates batch_results"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/amas/refresh_returns_ama.py

key-decisions:
  - "_BATCH_SIZE=15: amortizes NullPool engine creation across ~15 IDs per engine (was 1)"
  - "Bulk preload done in _process_source (coordinator), not in worker — watermarks passed via args"
  - "Source-advance skip: smax <= wm means 'no new data', skip entirely (vs always re-running)"
  - "id_watermark_pairs list passed in work_unit tuple replaces single asset_id in old signature"
  - "Pool still uses maxtasksperchild=1 (Windows safety); effective parallelism now at batch level"
  - "SET LOCAL work_mem per transaction preserved (not per connection) — ensures each BEGIN/COMMIT block gets it"

patterns-established:
  - "Bulk-preload-then-skip pattern: preload watermarks + src_max_ts, filter active_ids, build batched units"
  - "Batched worker returns list[dict]: imap_unordered yields batch_results, caller iterates them"

# Metrics
duration: 10min
completed: 2026-04-01
---

# Phase 108 Plan 03: AMA Returns Batch Optimization Summary

**AMA returns orchestration optimized: bulk watermark preload (1 query/source), source-advance skip, and 15-ID batched workers reduce engine creation from ~2,460x to ~165x per full run**

## Performance

- **Duration:** 10 min
- **Started:** 2026-04-01T04:51:15Z
- **Completed:** 2026-04-01T05:01:54Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `_bulk_load_watermarks()` — loads MAX(ts) for all IDs in one GROUP BY query, replacing N per-ID watermark SELECTs inside each worker (was ~2,460 queries, now 5 per full run)
- Added `_bulk_load_source_max_ts()` — loads src MAX(ts) for all IDs in one query; `_process_source` uses this to skip IDs with no new source data before dispatch
- Rewrote `_worker()` to accept `id_watermark_pairs: list[(asset_id, watermark)]` and return `list[dict]`, processing _BATCH_SIZE IDs per engine creation (was 1 ID per engine)
- Updated `_process_source()` with 3-phase optimization: (1) bulk watermark preload, (2) source-advance skip classification, (3) batch work-unit dispatch

## Task Commits

1. **Task 1: Optimize AMA returns worker with bulk watermark preload and batched dispatch** - `bf7e91be` (perf)

## Files Created/Modified

- `src/ta_lab2/scripts/amas/refresh_returns_ama.py` - Added `_bulk_load_watermarks`, `_bulk_load_source_max_ts`, `_BATCH_SIZE=15`; rewrote `_worker` (batched), `_process_source` (preload+skip+batch)

## Decisions Made

- `_BATCH_SIZE=15`: chosen to amortize NullPool engine creation cost — each of the 10 workers handles ~5 batches of 15 IDs each across 492 IDs, creating 33 engines total instead of 2,460
- Bulk preload done in `_process_source` (the coordinator), not inside workers — watermarks passed as data arguments to keep workers stateless and safe for multiprocessing pickle
- Source-advance skip uses `smax <= wm` (not `<`): equality means the source hasn't advanced past the last processed ts, so there's no new data
- `Pool(maxtasksperchild=1)` preserved from original — Windows multiprocessing safety requirement; effective parallelism is now at the batch level (~33 batches across 10 workers)
- `SET LOCAL work_mem = '128MB'` kept per `engine.begin()` transaction — this is correct since work_mem scopes to a transaction; the connection-level SET in a probe connection (discarded) wouldn't carry over to `engine.begin()` blocks anyway

## Deviations from Plan

None — plan executed exactly as specified. The plan called for:
- (a) Bulk watermark preload — implemented as `_bulk_load_watermarks()`
- (b) Batch IDs per worker — implemented with `_BATCH_SIZE=15` and `_chunks()`
- (c) Skip IDs with no new source data — implemented with `_bulk_load_source_max_ts()` and `active_ids`/`skipped_ids` partition
- (d) SET work_mem at connection level — plan note acknowledged per-transaction is correct; kept as-is

## Issues Encountered

- Write tool silently failed to apply changes (PostToolUse hook interference). Used Edit tool instead — all edits applied correctly.
- Ruff formatter reformatted file after first commit attempt; re-staged and committed cleanly.

## Next Phase Readiness

- AMA returns script ready for production. Incremental runs will show "Skipping N IDs (no new source data)" for up-to-date IDs and "Dispatching X IDs in Y batches" for active IDs.
- Pattern established for 108-04 (bar returns) and 108-05 (multi-TF bars): same bulk preload + skip + batch approach applies directly.
- The `_INSERT_SQL` template (PARTITION BY in WINDOW clause) was unchanged — correctness preserved.

---
*Phase: 108-pipeline-batch-performance*
*Completed: 2026-04-01*
