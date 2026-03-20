---
phase: 75-generalized-1d-bar-builder
verified: 2026-03-20T12:16:49Z
status: passed
score: 13/13 must-haves verified
re_verification: false
---

# Phase 75: Generalized 1D Bar Builder Verification Report

**Phase Goal:** A single 1D bar builder script handles all data sources via CLI flag, old source-specific scripts deleted
**Verified:** 2026-03-20T12:16:49Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running --source cmc builds 1D bars from CMC with OHLC repair | VERIFIED | choices=[cmc,tvc,hl,all] at L885; ohlc_repair branch build_bars_for_id L743-L758 |
| 2 | Running --source tvc builds 1D bars from tvc_price_histories | VERIFIED | custom_args source:tvc in orchestrator L66; TVC CTE fix in _add_venue_id_to_tvc_template |
| 3 | Running --source hl builds 1D bars via dim_asset_identifiers | VERIFIED | custom_args source:hl in orchestrator L74; HL JOIN path in _check_for_backfill_generic L515-L521 |
| 4 | Backfill detection works for all three sources via ts_column | VERIFIED | _check_for_backfill_generic at L497-L538; uses spec ts_column from dim_data_sources |
| 5 | Incremental run after state migration avoids spurious full rebuilds | VERIFIED | _migrate_state_table_pk L292-L422; ON CONFLICT (id, venue_id, tf) DO NOTHING for non-CMC rows |
| 6 | TVC and HL sources auto-sync 1D bars to price_bars_multi_tf | VERIFIED | _sync_1d_to_multi_tf at L987 gated by if sk \!= cmc; upsert SQL at L588-L601 |
| 7 | CTE templates get venue_id fix for NOT NULL constraint | VERIFIED | _preflight_fix_cte_templates L167-L213; idempotent; CMC adds 1::smallint, TVC adds 11::smallint |
| 8 | run_all_bar_builders.py invokes generic builder with source flag | VERIFIED | ALL_BUILDERS has 1d_cmc, 1d_tvc, 1d_hl all pointing to refresh_price_bars_1d.py; --source passed at L205 |
| 9 | Old TVC/HL scripts deleted | VERIFIED DELETED | Not in filesystem; git confirms deletion commit 263745a6 |
| 10 | --builders 1d_cmc, 1d_tvc, 1d_hl all work from orchestrator | VERIFIED | BUILDER_NAME_MAP built from ALL_BUILDERS; all three names at L53-L75 |
| 11 | run_daily_refresh.py skip flags use 1d_cmc not stale 1d | VERIFIED | Lines 147/149/151 use 1d_tvc,1d_hl and 1d_cmc,1d_hl and 1d_cmc,1d_tvc -- no bare 1d |
| 12 | _load_source_spec is defined and called | VERIFIED | Defined at L221; called at L944 inside main() |
| 13 | psycopg_helpers symbols connect/execute/fetchone/fetchall exported | VERIFIED | All 4 defined in psycopg_helpers.py L68/L80/L92/L108; imported at refresh_price_bars_1d.py L49 |

**Score:** 13/13 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/ta_lab2/scripts/bars/refresh_price_bars_1d.py | Generalized 1D builder with --source CLI | VERIFIED | 993 lines, substantive, exports main(), no stubs |
| src/ta_lab2/scripts/bars/run_all_bar_builders.py | Updated orchestrator with generic 1D entries | VERIFIED | 532 lines, ALL_BUILDERS has 1d_cmc/1d_tvc/1d_hl, custom_args field present |
| src/ta_lab2/scripts/run_daily_refresh.py | Daily refresh with 1d_cmc builder name | VERIFIED | Uses 1d_cmc/1d_tvc/1d_hl in --skip args, no stale 1d references |
| src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py | MUST NOT EXIST | VERIFIED DELETED | Not in filesystem; git confirms deletion 263745a6 |
| src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py | MUST NOT EXIST | VERIFIED DELETED | Not in filesystem; git confirms deletion 263745a6 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| refresh_price_bars_1d.py | dim_data_sources | SQL SELECT by source_key | WIRED | fetchone SELECT FROM dim_data_sources WHERE source_key at L234-L247 |
| refresh_price_bars_1d.py | ta_lab2.db.psycopg_helpers | import connect/execute/fetchone/fetchall | WIRED | Line 49; all 4 symbols defined in psycopg_helpers.py |
| run_all_bar_builders.py | refresh_price_bars_1d.py | BuilderConfig entries with custom_args source | WIRED | L54/62/70 all reference refresh_price_bars_1d.py; --source passed at L205 |
| run_daily_refresh.py | run_all_bar_builders.py | --skip flag with 1d_cmc builder name | WIRED | Lines 147/149/151 reference 1d_cmc/1d_tvc/1d_hl correctly |
| _sync_1d_to_multi_tf | price_bars_multi_tf | INSERT ON CONFLICT from price_bars_1d | WIRED | Called at L987 for non-CMC sources; SQL at L587-L601 |
| _check_for_backfill_generic | dim_asset_identifiers | JOIN for HL source | WIRED | L515-L521 uses JOIN dim_asset_identifiers dai ON dai.id_type = HL |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| BAR-01: Single script handles --source cmc/tvc/hl/all | SATISFIED | choices=[cmc,tvc,hl,all] at L885; main() loops over source_keys |
| BAR-03: New source = new dim_data_sources row only | SATISFIED | _load_source_spec/_resolve_sources fully driven by dim_data_sources; no hardcoded source list |
| BAR-04: Backfill detection for all sources | SATISFIED | _check_for_backfill_generic uses spec[ts_column] and spec[join_clause] for all three sources |
| BAR-06: Orchestrator updated with --source flag | SATISFIED | run_all_bar_builders.py has 1d_cmc/1d_tvc/1d_hl; build_command passes --source |
| BAR-07: Old scripts deleted | SATISFIED | Both scripts absent from filesystem |
| BAR-08: Row counts match baseline | UNCERTAIN - NEEDS HUMAN | Code structure correct; actual parity requires live DB run |

### Anti-Patterns Found

| File | Pattern | Severity | Assessment |
|------|---------|----------|------------|
| refresh_price_bars_1d.py L908-L914 | raise NotImplementedError in from_cli_args | Info | Intentional -- documented in docstring; main() is correct entry point |

No blockers or warnings found.

### Human Verification Required

#### 1. Row Count Parity -- CMC Source

**Test:** Run python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source cmc --ids all on a dev/staging database.
**Expected:** Row counts match baseline exactly (same assets, same date range)
**Why human:** Requires live database with dim_data_sources populated and CTE templates loaded

#### 2. Row Count Parity -- TVC Source

**Test:** Run python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source tvc --ids all.
**Expected:** Row counts match old TVC builder baseline
**Why human:** Requires live database run

#### 3. HL Row Count >= Baseline

**Test:** Run python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source hl --ids all.
**Expected:** Row count >= old HL baseline (scope expanded from HL_YN.csv to all HL assets in dim_asset_identifiers)
**Why human:** Requires live database with hl_candles and dim_asset_identifiers populated

#### 4. Pre-flight venue_id Fix Idempotence

**Test:** Run the builder twice on a fresh database.
**Expected:** First run logs Pre-flight: Fixed CMC/TVC CTE template. Second run logs Pre-flight: already has venue_id -- skipping.
**Why human:** Requires live database to observe log output

#### 5. --source all Processes All Three Sources

**Test:** Run python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source all --ids 1.
**Expected:** Log shows building source: cmc, building source: hl, building source: tvc
**Why human:** Requires live database run

---

## Gaps Summary

No gaps identified. All 13 must-haves verified against actual codebase.

- src/ta_lab2/scripts/bars/refresh_price_bars_1d.py is a substantive 993-line implementation with all required features.
- src/ta_lab2/scripts/bars/run_all_bar_builders.py has three BuilderConfig entries (1d_cmc, 1d_tvc, 1d_hl) pointing to the same generic script.
- src/ta_lab2/scripts/run_daily_refresh.py uses new builder names in --skip flags. No stale 1d references.
- Both old source-specific scripts confirmed deleted from filesystem and git (commit 263745a6).
- No references to deleted scripts remain in source code (only in planning documentation).

The 5 human verification items are about actual data correctness (row counts, DB behavior) that cannot be verified without a live database run. The code structure correctly supports all required behaviors.

---

_Verified: 2026-03-20T12:16:49Z_
_Verifier: Claude (gsd-verifier)_
