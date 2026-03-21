---
phase: 77-direct-to-u-remaining-families
verified: 2026-03-20T12:00:00Z
status: passed
score: 9/9 truths verified across 5 families
---

# Phase 77: Direct-to-_u Remaining Families - Verification Report

**Phase Goal:** Redirect all 5 remaining table families to write directly to their _u tables with alignment_source, disable all sync scripts, and verify row count parity.
**Verified:** 2026-03-20
**Status:** passed

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | All 5 bar returns builders write to returns_bars_multi_tf_u | VERIFIED | DEFAULT_OUT_TABLE = public.returns_bars_multi_tf_u + ALIGNMENT_SOURCE in all 5 scripts |
| 2 | EMA builders write to ema_multi_tf_u; alignment_source stamped BEFORE write; in PK | VERIFIED | base_ema_feature.py stamps at line 283 BEFORE to_sql; _get_pk_columns appends at line 344 |
| 3 | EMA returns read ema_multi_tf_u scoped; write returns_ema_multi_tf_u | VERIFIED | DEFAULT_EMA_TABLE = public.ema_multi_tf_u; DEFAULT_OUT_TABLE = public.returns_ema_multi_tf_u |
| 4 | AMA builders write ama_multi_tf_u; DELETE scoped; DataFrame stamped before write | VERIFIED | base_ama_feature.py stamps at line 403 BEFORE DELETE+INSERT; DELETE scoped at lines 433-447 |
| 5 | AMA returns TABLE_MAP 4-tuples; reads ama_multi_tf_u; writes returns_ama_multi_tf_u | VERIFIED | TABLE_MAP 4-tuple type; all 5 entries verified; 4-tuple unpack at line 536 |
| 6 | All 5 sync scripts are DEPRECATED no-ops | VERIFIED | All 5 scripts contain DEPRECATED in docstring; no ta_lab2 imports |
| 7 | Row count parity verified for all 5 families | VERIFIED | 5 verification files; all 5 alignment_sources MATCH per family |
| 8 | EMAStateManager scopes state queries by alignment_source | VERIFIED | update_state_from_output() has optional alignment_source param; WHERE filter in both private methods |
| 9 | Zero remaining 3-tuple unpacking in refresh_returns_ama.py | VERIFIED | grep for old pattern returns 0 matches |

**Score:** 9/9 truths verified

---

## Artifact Verification

### Plan 77-01: Bar Returns

All 5 builders verified: DEFAULT_OUT_TABLE = public.returns_bars_multi_tf_u, ALIGNMENT_SOURCE correct per-builder, alignment_source in INSERT_COLS + ON CONFLICT + DELETE scope + execute params. All pass ast.parse().
- refresh_returns_bars_multi_tf.py -> ALIGNMENT_SOURCE = multi_tf
- refresh_returns_bars_multi_tf_cal_us.py -> ALIGNMENT_SOURCE = multi_tf_cal_us
- refresh_returns_bars_multi_tf_cal_iso.py -> ALIGNMENT_SOURCE = multi_tf_cal_iso
- refresh_returns_bars_multi_tf_cal_anchor_us.py -> ALIGNMENT_SOURCE = multi_tf_cal_anchor_us
- refresh_returns_bars_multi_tf_cal_anchor_iso.py -> ALIGNMENT_SOURCE = multi_tf_cal_anchor_iso
sync_returns_bars_multi_tf_u.py: DEPRECATED (warnings.warn + print; no ta_lab2 imports)
77-01-row-count-verification.txt: 12,019,640 total rows; all 5 MATCH

### Plan 77-02: EMA Values

base_ema_feature.py: alignment_source in EMAFeatureConfig (line 55); stamp at line 283 BEFORE to_sql at line 285; _get_pk_columns appends at line 344.
refresh_ema_multi_tf_from_bars.py: default ema_multi_tf_u at line 74; alignment_source multi_tf via extra_config.
refresh_ema_multi_tf_cal_from_bars.py: --out-us/--out-iso default ema_multi_tf_u; alignment_source derived per scheme at line 323.
refresh_ema_multi_tf_cal_anchor_from_bars.py: same pattern; alignment_source derived at line 309.
ema_state_manager.py: alignment_source param at line 215; WHERE filter in both private update methods.
base_ema_refresher.py: passes alignment_source at lines 1065-1070 and 1135-1140.
sync_ema_multi_tf_u.py: DEPRECATED (sys.exit(0))
77-02-row-count-verification.txt: 55,796,615 total rows; all 5 MATCH (2 iso sources backfilled at migration time)

### Plan 77-03: EMA Returns

refresh_returns_ema_multi_tf.py: DEFAULT_EMA_TABLE = public.ema_multi_tf_u; DEFAULT_OUT_TABLE = public.returns_ema_multi_tf_u; ALIGNMENT_SOURCE = multi_tf; source WHERE scoped at line 190.
refresh_returns_ema_multi_tf_cal.py: ALIGNMENT_SOURCE_US = multi_tf_cal_us; ALIGNMENT_SOURCE_ISO = multi_tf_cal_iso; source scoped at lines 224/236.
refresh_returns_ema_multi_tf_cal_anchor.py: ALIGNMENT_SOURCE_US = multi_tf_cal_anchor_us; ALIGNMENT_SOURCE_ISO = multi_tf_cal_anchor_iso.
sync_returns_ema_multi_tf_u.py: DEPRECATED (sys.exit(0))
77-03-row-count-verification.txt: 48,830,818 total rows; all 5 MATCH

### Plan 77-04: AMA Values

base_ama_feature.py: alignment_source in AMAFeatureConfig (line 64); stamp at line 403 BEFORE DELETE+INSERT; DELETE scoped at lines 433-447; _get_pk_columns appends at lines 533-534.
refresh_ama_multi_tf.py: get_default_output_table() = ama_multi_tf_u; get_alignment_source() = multi_tf.
refresh_ama_multi_tf_cal_from_bars.py: SCHEME_CONFIG uses output_table=ama_multi_tf_u and alignment_source per scheme.
refresh_ama_multi_tf_cal_anchor_from_bars.py: same pattern for anchor schemes.
base_ama_refresher.py: alignment_source on AMAWorkerTask at line 92; passed to AMAFeatureConfig at line 128.
ama_state_manager.py: no update_state_from_output -- state saved directly; no alignment_source scoping needed.
sync_ama_multi_tf_u.py: DEPRECATED (sys.exit(0))
77-04-row-count-verification.txt: 170,447,220 total rows; all 5 MATCH

### Plan 77-05: AMA Returns

refresh_returns_ama.py: TABLE_MAP dict with 4-tuple values at line 60; all 5 entries use ama_multi_tf_u source and returns_ama_multi_tf_u output; ON CONFLICT includes alignment_source at line 150; source WHERE scoped at lines 244/249/255/259; 4-tuple unpack at line 536; zero remaining 3-tuple patterns.
sync_returns_ama_multi_tf_u.py: DEPRECATED (sys.exit(0))
77-05-row-count-verification.txt: 113,125,842 total rows; all 5 MATCH

---

## Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| refresh_returns_bars_multi_tf.py | returns_bars_multi_tf_u | DEFAULT_OUT_TABLE constant (line 45) | WIRED |
| base_ema_feature write_to_db | ema_multi_tf_u | alignment_source stamp at line 283 BEFORE to_sql at line 285 | WIRED |
| base_ema_feature _get_pk_columns | _pg_upsert ON CONFLICT | cols.append(alignment_source) at line 344 | WIRED |
| ema_state_manager update_state_from_output | ema_multi_tf_u | WHERE alignment_source filter in both private methods | WIRED |
| base_ema_refresher | ema_state_manager | passes alignment_source at lines 1065-1070 and 1135-1140 | WIRED |
| refresh_returns_ema_multi_tf | ema_multi_tf_u source | AND alignment_source in source CTE WHERE (line 190) | WIRED |
| base_ama_feature write_to_db | ama_multi_tf_u | stamp at line 403; scoped DELETE at lines 433-447 | WIRED |
| refresh_returns_ama TABLE_MAP | ama_multi_tf_u source | AND alignment_source in where_clause (lines 244/249/255/259) | WIRED |
| refresh_returns_ama main | TABLE_MAP 4-tuple | 4-tuple unpack at line 536; zero 3-tuple patterns remain | WIRED |

---

## Syntax Verification

All 25 modified Python files pass ast.parse() without errors.

---

## Row Count Parity Summary

| Family | Total _u rows | Status | Notes |
|--------|--------------|--------|-------|
| Bar Returns (77-01) | 12,019,640 | MATCH | All 5 exact |
| EMA Values (77-02) | 55,796,615 | MATCH | Backfill for 2 iso sources at migration time |
| EMA Returns (77-03) | 48,830,818 | MATCH | All 5 exact |
| AMA Values (77-04) | 170,447,220 | MATCH | All 5 exact |
| AMA Returns (77-05) | 113,125,842 | MATCH | All 5 exact |

---

## Anti-Patterns Scan

No blockers found. Bar returns sync uses warnings.warn instead of sys.exit(0) -- minor deviation; still a functional no-op.
No TODO/FIXME/placeholder in alignment_source-stamping or write-path code.

---

## Human Verification Required

None. All critical behaviors verifiable via static code analysis.

---

## Summary

Phase 77 goal achieved. All 5 remaining table families write directly to their _u unified tables with alignment_source. Every must-have from all 5 plans is satisfied.

77-01 (Bar Returns): 5 builders redirect to returns_bars_multi_tf_u. alignment_source in INSERT_COLS, ON CONFLICT, execute params, DELETE scope. 12,019,640 rows, all 5 MATCH.

77-02 (EMA Values): BaseEMAFeature stamps alignment_source BEFORE to_sql. _get_pk_columns appends alignment_source. EMAStateManager scopes state queries. 55,796,615 rows, all 5 MATCH.

77-03 (EMA Returns): All 3 builders read ema_multi_tf_u scoped by alignment_source; write returns_ema_multi_tf_u. Source WHERE prevents cross-source LAG contamination. 48,830,818 rows, all 5 MATCH.

77-04 (AMA Values): BaseAMAFeature stamps BEFORE DELETE+INSERT. DELETE scoped. AMA state manager uses direct save_state. 170,447,220 rows, all 5 MATCH.

77-05 (AMA Returns): TABLE_MAP from 3-tuples to 4-tuples. Zero old unpack patterns. All 5 use ama_multi_tf_u source and returns_ama_multi_tf_u output. 113,125,842 rows, all 5 MATCH.

All 5 sync scripts disabled as DEPRECATED no-ops.

---

_Verified: 2026-03-20_
_Verifier: Claude (gsd-verifier)_
