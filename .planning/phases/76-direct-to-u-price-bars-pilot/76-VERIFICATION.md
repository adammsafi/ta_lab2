---
phase: 76-direct-to-u-price-bars-pilot
verified: 2026-03-20T13:43:43Z
status: passed
score: 9/9 must-haves verified
---

# Phase 76: Direct-to-U Price Bars Pilot Verification Report

**Phase Goal:** Price bar pipeline writes directly to price_bars_multi_tf_u, validating the pattern for all remaining families
**Verified:** 2026-03-20T13:43:43Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | All 5 builders write to price_bars_multi_tf_u (not siloed tables) | VERIFIED | OUTPUT_TABLE = "public.price_bars_multi_tf_u" in all 5 builder class constants and DEFAULT_BARS_TABLE constants |
| 2  | Each builder stamps alignment_source on every row before upsert | VERIFIED | bars["alignment_source"] = self.ALIGNMENT_SOURCE in all code paths (full rebuild, incremental, from_1d) across all 5 builders |
| 3  | conflict_cols include alignment_source in all upsert calls | VERIFIED | All upsert_bars() call sites pass conflict_cols=("id","tf","bar_seq","venue_id","timestamp","alignment_source") |
| 4  | Delete operations scope by alignment_source | VERIFIED | delete_bars_for_id_tf(..., alignment_source=self.ALIGNMENT_SOURCE) in all 5 builders; from_1d path uses inline DELETE scoped by alignment_source |
| 5  | _load_last_snapshot_info filters by alignment_source in all 3 CTEs | VERIFIED | AND alignment_source = :alignment_source present in all 3 CTEs of the snapshot query in every builder |
| 6  | venue_id unconditionally set on all output DataFrames | VERIFIED | bars["venue_id"] = bars.get("venue_id", 1) unconditional assignment before every upsert in all 5 builders |
| 7  | State tables pre-populated from price_bars_multi_tf_u actual data | VERIFIED | Bootstrap confirmed in 76-01-SUMMARY: ON CONFLICT DO UPDATE GREATEST() watermark logic, 1442 to 5610 rows per table |
| 8  | sync_price_bars_multi_tf_u.py is a no-op with deprecation notice | VERIFIED | main() body replaced with print() + return; no data movement; zero references in run_all_bar_builders.py or run_daily_refresh.py |
| 9  | Row counts per alignment_source match pre-migration totals | VERIFIED | 76-row-count-verification.txt: all 5 alignment_sources MATCH, 12,029,626 total rows, 0 WARN, 0 FAIL |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
|  | alignment_source in valid_cols + delete param | VERIFIED | Line 1009: "alignment_source" in valid_cols; lines 1457-1481: alignment_source param + WHERE clause in delete_bars_for_id_tf() |
|  | OUTPUT_TABLE=_u, ALIGNMENT_SOURCE=multi_tf | VERIFIED | Line 134: OUTPUT_TABLE = "public.price_bars_multi_tf_u"; Line 135: ALIGNMENT_SOURCE = "multi_tf"; 1266 lines |
|  | OUTPUT_TABLE=_u, ALIGNMENT_SOURCE=multi_tf_cal_us | VERIFIED | Line 178: OUTPUT_TABLE = "public.price_bars_multi_tf_u"; Line 179: ALIGNMENT_SOURCE = "multi_tf_cal_us"; 1173 lines |
|  | OUTPUT_TABLE=_u, ALIGNMENT_SOURCE=multi_tf_cal_iso | VERIFIED | Line 178: OUTPUT_TABLE = "public.price_bars_multi_tf_u"; Line 179: ALIGNMENT_SOURCE = "multi_tf_cal_iso"; 1175 lines |
|  | OUTPUT_TABLE=_u, ALIGNMENT_SOURCE=multi_tf_cal_anchor_us | VERIFIED | Line 175: OUTPUT_TABLE = "public.price_bars_multi_tf_u"; Line 176: ALIGNMENT_SOURCE = "multi_tf_cal_anchor_us"; 957 lines |
|  | OUTPUT_TABLE=_u, ALIGNMENT_SOURCE=multi_tf_cal_anchor_iso | VERIFIED | Line 175: OUTPUT_TABLE = "public.price_bars_multi_tf_u"; Line 176: ALIGNMENT_SOURCE = "multi_tf_cal_anchor_iso"; 957 lines |
|  | Deprecated no-op, exits 0 | VERIFIED | main() prints deprecation notice and returns; 52 lines; zero references in any orchestrator |
|  | Row count parity report | VERIFIED | All 5 alignment_sources MATCH, 12,029,626 total rows, generated 2026-03-20T13:38:26Z |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| refresh_price_bars_multi_tf.py | price_bars_multi_tf_u | OUTPUT_TABLE + _upsert_bars() wrapper | WIRED | _upsert_bars() wrapper passes conflict_cols with alignment_source; both full and incremental paths call it |
| refresh_price_bars_multi_tf_cal_us.py | price_bars_multi_tf_u | OUTPUT_TABLE + 4 direct upsert_bars() calls | WIRED | 4 call sites at lines 341, 564, 609, 648 all include alignment_source in conflict_cols |
| refresh_price_bars_multi_tf_cal_iso.py | price_bars_multi_tf_u | OUTPUT_TABLE + 4 direct upsert_bars() calls | WIRED | 4 call sites all include alignment_source in conflict_cols |
| refresh_price_bars_multi_tf_cal_anchor_us.py | price_bars_multi_tf_u | OUTPUT_TABLE + 2 direct upsert_bars() calls | WIRED | 2 call sites at lines 304, 507 both include alignment_source in conflict_cols |
| refresh_price_bars_multi_tf_cal_anchor_iso.py | price_bars_multi_tf_u | OUTPUT_TABLE + 2 direct upsert_bars() calls | WIRED | 2 call sites both include alignment_source in conflict_cols |
| _load_last_snapshot_info (all 5 builders) | price_bars_multi_tf_u | alignment_source filter in 3 CTEs | WIRED | All 3 CTEs in every builder filter AND alignment_source = :alignment_source |
| delete_bars_for_id_tf (all 5 builders) | price_bars_multi_tf_u | alignment_source=self.ALIGNMENT_SOURCE param | WIRED | Scoped deletes confirmed in all 5 builders; from_1d path uses inline scoped DELETE |
| from_1d derivation path (cal/cal_anchor) | price_bars_multi_tf_u | inline DELETE + upsert_bars() with alignment_source | WIRED | DELETE WHERE id AND alignment_source; bars_pd stamped; conflict_cols include alignment_source |
| run_all_bar_builders.py | sync_price_bars_multi_tf_u | (no reference -- intentional) | WIRED | Zero grep matches confirm sync script is fully decoupled from orchestrator |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| UTB-01 | SATISFIED | All 5 builders write directly to price_bars_multi_tf_u |
| UTB-07 | SATISFIED | State tables bootstrapped; incremental watermark tracking works via alignment_source-filtered snapshot queries |
| UTB-08 | SATISFIED | Row counts verified: 12,029,626 rows, all 5 alignment_sources MATCH (0 deficit) |

### Anti-Patterns Found

No blockers or warnings. No TODO/FIXME/placeholder/stub patterns in any of the 7 key files. The no-op sync script main() body is intentional deprecation (not a stub).

### Human Verification Required

None. All behaviors are fully verifiable by static code analysis combined with the committed 76-row-count-verification.txt artifact.

## Gaps Summary

No gaps. All 9 observable truths verified. Phase goal achieved: the direct-to-_u pattern is fully implemented across all 5 price bar builders, with correct alignment_source stamping, scoped conflict resolution, scoped deletes, alignment-filtered snapshot queries, bootstrapped watermarks, disabled sync intermediary, and confirmed row-count parity.

---

_Verified: 2026-03-20T13:43:43Z_
_Verifier: Claude (gsd-verifier)_
