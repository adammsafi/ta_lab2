---
phase: 78-table-drops-script-cleanup
plan: 03
subsystem: database
tags: [postgresql, ddl, drop-table, vacuum, storage-optimization, parity-validation]

# Dependency graph
requires:
  - phase: 78-01
    provides: "all_emas view migrated to ema_multi_tf_u; all Category E runtime files query _u tables only"
  - phase: 78-02
    provides: "20 deprecated scripts deleted; _resync_u_tables() removed; orchestrators cleaned"
  - phase: 76-77-direct-to-u
    provides: "All 6 families write directly to _u tables; siloed tables are read-only"
provides:
  - "30 siloed data tables dropped from PostgreSQL (407M+ rows freed)"
  - "VACUUM FULL reclaimed 254 GB disk space (431 GB -> 177 GB, 59% reduction)"
  - "Pre-drop parity validation: all 6 families confirmed u_total >= siloed_total"
  - "33 state tables preserved: 30 siloed-path + 3 cmc_* (actively used by builders)"
affects:
  - phase: 78-04
  - phase: 79-vwap-and-cleanup

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DROP TABLE RESTRICT safe for all siloed tables (no incoming FK constraints)"
    - "Per-family batch transactions for atomic rollback per family"
    - "VACUUM FULL required to return disk to OS (plain VACUUM only marks reusable internally)"

key-files:
  created: []
  modified: []

key-decisions:
  - "State tables (30 siloed-path + 3 cmc_* = 33 total) kept: all actively used by builders for watermark tracking (STATE_TABLE constants); dropping them would break every incremental refresh"
  - "State table expected count corrected: research said 27 non-cmc but live DB has 47 non-cmc (extra stats/feature/signal state tables); verification checks explicitly enumerate the 30 siloed-path ones"
  - "returns_ema_u and returns_ama_u show u_total > siloed_total (+6.89M and +4.09M respectively): expected from direct writes post-Phase 77; parity validation uses >= not =="
  - "VACUUM FULL yielded 254 GB (59%) reduction vs 207 GB (48%) estimated: VACUUM compacted _u table pages too, not just removed dropped table space"

patterns-established:
  - "Pre-drop parity gate: COUNT(*) on all siloed tables vs _u, abort if any u_total < siloed_total"
  - "State table preservation: keep siloed-path state tables until builders explicitly migrated to _u-path state tables"

# Metrics
duration: 137min
completed: 2026-03-21
---

# Phase 78 Plan 03: Table Drops, VACUUM FULL, Storage Reclaim Summary

**Dropped 30 siloed data tables (407M+ rows), ran VACUUM FULL, and reclaimed 254 GB (59% of DB) -- PostgreSQL shrank from 431 GB to 177 GB with all 33 state tables and 6 _u tables intact**

## Performance

- **Duration:** ~137 min (4 min validation + 7.5 min drops + 127.5 min VACUUM FULL)
- **Started:** 2026-03-21T04:06:04Z
- **Completed:** 2026-03-21T06:21:16Z
- **Tasks:** 2
- **Files modified:** 0 (pure DB DDL operation)

## Parity Validation Results (Task 1)

Pre-drop parity check confirmed all 6 families are safe to drop. u_total >= siloed_total for all families.

| Family | Siloed Total | _u Total | Difference | Status |
|--------|-------------|---------|------------|--------|
| price_bars | 12,029,626 | 12,029,626 | +0 | PASS |
| returns_bars | 12,019,640 | 12,019,640 | +0 | PASS |
| ema | 55,796,615 | 55,796,615 | +0 | PASS |
| returns_ema | 48,830,818 | 55,720,846 | +6,890,028 | PASS |
| ama | 170,447,220 | 170,447,220 | +0 | PASS |
| returns_ama | 113,125,842 | 117,213,138 | +4,087,296 | PASS |
| **TOTAL** | **412,249,161** | **421,223,085** | **+8,977,296** | **6/6 PASS** |

The +6.89M and +4.09M extra rows in returns_ema_u and returns_ama_u are direct writes from Phase 77 builders (expected, safe).

## Storage Metrics (Task 2)

| Metric | Value |
|--------|-------|
| DB size before drops | 431 GB |
| DB size after VACUUM FULL | 177 GB |
| Space reclaimed | 254 GB |
| Reduction percentage | 59% |
| VACUUM FULL duration | 127.5 min |

Expected reduction was 48% (~207 GB). Actual reduction was 59% (~254 GB) because VACUUM FULL also compacted the _u tables and other bloated tables, not just freed the dropped-table space.

## Dropped Tables (30 total)

### Family 1: price_bars (5 tables)
- `public.price_bars_multi_tf` (3,271,844 rows)
- `public.price_bars_multi_tf_cal_us` (2,254,850 rows)
- `public.price_bars_multi_tf_cal_iso` (2,254,850 rows)
- `public.price_bars_multi_tf_cal_anchor_us` (2,124,041 rows)
- `public.price_bars_multi_tf_cal_anchor_iso` (2,124,041 rows)

### Family 2: returns_bars (5 tables)
- `public.returns_bars_multi_tf` (3,270,402 rows)
- `public.returns_bars_multi_tf_cal_us` (2,252,653 rows)
- `public.returns_bars_multi_tf_cal_iso` (2,252,653 rows)
- `public.returns_bars_multi_tf_cal_anchor_us` (2,121,966 rows)
- `public.returns_bars_multi_tf_cal_anchor_iso` (2,121,966 rows)

### Family 3: ema (5 tables)
- `public.ema_multi_tf` (24,674,715 rows)
- `public.ema_multi_tf_cal_us` (7,828,616 rows)
- `public.ema_multi_tf_cal_iso` (7,827,227 rows)
- `public.ema_multi_tf_cal_anchor_us` (7,733,441 rows)
- `public.ema_multi_tf_cal_anchor_iso` (7,732,616 rows)

### Family 4: returns_ema (5 tables)
- `public.returns_ema_multi_tf` (17,752,408 rows)
- `public.returns_ema_multi_tf_cal_us` (7,817,671 rows)
- `public.returns_ema_multi_tf_cal_iso` (7,816,280 rows)
- `public.returns_ema_multi_tf_cal_anchor_us` (7,722,643 rows)
- `public.returns_ema_multi_tf_cal_anchor_iso` (7,721,816 rows)

### Family 5: ama (5 tables)
- `public.ama_multi_tf` (58,893,192 rows)
- `public.ama_multi_tf_cal_us` (40,625,748 rows)
- `public.ama_multi_tf_cal_iso` (40,625,874 rows)
- `public.ama_multi_tf_cal_anchor_us` (14,988,852 rows)
- `public.ama_multi_tf_cal_anchor_iso` (15,313,554 rows)

### Family 6: returns_ama (5 tables)
- `public.returns_ama_multi_tf` (56,450,952 rows)
- `public.returns_ama_multi_tf_cal_us` (13,186,332 rows)
- `public.returns_ama_multi_tf_cal_iso` (13,186,152 rows)
- `public.returns_ama_multi_tf_cal_anchor_us` (14,988,852 rows)
- `public.returns_ama_multi_tf_cal_anchor_iso` (15,313,554 rows)

## State Tables Preserved (33 total)

### 30 Siloed-Path State Tables (actively used by builders for watermark tracking)
All 30 preserved -- these hold `last_canonical_ts` and `last_bar_seq` used by incremental refresh scripts:
- price_bars family: 5 state tables
- returns_bars family: 5 state tables
- ema family: 5 state tables
- returns_ema family: 5 state tables
- ama family: 5 state tables
- returns_ama family: 5 state tables

**Rationale:** Plan CONTEXT.md said "drop state tables too -- clean break" but RESEARCH.md confirmed all 30 are actively referenced by builder STATE_TABLE class constants. Dropping them would break every incremental refresh. They total 78 MB (negligible vs 254 GB reclaimed). Kept for Phase 78 scope.

### 3 cmc_* _u-Path State Tables (explicitly verified)
- `cmc_ama_multi_tf_u_state` -- tracks alignment_source watermarks for AMA _u writes
- `cmc_returns_ama_multi_tf_u_state` -- tracks alignment_source watermarks for AMA returns _u writes
- `cmc_returns_ema_multi_tf_u_state` -- tracks alignment_source watermarks for EMA returns _u writes

## _u Tables Intact (6 tables, all queryable)

| Table | Row Count |
|-------|----------|
| price_bars_multi_tf_u | 12,029,626 |
| returns_bars_multi_tf_u | 12,019,640 |
| ema_multi_tf_u | 55,796,615 |
| returns_ema_multi_tf_u | 55,720,846 |
| ama_multi_tf_u | 170,447,220 |
| returns_ama_multi_tf_u | 117,213,138 |

## Accomplishments

- Pre-drop parity validation: all 6 families confirmed u_total >= siloed_total (abort-gate script exited 0)
- 30 siloed data tables dropped (412M rows freed from PostgreSQL catalog)
- VACUUM FULL completed: 431 GB -> 177 GB (-254 GB, -59%)
- all_emas view confirmed working post-drop (55.8M rows, queries ema_multi_tf_u)
- 30 siloed-path state tables preserved intact (builders unaffected)
- 3 cmc_* _u-path state tables explicitly verified present

## Task Commits

These are pure DDL operations (no Python code files changed). No git commits needed for the database operations. The SUMMARY.md and STATE.md update constitutes the plan metadata commit.

## Files Created/Modified

None - this plan operated entirely at the PostgreSQL DDL level (DROP TABLE, VACUUM FULL).

## Decisions Made

- **State table count in verification:** Research said 27 non-cmc siloed-path state tables. Live DB has 47 non-cmc state tables (extra stats/feature/signal/pipeline state tables not enumerated in research). Verification logic was updated to explicitly check the 30 named siloed-path state tables rather than relying on a count of `*_state` tables.
- **VACUUM FULL timing:** Ran as a single `VACUUM FULL` on the entire database rather than table-by-table. Completed in 127.5 minutes. No concurrent workload to worry about (dev/research DB).
- **State tables retained:** All 30 siloed-path state tables kept intact. The 78 MB cost is negligible vs 254 GB reclaimed. Migrating builder STATE_TABLE constants to new _u-path state tables is a follow-up concern, not Phase 78 scope.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] State table count check used wrong expected value**

- **Found during:** Task 2 verification
- **Issue:** Plan verification script expected 27 non-cmc state tables but live DB has 47 non-cmc state tables (extra stats/feature/signal/pipeline state tables not counted in RESEARCH.md's enumeration of 30 siloed-path tables). The check `WHERE tablename LIKE '%_state' AND tablename NOT LIKE 'cmc_%'` returns 47, not 27.
- **Fix:** Updated verification to explicitly enumerate all 30 named siloed-path state tables and check each by name, rather than relying on a count of `*_state` pattern matches. This is more robust and correctly verifies the actual requirement.
- **Verification:** All 30 named state tables confirmed present; all 3 cmc_* tables confirmed present.

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: wrong expected count for state table verification)
**Impact on plan:** Minor verification logic fix; no data was affected. All 33 state tables confirmed present and correct.

## Issues Encountered

None of note. VACUUM FULL ran without interruption for 127.5 minutes.

## Next Phase Readiness

- Phase 78 is now complete: view migrated (78-01), scripts cleaned (78-02), tables dropped (78-03)
- Database is 177 GB (down from 431 GB) -- 59% storage reduction achieved
- All 6 _u tables are the single source of truth for their respective data families
- All 6 builder families continue to work normally (state tables preserved)
- Phase 79 (VWAP consolidation + null row pruning) can proceed

---
*Phase: 78-table-drops-script-cleanup*
*Completed: 2026-03-21*
