---
phase: 21-comprehensive-review
plan: 04
subsystem: documentation
status: complete
tags: [onboarding, gap-analysis, asset-management, validation, severity-tiers]

requires:
  - 21-01-script-inventory
  - 21-02-data-flow-diagram
  - 21-03-ema-analysis

provides:
  - new-asset-onboarding-guide
  - severity-tiered-gap-analysis

affects:
  - phase-22-critical-fixes
  - phase-23-operations
  - phase-24-pattern-consistency

tech-stack:
  added: []
  patterns: [evidence-based-gap-analysis, severity-tiers, effort-estimation]

key-files:
  created:
    - .planning/phases/21-comprehensive-review/findings/new-asset-guide.md
    - .planning/phases/21-comprehensive-review/deliverables/gap-analysis.md
  modified: []

decisions:
  - gap-severity-framework: "CRITICAL (data corruption), HIGH (error-prone), MEDIUM (workarounds), LOW (nice-to-have)"
  - phase-22-focus: "4 CRITICAL + 1 HIGH gap (44-63h) - reject tables, EMA validation, 1D backfill, test suite"
  - phase-23-focus: "4 HIGH + 2 MEDIUM gaps (30-43h) - add_asset.py, onboard_asset.py, recovery.py, summary logging"
  - phase-24-focus: "2 MEDIUM gaps (21-31h) - BaseBarBuilder template, calendar tz documentation"

metrics:
  duration: 6.9 minutes
  completed: 2026-02-05
---

# Phase 21 Plan 04: New Asset Guide & Gap Analysis Summary

**One-liner:** End-to-end asset onboarding checklist (6 steps, 15-40 min) + severity-tiered gap analysis (15 gaps, 95-137h remediation)

## What Was Built

### RVWQ-04: How do I add a new asset?

Created `findings/new-asset-guide.md` answering the critical onboarding question with:

**End-to-end 6-step checklist:**
1. Add to dim_assets (manual SQL INSERT with cmc_id, symbol, name)
2. Build 1D bars (refresh_cmc_price_bars_1d.py, 2-5 min)
3. Build multi-TF bars (refresh_cmc_price_bars_multi_tf.py, 3-10 min)
4. Compute EMAs (refresh_cmc_ema_multi_tf_from_bars.py, 5-15 min)
5. Validate output (SQL queries: bar counts, EMA coverage, state completeness)
6. Verify incremental refresh (re-run scripts, confirm minimal new rows)

**Key asset mechanics documented:**
- Asset ID flow: CMC ID → dim_assets.id → all bar/EMA tables
- Script selection: tf_day vs calendar (US/ISO) vs calendar_anchor variants
- Verification queries: Compare to reference asset (Bitcoin id=1)
- Troubleshooting: No bars (wrong ID), high rejects (source data quality), sparse EMAs (insufficient history)

**Cross-references to Wave 1:**
- Script execution order: data-flow-diagram.md L1 System Overview
- Validation checks: validation-points.md sections 1-4
- State management: incremental-refresh.md (watermarks, backfill detection)
- Variant selection: ema-variants.md (tf_day vs calendar semantics)

**Automation opportunities identified:**
- add_asset.py: dim_assets insert + CMC API validation (6-8h)
- onboard_asset.py: Orchestrate Steps 2-4 with error handling (8-12h)
- Validation test suite: Automated checks instead of manual queries (4-6h)

**Total onboarding time:** 15-40 minutes per asset (scales with history depth)

---

### RVWD-04: Gap Analysis with Severity Tiers

Created `deliverables/gap-analysis.md` using evidence-based gap identification:

**15 gaps cataloged:**
- 4 CRITICAL: Multi-TF reject tables (C01), EMA output validation (C02), 1D backfill detection (C03), automated test suite (C04)
- 5 HIGH: Manual dim_assets (H01), no orchestration (H02), state schema undocumented (H03), no error recovery (H04), no observability (H05)
- 4 MEDIUM: BaseBarBuilder missing (M01), populate_dim_assets script (M02), calendar tz column (M03), gap-fill strategy (M04)
- 2 LOW: Six EMA state tables (L01), no bar_metadata table (L02)

**Severity framework established:**
- **CRITICAL:** Blocks data quality or causes silent corruption (reject visibility, validation blind spots)
- **HIGH:** Makes onboarding error-prone or requires manual intervention (dim_assets, orchestration, recovery)
- **MEDIUM:** Code duplication or missing documentation (BaseBarBuilder, gap-fill policy)
- **LOW:** Nice-to-have optimizations (unified state table, metadata caching)

**Evidence standard:** Every gap cites source document + line numbers
- C01: validation-points.md lines 76-77 (Multi-TF has no rejects table)
- C02: validation-points.md lines 463-464 (No EMA output validation)
- C03: incremental-refresh.md lines 173-177 (1D has no backfill detection)
- C04: validation-points.md lines 523-597 (Manual testing only)
- H01: new-asset-guide.md lines 27-68 (Manual SQL INSERT for dim_assets)
- (All 15 gaps similarly sourced)

**Phase prioritization:**
- **Phase 22 (Q1 2026):** 4 CRITICAL + 1 HIGH gap = 44-63 hours → Data quality fixes
- **Phase 23 (Q1-Q2 2026):** 4 HIGH + 2 MEDIUM gaps = 30-43 hours → Operational automation
- **Phase 24 (Q2 2026):** 2 MEDIUM + 2 LOW gaps = 21-31 hours → Code quality/pattern consistency

**Total remediation effort:** 95-137 hours (3-4 weeks full-time)

**Key findings:**
1. Data quality strong at bar level (1D builder has comprehensive validation)
2. Multi-TF builders have silent repair (OHLC sanity clamps without reject logging)
3. EMA validation absent (assumes bars correct, no output checks)
4. Operational tooling manual (6 separate commands for asset onboarding)
5. Code duplication high (80% shared logic not extracted in bar builders)

---

## Technical Decisions

### Gap Severity Framework
**Decision:** Use 4-tier severity (CRITICAL/HIGH/MEDIUM/LOW) based on impact dimensions

**Rationale:**
- CRITICAL: Data corruption or silent errors (trading system cannot tolerate)
- HIGH: Error-prone workflows or manual workarounds (slows development, increases mistakes)
- MEDIUM: Maintainability issues or missing docs (system works, but harder to change)
- LOW: Nice-to-have optimizations (no current pain point)

**Impact:** Clear prioritization for Phase 22-24. CRITICAL gaps addressed first (data quality), followed by HIGH (operations), then MEDIUM/LOW (code quality).

---

### Phase 22 Focus: Data Quality Over Operations
**Decision:** Prioritize CRITICAL gaps (reject tables, validation, backfill) in Phase 22 over HIGH operational gaps (add_asset.py, orchestration)

**Rationale:**
- Silent data corruption is highest risk (affects trading decisions)
- Reject visibility enables audit trail (required for production)
- EMA validation catches calculation bugs (prevents bad signals)
- 1D backfill detection prevents bar_seq corruption (ensures correct sequencing)

**Trade-off:** Asset onboarding remains manual in Phase 22 (HIGH gap deferred to Phase 23), but data quality guaranteed.

---

### Automation Opportunities Documented, Not Implemented
**Decision:** Flag automation opportunities in new-asset-guide.md but don't build in Phase 21

**Rationale:**
- Phase 21 is read-only analysis (no code changes per 21-CONTEXT.md)
- Automation scripts are Phase 23 work (after data quality fixes)
- Guide provides clear blueprint: add_asset.py (6-8h), onboard_asset.py (8-12h), recovery.py (4-6h)

**Impact:** Phase 23 can pick up automation work with clear requirements and effort estimates.

---

## Deviations from Plan

None - plan executed exactly as written.

Both tasks completed:
- Task 1: new-asset-guide.md created with 6-step checklist, verification queries, troubleshooting, cross-references
- Task 2: gap-analysis.md created with 15 gaps, severity tiers, evidence citations, phase assignments

All success criteria met:
- RVWQ-04 answered: Asset onboarding documented end-to-end ✓
- RVWD-04 complete: Gap analysis with severity tiers, sourced, prioritized ✓
- Wave 1 synthesis: All 6 prior deliverables referenced and integrated ✓
- Actionable: Gaps include effort estimates and phase assignments ✓

---

## Next Phase Readiness

### Phase 22 Prerequisites Met
- [x] Gap list prioritized (4 CRITICAL + 1 HIGH identified)
- [x] Effort estimates provided (44-63 hours total)
- [x] Evidence cited (validation-points.md, incremental-refresh.md)
- [x] Success criteria defined (reject visibility, EMA validation, 1D backfill, test suite)

**Blockers:** None

**Concerns:** None - data quality gaps are scoped and actionable

---

### Phase 23 Prerequisites Met
- [x] Operational gaps cataloged (4 HIGH + 2 MEDIUM)
- [x] Automation blueprint provided (add_asset.py, onboard_asset.py, recovery.py)
- [x] Asset onboarding workflow documented (6-step checklist)
- [x] Effort estimates for automation tools (30-43 hours total)

**Blockers:** None

**Concerns:** None - operational automation can proceed after Phase 22 data quality fixes

---

### Phase 24 Prerequisites Met
- [x] Code quality gaps identified (BaseBarBuilder missing)
- [x] Pattern consistency issues documented (calendar tz column, gap-fill strategy)
- [x] LOC reduction estimate (80% via BaseBarBuilder template)
- [x] Effort for refactoring (20-30 hours for BaseBarBuilder)

**Blockers:** None

**Concerns:** None - pattern consistency is lowest priority (system works, just harder to maintain)

---

## Artifacts

### Created Files
1. **.planning/phases/21-comprehensive-review/findings/new-asset-guide.md**
   - Purpose: Answer RVWQ-04 (How do I add a new asset?)
   - Size: 795 lines
   - Sections: Prerequisites (3), 6-step checklist, troubleshooting (3 common issues), automation opportunities, cross-references (5 Wave 1 docs), quick reference

2. **.planning/phases/21-comprehensive-review/deliverables/gap-analysis.md**
   - Purpose: RVWD-04 (Gap analysis with severity tiers)
   - Size: 639 lines
   - Structure: 4 CRITICAL gaps, 5 HIGH gaps, 4 MEDIUM gaps, 2 LOW gaps, summary by category, phase prioritization, effort estimates

### Modified Files
None (read-only analysis phase)

---

## Commits

1. **7805b6e0** - docs(21-04): create new asset onboarding guide (RVWQ-04)
   - Files: .planning/phases/21-comprehensive-review/findings/new-asset-guide.md
   - Commit message: End-to-end 6-step checklist, asset ID mechanics, verification queries, troubleshooting, cross-references, automation opportunities

2. **43a0ea88** - docs(21-04): create gap analysis with severity tiers (RVWD-04)
   - Files: .planning/phases/21-comprehensive-review/deliverables/gap-analysis.md
   - Commit message: 15 gaps (4 CRITICAL, 5 HIGH, 4 MEDIUM, 2 LOW), phase assignments, evidence citations, effort estimates

---

## Wave 1 Synthesis Verification

**All 6 Wave 1 outputs integrated:**

1. **script-inventory.md** → Used for:
   - Script command examples (new-asset-guide.md Steps 2-4)
   - Script location paths (refresh_cmc_price_bars_1d.py, etc.)
   - LOC counts for duplication analysis (GAP-M01: BaseBarBuilder missing)

2. **data-flow-diagram.md** → Used for:
   - Script execution order (new-asset-guide.md cross-reference)
   - Pipeline sequence understanding (1D → multi-TF → EMAs)
   - L1 system overview reference (asset onboarding flow)

3. **ema-variants.md** → Used for:
   - Variant selection guidance (new-asset-guide.md Step 4)
   - Open Question 4 → GAP-L01 (Six separate state tables)
   - EMA calculation mechanics (alpha formulas, dual EMAs)

4. **variant-comparison.md** → Used for:
   - Bar variant selection table (new-asset-guide.md Step 3)
   - Variant justification (tf_day vs calendar vs anchor)
   - Question 4 analysis → GAP-L01 evidence

5. **incremental-refresh.md** → Used for:
   - State management cross-reference (new-asset-guide.md)
   - Backfill detection mechanics → GAP-C03 (1D lacks backfill)
   - Incremental refresh verification (Step 6)

6. **validation-points.md** → Used for:
   - Verification queries (new-asset-guide.md Step 5)
   - Gap sources: GAP-C01 (Multi-TF rejects), GAP-C02 (EMA validation), GAP-C04 (test suite)
   - Troubleshooting reject reasons (new-asset-guide.md)

**Cross-reference completeness:** 100% (all Wave 1 outputs cited in at least one deliverable)

---

## Metrics

**Execution time:** 6.9 minutes (start: 2026-02-05T17:07:28Z, end: 2026-02-05T17:14:20Z)

**Wave 1 leverage:**
- Documents read: 6 (script-inventory, data-flow-diagram, ema-variants, variant-comparison, incremental-refresh, validation-points)
- Total Wave 1 content: ~5000 lines analyzed
- Synthesis efficiency: 2 deliverables (1434 lines) created in <10 minutes

**Gap identification efficiency:**
- Gaps per category: Data Quality (4), Operational (4), Documentation (3), Code Quality (2), Testing (1), Performance (1)
- Evidence citations: 15 gaps × avg 2 citations = ~30 source references
- Phase assignments: 100% of gaps assigned to Phase 22/23/24

**Asset onboarding documentation:**
- Checklist steps: 6 (Prerequisites → dim_assets → 1D bars → multi-TF bars → EMAs → validate → verify incremental)
- Verification queries: 15+ SQL queries provided
- Troubleshooting scenarios: 3 common issues documented
- Cross-references: 5 Wave 1 documents linked

---

## Summary

Phase 21 Plan 04 completed successfully, delivering:

1. **Actionable asset onboarding guide** (new-asset-guide.md):
   - End-to-end 6-step checklist (15-40 minutes per asset)
   - Asset ID mechanics clarified (CMC ID → dim_assets.id → bars/EMAs)
   - Verification queries provided (bar counts, EMA coverage, state)
   - Troubleshooting guidance (3 common failure modes)
   - Cross-references to all Wave 1 outputs

2. **Evidence-based gap analysis** (gap-analysis.md):
   - 15 gaps identified with severity tiers (4 CRITICAL, 5 HIGH, 4 MEDIUM, 2 LOW)
   - Every gap cited with source document + line numbers
   - Phase prioritization: Phase 22 (data quality), Phase 23 (operations), Phase 24 (code quality)
   - Effort estimates: 95-137 hours total remediation (3-4 weeks)

**Key achievement:** Complete synthesis of Wave 1 outputs into actionable deliverables for Phase 22-24 execution. New asset onboarding is now documented end-to-end, and all system gaps are prioritized by severity with clear remediation paths.

**Next steps:**
- Phase 22: Address 4 CRITICAL + 1 HIGH gaps (reject tables, EMA validation, 1D backfill, test suite, state docs)
- Phase 23: Build operational automation (add_asset.py, onboard_asset.py, recovery.py, summary logging)
- Phase 24: Extract BaseBarBuilder template (80% LOC reduction in bar builders)

**Wave 1 complete:** All 4 review questions answered (RVWQ-01 through RVWQ-04), all 4 structured deliverables created (RVWD-01 through RVWD-04). Ready for Phase 22 execution.
