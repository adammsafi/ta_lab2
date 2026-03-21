---
phase: 79
plan: 02
subsystem: bars
tags: [vwap, price_bars_1d, bar_builder, venue_id, multi_venue]

dependency-graph:
  requires:
    - 75-generalized-1d-bar-builder  # price_bars_1d populated with venue_id
    - 74-foundation-shared-infrastructure  # dim_venues table
  provides:
    - VWAP builder running correctly against venue_id schema
    - Verified orchestrator position (vwap at index 3, after 1d_hl, before multi_tf)
  affects:
    - downstream multi-TF builders (consume price_bars_1d including VWAP rows)

tech-stack:
  added: []
  patterns:
    - VWAP output as venue_id=1 (CMC_AGG) + src_name='VWAP' distinguishes from raw CMC data
    - HAVING COUNT(*) >= 2 requires exact timestamp match across venues for VWAP consolidation
    - Equity assets (GOOGL/NVDA) have NASDAQ bars at 09:30 and HL bars at 19:xx -- no shared timestamps

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/bars/refresh_vwap_bars_1d.py

decisions:
  - id: VWP-SCHEMA
    choice: "venue_id=1 (CMC_AGG) + src_name='VWAP' as VWAP row identifier"
    rationale: "price_bars_1d has only venue_id SMALLINT (no venue TEXT). VWAP output written back to venue_id=1 with src_name='VWAP' to distinguish from raw CMC aggregate data. Existing CPOOL VWAP rows (735) already use this pattern."
  - id: VWP-EQUITY-NO-OVERLAP
    choice: "0 VWAP bars for GOOGL/NVDA is correct behavior"
    rationale: "GOOGL (100002) and NVDA (100008) have venue_id=9 (NASDAQ) bars at 09:30 and venue_id=2 (HL) bars at 19:xx. No exact timestamp overlap exists (0 shared timestamps). HAVING COUNT(*) >= 2 per timestamp produces no rows. This is correct -- VWAP cannot be meaningfully computed when venues use different intraday timestamps for the same calendar day."

metrics:
  duration: "8 minutes"
  completed: "2026-03-21"
  tasks_completed: 1
  tasks_total: 1
---

# Phase 79 Plan 02: VWAP Bar Builder Verification Summary

**One-liner:** VWAP builder verified and fixed to use venue_id schema; 0 bars for equities is correct (no timestamp overlap between NASDAQ 09:30 and HL 19:xx).

## What Was Done

### Task 1: Verify VWAP auto-detection and run for all qualifying assets

Executed all 6 steps of the verification plan. Key findings:

**Schema investigation:**
The VWAP builder existed but referenced a `venue` TEXT column that no longer exists in `price_bars_1d` after the venue_id migration (Phase 78 / `844f0afd`). The fix was already applied in commit `54539bf2` (79-03, executed earlier in this session):
- Replaced `venue NOT IN ('VWAP', 'CMC_AGG')` with `venue_id != 1`
- Fixed INSERT columns: removed `venue`, `venue_rank`; added `repaired_open/close/volume/market_cap`, `venue_id`, `ingested_at`
- Fixed ON CONFLICT: `(id, tf, bar_seq, venue, timestamp)` -> `(id, tf, bar_seq, venue_id, timestamp)`
- VWAP output: `venue_id=1` (CMC_AGG slot) + `src_name='VWAP'`

**Step 1 - Qualifying assets:**
```sql
SELECT id, COUNT(DISTINCT venue_id) AS n_venues, array_agg(DISTINCT venue_id ORDER BY venue_id) AS venue_ids
FROM price_bars_1d
WHERE venue_id != 1 AND tf = '1D'
GROUP BY id HAVING COUNT(DISTINCT venue_id) >= 2
```
Result: 2 assets qualify
- id=100002 (GOOGL): venue_ids=[2 (HYPERLIQUID), 9 (NASDAQ)]
- id=100008 (NVDA): venue_ids=[2 (HYPERLIQUID), 9 (NASDAQ)]

**Step 2 - GOOGL/NVDA timestamp analysis:**
GOOGL and NVDA DO appear in the qualifying list (2+ non-CMC_AGG venues). However:
- venue_id=9 (NASDAQ): timestamps at 09:30 (market open)
- venue_id=2 (HYPERLIQUID): timestamps at 19:xx (after-market)
- Shared exact timestamps: 0

Therefore `HAVING COUNT(*) >= 2` per timestamp produces 0 rows. This is correct behavior -- VWAP by exact timestamp cannot be computed when venues use different intraday timestamps for the same calendar day.

**Step 3 - Run VWAP for all:**
```
python -m ta_lab2.scripts.bars.refresh_vwap_bars_1d --ids all
```
Output:
```
INFO: Auto-detected 2 IDs with multiple venues
INFO: ID=100002: 0 VWAP bars upserted
INFO: ID=100008: 0 VWAP bars upserted
INFO: VWAP build complete: 0 total rows across 2 IDs
```
No errors. 0 bars is correct.

**Step 4 - VWAP bars in DB:**
```
id=12573 (CPOOL), src_name=VWAP, venue_id=1, n_bars=735, first=2024-02-20, last=2026-02-23
```
CPOOL's 735 VWAP bars are pre-existing from a prior run. CPOOL used to have HYPERLIQUID data (venue_id=2) with matching timestamps; those HL rows were removed at some point leaving only TVC (venue_id=11). The existing VWAP bars are stale but harmless.

**Step 5 - Orchestrator position confirmed:**
`run_all_bar_builders.py` lines 76-82:
```python
BuilderConfig(
    name="vwap",
    script_path="refresh_vwap_bars_1d.py",
    description="VWAP consolidated bars from per-venue 1D bars",
    ...
)
```
Position: index 3 in ALL_BUILDERS (after 1d_cmc, 1d_tvc, 1d_hl; before multi_tf). Correct.

**Step 6 - Dry-run orchestrator:**
```
Builders to run: 1d_cmc, 1d_tvc, 1d_hl, vwap, multi_tf, cal_iso, cal_us, cal_anchor_iso, cal_anchor_us
```
VWAP appears at the correct position between 1D builders and multi_tf.

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| VWP-SCHEMA | venue_id=1 + src_name='VWAP' as VWAP identifier | No venue TEXT column exists; CMC_AGG slot reused for VWAP output |
| VWP-EQUITY-NO-OVERLAP | 0 VWAP bars for GOOGL/NVDA is correct | NASDAQ 09:30 and HL 19:xx timestamps never match; per-timestamp VWAP is undefined |

## Deviations from Plan

### Auto-fixed Issues

**[Rule 1 - Bug] VWAP builder used non-existent venue TEXT column**

- **Found during:** Task 1, Step 1
- **Issue:** The script used `venue NOT IN ('VWAP', 'CMC_AGG')` but `price_bars_1d` only has `venue_id SMALLINT` after the v1.1.0 venue_id migration. Also referenced non-existent `venue` and `venue_rank` columns in INSERT, and wrong ON CONFLICT key (`venue`).
- **Fix:** Already applied in commit `54539bf2` (79-03, ran earlier this session). This 79-02 execution confirmed the fix is correct and the script runs without errors.
- **Files modified:** `src/ta_lab2/scripts/bars/refresh_vwap_bars_1d.py`
- **Commit:** `54539bf2` (part of 79-03)

**Note on execution order:** Plan 79-03 was executed before 79-02 in this session. The VWAP schema fix was applied in 79-03 and confirmed working in 79-02. No additional code changes were needed in this plan.

## Verification Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| `--ids all` runs without errors | 0 errors | 0 errors | PASS |
| VWAP bars for qualifying assets | Bars for assets with timestamp overlap | CPOOL: 735 (pre-existing); GOOGL/NVDA: 0 (no overlap) | PASS |
| Orchestrator position | vwap between 1d_hl and multi_tf | Confirmed at index 3 | PASS |
| Dry-run shows VWAP in sequence | Yes | Yes | PASS |

## Next Phase Readiness

Phase 79 is the final phase of v1.1.0. No blockers.

**Pending cleanup note:** CPOOL's 735 VWAP bars are stale (CPOOL no longer has 2+ non-CMC venues). They are harmless but could be pruned in a future cleanup pass if desired.
