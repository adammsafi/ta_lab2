---
phase: 32-runbooks
verified: 2026-02-23T00:00:00Z
status: passed
score: 9/9 must-haves verified
---

# Phase 32: Runbooks Verification Report

**Phase Goal:** Write 4 operational runbooks so that any operator can pick up a workflow cold and execute it without reading code. Covers: regime pipeline, backtest pipeline, new-asset onboarding, and disaster recovery. Add runbooks to mkdocs nav under an Operations section.
**Verified:** 2026-02-23
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Operator can run, debug, and recover the regime refresh pipeline using only REGIME_PIPELINE.md | VERIFIED | 384-line file: Quick Start, 12-flag CLI table, 4 regime_inspect modes, 5 SQL queries, 6 troubleshooting subsections, State and Recovery section |
| 2 | Operator can generate signals, run backtests, and interpret results using only BACKTEST_PIPELINE.md | VERIFIED | 429-line file: Quick Start, ASCII flow diagram, 3-signal-type table, 4 SQL queries, metrics threshold table, 5 troubleshooting subsections |
| 3 | Both runbooks include Quick Start with copy-paste commands at the top | VERIFIED | Both files have ## Quick Start as first content section with executable bash blocks |
| 4 | Both runbooks include Prerequisites, Troubleshooting, and Verification sections | VERIFIED | Both have ## Prerequisites, ## Troubleshooting, ## Verification Queries sections |
| 5 | Operator can onboard a new crypto asset end-to-end using only NEW_ASSET_ONBOARDING.md | VERIFIED | 308-line file: 6 numbered steps, ETH (id=2) example throughout, Verify block per step, timing estimates, Removing an Asset section |
| 6 | Operator can restore from backup or rebuild the database from scratch using only DISASTER_RECOVERY.md | VERIFIED | 352-line file: two scenario sections, pg_dump/gunzip commands, 12-step schema creation, recovery time estimates table |
| 7 | The onboarding SOP uses ETH (id=2) as the worked example with verification queries at each step | VERIFIED | ETH/id=2 appears 40+ times; all 6 steps have Verify blocks with SQL or CLI commands |
| 8 | The DR guide covers two scenarios: DB restore from backup and full rebuild from scratch | VERIFIED | Scenario 1 (Restore from Backup) and Scenario 2 (Full Rebuild from Scratch) both present with complete procedures |
| 9 | All 4 new runbooks plus existing operations docs appear in the mkdocs nav under an Operations section | VERIFIED | mkdocs.yml Operations section has 6 entries: DAILY_REFRESH, REGIME_PIPELINE, BACKTEST_PIPELINE, NEW_ASSET_ONBOARDING, DISASTER_RECOVERY, STATE_MANAGEMENT - all plain paths, no anchors |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| docs/operations/REGIME_PIPELINE.md | Regime pipeline runbook containing regime_inspect | VERIFIED | Exists, 384 lines, regime_inspect appears 12 times |
| docs/operations/BACKTEST_PIPELINE.md | Backtest pipeline runbook containing run_backtest_signals | VERIFIED | Exists, 429 lines, run_backtest_signals appears 8 times |
| docs/operations/NEW_ASSET_ONBOARDING.md | New-asset onboarding SOP containing dim_assets | VERIFIED | Exists, 308 lines, dim_assets appears 12 times |
| docs/operations/DISASTER_RECOVERY.md | Disaster recovery guide containing pg_dump | VERIFIED | Exists, 352 lines, pg_dump appears 6 times |
| mkdocs.yml | Updated nav with Operations section | VERIFIED | Operations section present with all 6 nav entries, no anchored paths |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| REGIME_PIPELINE.md | DAILY_REFRESH.md | See Also and Prerequisites cross-reference | VERIFIED | DAILY_REFRESH pattern appears 2 times in the file |
| BACKTEST_PIPELINE.md | REGIME_PIPELINE.md | See Also and Prerequisites cross-reference | VERIFIED | REGIME_PIPELINE pattern appears 2 times in the file |
| mkdocs.yml | REGIME_PIPELINE.md | nav entry | VERIFIED | Regime Pipeline: operations/REGIME_PIPELINE.md present |
| mkdocs.yml | BACKTEST_PIPELINE.md | nav entry | VERIFIED | Backtest Pipeline: operations/BACKTEST_PIPELINE.md present |
| mkdocs.yml | NEW_ASSET_ONBOARDING.md | nav entry | VERIFIED | New Asset Onboarding: operations/NEW_ASSET_ONBOARDING.md present |
| mkdocs.yml | DISASTER_RECOVERY.md | nav entry | VERIFIED | Disaster Recovery: operations/DISASTER_RECOVERY.md present |

### Requirements Coverage

| Requirement | Status | Supporting Evidence |
|-------------|--------|---------------------|
| RUNB-01: Regime pipeline runbook | SATISFIED | docs/operations/REGIME_PIPELINE.md - 384 lines, complete runbook |
| RUNB-02: Backtest pipeline runbook | SATISFIED | docs/operations/BACKTEST_PIPELINE.md - 429 lines, complete runbook |
| RUNB-03: New-asset onboarding SOP | SATISFIED | docs/operations/NEW_ASSET_ONBOARDING.md - 308 lines, 6-step walkthrough with ETH (id=2) |
| RUNB-04: Disaster recovery guide | SATISFIED | docs/operations/DISASTER_RECOVERY.md - 352 lines, two scenarios with 12-step schema rebuild |

### Anti-Patterns Found

None. No stub patterns, placeholders, TODOs, FIXMEs, or coming-soon text found in any of the 4 runbooks.

### Detailed Content Verification

**REGIME_PIPELINE.md (384 lines):**
- Quick Start: 4 copy-paste commands (full pipeline, regimes-only, single asset, inspect)
- Prerequisites: 4 conditions (DB up, bars fresh, EMAs fresh, dim_assets populated)
- Entry Points: orchestrator and direct script sections; flags table with all 12 flags
  (--ids, --all, --cal-scheme, --policy-file, --dry-run, -v/--verbose, --db-url, --min-bars-l0/l1/l2, --no-hysteresis, --min-hold-bars)
- Execution Flow: 10 numbered steps (load bars+EMAs, assess data budget, label layers, proxy fallback,
  forward-fill, resolve policy with hysteresis, detect flips, compute stats, compute comovement, write to DB)
- Regime Tables: 4-table reference with key columns (cmc_regimes, cmc_regime_flips, cmc_regime_stats, cmc_regime_comovement)
- Debugging: 4 regime_inspect modes (default, --history, --flips, --live) with example commands
- Verification Queries: 5 SQL queries (freshness, regime distribution, recent flips, version hash consistency, asset count)
- Troubleshooting: 6 named failure modes with error messages in code blocks and fixes
- State and Recovery: full-recompute explanation, manual DELETE queries, A/B testing with --no-regime

**BACKTEST_PIPELINE.md (429 lines):**
- Quick Start: 3 copy-paste command blocks (generate signals, run backtest, validate-only)
- Prerequisites: 5 conditions (DB, cmc_features, cmc_ema_multi_tf_u, dim_signals, optional regimes)
- Pipeline Overview: ASCII flow diagram showing cmc_features + cmc_ema_multi_tf_u to backtest tables
- Signal Generation: all orchestrator flags, individual signal scripts, 3-entry signal types table, feature sources per signal type
- Running Backtests: 3 modes (clean/reproducibility, realistic with fees, JSON output), complete flags table
- Result Tables: 3 tables (runs, trades, metrics) with key columns
- Querying Results: 4 SQL queries (latest runs, full metrics join, trades for a run, signal counts sanity check)
- Interpreting Metrics: 7-metric threshold table with good/concerning thresholds
- Reproducibility Validation: strict/non-strict modes, manual invocation, feature_hash explanation
- Troubleshooting: 5 named failure modes with error messages and fixes

**NEW_ASSET_ONBOARDING.md (308 lines):**
- Quick Start: 6 ordered commands matching the 6 steps
- Prerequisites: 4 conditions with fallback URL chain
- 6 numbered steps each with: description, exact command, Verify block with SQL or CLI, timing estimate
- ETH (id=2) is the consistent worked example throughout (40+ mentions)
- Total Time table: 18-43 min
- Removing an Asset: FK-aware DELETE order with source data and registry deletes commented out

**DISASTER_RECOVERY.md (352 lines):**
- Overview: two-scenario scope; notes no automated backup exists yet
- Prerequisites: TARGET_DB_URL fallback chain, Python env, PostgreSQL client tools
- Scenario 1: pg_dump backup with gzip, gunzip pipe restore, 5-table COUNT verification,
  incremental catch-up run, alembic stamp head note
- Scenario 2 Phase A: exactly 12 numbered psql DDL steps in dependency order
- Scenario 2 Phase B: per-asset source ingest pattern using upsert_cmc_history
- Scenario 2 Phase C: derived data rebuild in order (bars to EMAs to features to regimes to signals)
- Scenario 2 Phase D: UNION ALL verification query with expected row counts
- Recovery Time Estimates: 8-row table with estimates and notes
- SQL File Reference: annotated directory tree for sql/

**mkdocs.yml Operations section:**
- Inserted between Components and Deployment
- All 6 entries use plain page paths with no anchors (compliant with Phase 31-03 decision)
- Cross-link targets DAILY_REFRESH.md and STATE_MANAGEMENT.md both exist on disk

---

_Verified: 2026-02-23_
_Verifier: Claude (gsd-verifier)_
