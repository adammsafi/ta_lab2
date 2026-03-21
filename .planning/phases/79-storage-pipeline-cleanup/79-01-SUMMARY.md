---
phase: 79
plan: "01"
name: prune-null-ama-returns
subsystem: ama-returns
tags: [ama, returns, null-prune, sql, cleanup, storage]

dependency_graph:
  requires:
    - "77-05: AMA returns _u migration (introduced returns_ama_multi_tf_u)"
  provides:
    - "returns_ama_multi_tf_u free of all-NULL first-observation rows"
    - "refresh_returns_ama.py SQL filters first-observation rows going forward"
  affects:
    - "All downstream queries on returns_ama_multi_tf_u (leaner table, no dead rows)"

tech_stack:
  added: []
  patterns:
    - "WHERE delta1_ama_roll IS NOT NULL filter in INSERT SQL to exclude LAG()-NULL first-observation rows"
    - "Batched DELETE by alignment_source to avoid single mega-transaction"

key_files:
  created: []
  modified:
    - src/ta_lab2/scripts/amas/refresh_returns_ama.py

decisions:
  - "Filter on delta1_ama_roll IS NOT NULL (not delta1 from pass1) because pass2 renames delta1 AS delta1_ama_roll"
  - "One DELETE per alignment_source (5 batches) rather than one DELETE for all rows -- follows key convention of batching large table operations"
  - "VACUUM ANALYZE (not VACUUM FULL) per plan instructions -- reclaims space without exclusive lock"
  - "NULL pruning CLN-01 requirement: first-observation rows where LAG() returns NULL for all return columns"

metrics:
  duration: "31 min"
  completed: "2026-03-21"
---

# Phase 79 Plan 01: Prune NULL AMA Returns Summary

**One-liner:** Pruned 7,180,871 all-NULL first-observation rows from `returns_ama_multi_tf_u` (-6.13%) and added `WHERE delta1_ama_roll IS NOT NULL` filter to prevent new ones.

## What Was Built

Added a first-observation filter to `refresh_returns_ama.py`'s `_INSERT_SQL` template and ran a one-time batched DELETE to remove existing NULL rows from `returns_ama_multi_tf_u`.

AMA returns tables contained ~6.13% dead-weight rows where all return columns were NULL -- these are the first observation per series per (id, tf, indicator, params_hash) partition where `LAG()` has no prior value to subtract from. Bar returns and EMA returns builders already filter these out; this plan brings AMA returns into parity.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add first-observation filter + prune NULL rows | 7ad9baf7 | refresh_returns_ama.py |

## Row Count Reduction

**Pre-prune:**
- Total rows: 117,213,138
- NULL rows: 7,180,871 (6.13%)

**By alignment_source:**
| alignment_source | rows deleted |
|-----------------|-------------|
| multi_tf | 2,524,000 |
| multi_tf_cal_us | 1,122,693 |
| multi_tf_cal_iso | 1,122,799 |
| multi_tf_cal_anchor_us | 1,192,054 |
| multi_tf_cal_anchor_iso | 1,219,325 |
| **Total** | **7,180,871** |

**Post-prune:**
- Total rows: 110,032,267
- NULL rows: 0
- VACUUM ANALYZE run after prune

## SQL Change

`_INSERT_SQL` in `refresh_returns_ama.py` (line 150):

```sql
-- Before
SELECT *, '{alignment_source}'::text AS alignment_source FROM pass2
ON CONFLICT (id, venue_id, ts, tf, indicator, params_hash, alignment_source) DO NOTHING

-- After
SELECT *, '{alignment_source}'::text AS alignment_source FROM pass2
WHERE delta1_ama_roll IS NOT NULL
ON CONFLICT (id, venue_id, ts, tf, indicator, params_hash, alignment_source) DO NOTHING
```

The filter uses `delta1_ama_roll` (the pass2 column name) not `delta1` (the pass1 alias) because pass2 renames `delta1 AS delta1_ama_roll`.

## Verification

- `SELECT COUNT(*) FROM returns_ama_multi_tf_u WHERE delta1_ama_roll IS NULL AND ... (all 6 cols NULL)` returns 0
- `grep "WHERE delta1_ama_roll IS NOT NULL" src/ta_lab2/scripts/amas/refresh_returns_ama.py` returns line 150
- `python -m py_compile src/ta_lab2/scripts/amas/refresh_returns_ama.py` passes

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Filter on `delta1_ama_roll` not `delta1` | pass2 renames `delta1 AS delta1_ama_roll`; using `delta1` would reference pass1 column not visible in final SELECT |
| Batch DELETE by alignment_source (5 batches) | Follows project convention: large tables always batch to avoid multi-hour single transactions |
| VACUUM ANALYZE not VACUUM FULL | Plan specified VACUUM ANALYZE; no exclusive lock needed, regular reclaim sufficient |

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

- CLN-01 requirement satisfied: first-observation NULL rows pruned and future inserts filtered
- `returns_ama_multi_tf_u` is now consistent with `returns_bars_multi_tf_u` and `returns_ema_multi_tf_u` (both already filter first-observation rows)
- No blockers for remaining Phase 79 plans
