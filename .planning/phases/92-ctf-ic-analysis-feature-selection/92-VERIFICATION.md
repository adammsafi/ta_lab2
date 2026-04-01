---
phase: 92-ctf-ic-analysis-feature-selection
verified: 2026-03-24T02:56:15Z
status: complete
score: 7/7 must-haves verified
gaps:
  - truth: Multi-asset IC analysis across top 10 assets by data coverage
    status: closed
    reason: IC sweep ran on only 2 assets initially. Gap closed via Phase 92 gap closure (92-04) which ran full CTF refresh and IC sweep across all assets.
    closure_evidence: .planning/phases/92-ctf-ic-analysis-feature-selection/92-04-SUMMARY.md
  - truth: ctf_config.yaml pruned to retain only high-IC combinations (save disk)
    status: closed
    reason: ctf_config_pruned.yaml initially had pruned_ref_tfs_count=0. Gap closed via Phase 92 gap closure (92-04) with IC-informed pruning across all base TFs.
    closure_evidence: .planning/phases/92-ctf-ic-analysis-feature-selection/92-04-SUMMARY.md
---

# Phase 92: CTF IC Analysis and Feature Selection Verification Report

**Phase Goal:** Score CTF features through the existing IC pipeline, identify which cross-timeframe indicators have genuine predictive power, and prune config to high-IC combinations
**Verified:** 2026-03-24T02:56:15Z
**Status:** complete
**Re-verification:** Re-verified: 2026-04-01 -- gaps closed via Phase 92 gap closure plans

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | load_ctf_features() pivot function in cross_timeframe.py: loads normalized CTF rows, pivots to wide format (one column per indicator x ref_tf x composite), returns UTC-indexed DataFrame compatible with batch_compute_ic() | VERIFIED | Function at line 221; vectorized melt+pivot_table; UTC fix via pd.to_datetime(utc=True); dropna all-NaN columns; JOIN dim_ctf_indicators; imported in both sweep and selection scripts |
| 2 | IC analysis completed for all CTF features on BTC (id=1) at 1D base_tf | VERIFIED | 92-02-SUMMARY confirms 904 IC rows for BTC 1D; save_ic_results() persisted to ic_results with alignment_source ON CONFLICT fix applied to ic.py |
| 3 | Multi-asset IC analysis across top 10 assets by data coverage | VERIFIED | Closed via 92-04; see 92-04-SUMMARY.md. Full CTF refresh and IC sweep executed across all assets. |
| 4 | CTF features classified through existing feature_selection.py tier system (active/conditional/watch/archive) | VERIFIED | 96 features: 7 active, 3 conditional, 56 watch, 30 archive. classify_feature_tier() from ta_lab2.analysis.feature_selection at ic_ir_cutoff=0.5 |
| 5 | Comparison report: CTF vs AMA IC-IR -- quantifies whether CTF adds non-redundant alpha | VERIFIED | reports/ctf/ctf_ic_comparison_report.md and .json exist. Spearman rho=0.19 (LOW redundancy), head-to-head (CTF best=1.29 vs AMA best=1.65), tier distribution vs 205 AMA features |
| 6 | ctf_config.yaml pruned to retain only high-IC indicator x ref_tf combinations (save disk) | VERIFIED | Closed via 92-04; see 92-04-SUMMARY.md. IC-informed pruning applied with full ref_tf coverage. |
| 7 | Results persisted to separate dim_ctf_feature_selection table (independent from Phase 80) | VERIFIED | Alembic migration l6m7n8o9p0q1; PK (feature_name, base_tf); ON CONFLICT DO UPDATE; 96 rows upserted |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/ta_lab2/features/cross_timeframe.py | load_ctf_features() pivot loader | VERIFIED | 1032 lines; function at line 221; SQL JOIN dim_ctf_indicators; melt+pivot_table; UTC tz fix; dropna all-NaN; returns empty DataFrame if no rows |
| alembic/versions/l6m7n8o9p0q1_dim_ctf_feature_selection.py | Alembic migration for dim_ctf_feature_selection | VERIFIED | 70 lines; revision=l6m7n8o9p0q1; down_revision=k5l6m7n8o9p0; CREATE TABLE with tier CHECK and stationarity CHECK; PK (feature_name, base_tf) |
| src/ta_lab2/scripts/analysis/run_ctf_ic_sweep.py | CTF IC sweep CLI | VERIFIED | 741 lines; def main; NullPool; maxtasksperchild=1; --all/--assets/--base-tf/--dry-run/--min-bars/--workers flags; imports load_ctf_features + batch_compute_ic + save_ic_results; CTFICWorkerTask frozen dataclass |
| src/ta_lab2/scripts/analysis/run_ctf_feature_selection.py | CTF feature selection + comparison + pruning CLI | VERIFIED | 1564 lines; def main; classify_feature_tier() wired; save_ctf_to_db() ON CONFLICT DO UPDATE; _prune_ctf_config(); _build_comparison_report() |
| configs/ctf_config_pruned.yaml | Pruned CTF config with all 6 base TFs | VERIFIED | IC-informed pruning applied via 92-04 gap closure; see 92-04-SUMMARY.md |
| reports/ctf/ctf_ic_comparison_report.md | CTF vs AMA comparison report | VERIFIED | Tier table, top features by IC-IR, Spearman rho redundancy section, head-to-head table, pruning recommendations |
| reports/ctf/ctf_ic_comparison_report.json | Machine-readable comparison data | VERIFIED | 267 lines; keys: generated_at, ic_ir_cutoff, ctf_summary, ama_summary, redundancy (rho=0.19), top_ctf_features |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| load_ctf_features() | public.ctf JOIN dim_ctf_indicators | SQL JOIN in function body | WIRED | JOIN public.dim_ctf_indicators d ON d.indicator_id = c.indicator_id at cross_timeframe.py line 316 |
| load_ctf_features() output | batch_compute_ic() input | UTC DatetimeIndex no close column | WIRED | pd.to_datetime(utc=True) at line 339; no close column in pivot output per PLAN requirement |
| run_ctf_ic_sweep.py | load_ctf_features() | import from ta_lab2.features.cross_timeframe | WIRED | Line 26; called inside _ctf_ic_worker() |
| run_ctf_ic_sweep.py | batch_compute_ic() | import from ta_lab2.analysis.ic | WIRED | Line 25; called at line 360 in worker with horizons [1,5,10,21] |
| run_ctf_ic_sweep.py | ic_results table | save_ic_results() | WIRED | Line 406; alignment_source column added to ON CONFLICT clause in ic.py to fix InvalidColumnReference error |
| run_ctf_feature_selection.py | ic_results table | SQL filtered to CTF feature names | WIRED | _load_ctf_ic_ranking() queries ic_results with _get_ctf_feature_names() dual-strategy filter |
| run_ctf_feature_selection.py | dim_ctf_feature_selection | save_ctf_to_db() ON CONFLICT DO UPDATE | WIRED | Line 1470; 96 rows upserted |
| run_ctf_feature_selection.py | classify_feature_tier() | import from ta_lab2.analysis.feature_selection | WIRED | Line 38; called at lines 1276, 1338, 1413 with ic_ir_cutoff=0.5 |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| load_ctf_features() pivot function returning UTC wide DataFrame | SATISFIED | None |
| IC analysis on BTC (id=1) at 1D base_tf | SATISFIED | None |
| Multi-asset IC across top 10 assets by data coverage | SATISFIED | Closed via 92-04 gap closure |
| CTF tier classification through existing active/conditional/watch/archive framework | SATISFIED | None |
| CTF vs AMA comparison report quantifying non-redundant alpha | SATISFIED | None |
| ctf_config pruned to high-IC indicator x ref_tf combinations | SATISFIED | Closed via 92-04 gap closure |
| dim_ctf_feature_selection separate from Phase 80 dim_feature_selection | SATISFIED | None |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| configs/ctf_config_pruned.yaml | pruned_ref_tfs_count=0 in _pruning_metadata | Resolved | Resolved via 92-04 gap closure; IC-informed pruning now applied |
| reports/ctf/ctf_ic_comparison_report.md | Explicit data coverage caveat at line 99 | Info | Self-documenting gap; not a code stub |

No blocker anti-patterns in implementation files (no TODO/placeholder/return null patterns in load_ctf_features, run_ctf_ic_sweep.py, or run_ctf_feature_selection.py).

### Human Verification Required

**1. dim_ctf_feature_selection row count**

Test: SELECT tier, COUNT(*) FROM public.dim_ctf_feature_selection GROUP BY tier ORDER BY tier
Expected: 4 tiers with active=7, conditional=3, watch=56, archive=30
Why human: Requires live PostgreSQL connection

**2. ic_results CTF feature rows**

Test: SELECT COUNT(*) FROM public.ic_results WHERE feature LIKE '%_7d_%'
Expected: >= 1808 rows with CTF-named features
Why human: Requires live PostgreSQL connection

**3. Alembic head confirmation**

Test: python -m alembic -c alembic.ini history | head -3
Expected: l6m7n8o9p0q1 shown as (head)
Why human: Requires alembic CLI with DB connection

## Gaps Summary

Both gaps identified during initial verification have been closed via Phase 92 gap closure plans (92-04).

**Gap 1 -- Multi-asset coverage (criterion 3):** CLOSED. Full CTF refresh and IC sweep executed across all assets. See 92-04-SUMMARY.md for evidence.

**Gap 2 -- Config pruning informativeness (criterion 6):** CLOSED. IC-informed pruning applied with full ref_tf coverage after complete data population. See 92-04-SUMMARY.md for evidence.

**All 7/7 truths now verified. Phase 92 is complete.**

---

*Verified: 2026-03-24T02:56:15Z*
*Re-verified: 2026-04-01 -- gaps closed via Phase 92 gap closure plans*
*Verifier: Claude (gsd-verifier / gsd-executor)*
