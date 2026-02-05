# Pitfalls Research

**Domain:** EMA & Bar Architecture Standardization (Production Quant System)
**Researched:** 2026-02-05
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: Breaking Working Scripts During Standardization (Silent Calculation Drift)

**What goes wrong:**
Standardizing validation logic or data sources causes EMA values to change slightly, breaking downstream consumers that depend on exact historical values. Production backtests fail validation, trading signals flip, and historical analysis becomes inconsistent.

**Why it happens:**
Teams focus on "making code cleaner" without recognizing that changing data sources (raw price_histories7 → validated bars) or calculation order can introduce floating-point differences. The scripts "work fine" in isolation, but the output differs from production baselines.

**How to avoid:**
- BEFORE changing any EMA calculator: capture baseline outputs (id, tf, period, ts, ema_value) for representative date ranges
- After standardization: run side-by-side comparison (old vs new) and flag any differences > epsilon (1e-10)
- Document intentional changes (e.g., "switching to validated bars means missing days are now flagged → different bar sequences → different EMA values")
- Create migration flag: `--validate-against-legacy` that compares outputs before deployment

**Warning signs:**
- "The code is cleaner now" without output validation
- "Small differences don't matter" (they do in quant systems)
- No baseline snapshots exist before refactoring starts
- Tests pass but backtest results change

**Phase to address:**
**Phase 1 (Review):** Capture baseline outputs for all 6 EMA variants
**Phase 2 (Data Source Fix):** Run side-by-side comparisons when switching to validated bars

---

### Pitfall 2: Incomplete Inventory Leading to Orphaned Dependencies

**What goes wrong:**
During review, teams miss helper scripts, orchestrators, or utility functions that depend on "variant X." After consolidating variants, production jobs fail because undocumented scripts still reference the old table/function.

**Why it happens:**
Focus narrows to "main" refresh scripts (the 6 EMA calculators), overlooking:
- Orchestrator scripts (run_all_ema_refreshes.py)
- Validation scripts (validate_ema_rowcounts.py, audit_ema_*.py)
- Stats calculators (refresh_ema_*_stats.py in stats/ subdirectories)
- Ad-hoc research queries in scripts/research/queries/
- Downstream consumers in features/, backtests/, signals/

**How to avoid:**
- Phase 1 checklist MUST include:
  - Grep for table names across entire codebase: `cmc_ema_multi_tf`, `cmc_ema_multi_tf_cal_us`, etc.
  - Grep for module imports: `from ta_lab2.features.m_tf.ema_multi_tf_cal import`
  - Find SQL queries referencing EMA tables: `SELECT * FROM public.cmc_ema`
  - Check orchestrators/run_all scripts for hardcoded paths
  - Document ALL consumers in REVIEW.md with dependency graph
- Before removing ANY variant: verify zero references in codebase + database views

**Warning signs:**
- Review document lists "6 main scripts" but repo has 30+ files with "ema" in name
- "We'll find consumers when they break" attitude
- No dependency graph created
- grep commands not run

**Phase to address:**
**Phase 1 (Review):** Create complete inventory using grep, imports analysis, SQL references
**Phase 3 (Standardization):** Before removing any code, verify zero consumers remain

---

### Pitfall 3: Premature Consolidation (Removing Variants Still In Use)

**What goes wrong:**
Team assumes "variants are redundant" and consolidates before understanding why 6 variants exist. Turns out variant 4 (cal_anchor_iso) is used by a critical backtest strategy that depends on partial-period snapshots. After consolidation, the strategy breaks.

**Why it happens:**
Variants look similar in code structure, leading to assumption they're "technical debt from copy-paste development." Reality: each variant serves a specific use case (calendar alignment, anchor snapshots, different week start conventions). The "redundancy" is actually necessary feature diversity.

**How to avoid:**
- Phase 1 MUST answer: "What consumer depends on each variant's unique behavior?"
  - multi_tf (tf_day): Used by X, Y, Z backtests
  - cal_us: Used by W weekly strategy
  - cal_iso: Used by V European market strategy
  - cal_anchor_us: Used by U partial-period analysis
  - etc.
- Create "variant justification matrix": variant → unique behavior → consumers → keep or consolidate decision
- Defer consolidation until Phase 4-5 (after standardization proves stable)
- Document "variants are not a bug, they're a feature set"

**Warning signs:**
- "These look the same, let's merge them" without consumer analysis
- No documentation of why 6 variants exist
- Consolidation happens in early phases (1-3) instead of late phases (4-5)
- "We'll make it configurable" without understanding configuration requirements

**Phase to address:**
**Phase 1 (Review):** Document why each variant exists and what depends on it
**Phase 4-5 (Consolidation):** Only consolidate after proving standardization works

---

### Pitfall 4: Schema Change Coordination Failure (State Table Primary Key Migration)

**What goes wrong:**
EMA_STATE_STANDARDIZATION.md documents a breaking change: state table primary key changed from `(id, tf)` to `(id, tf, period)`. Team updates scripts to use new schema, but forgets to:
- Migrate existing state data
- Update dependent scripts simultaneously
- Coordinate deployment (some scripts use old PK, some use new)

Result: Incremental refresh breaks because state lookups fail. Production runs full refresh (expensive) or fails silently.

**Why it happens:**
Schema changes require coordinated migration across:
- DDL (CREATE TABLE with new PK)
- Data (migrate old → new with CROSS JOIN)
- Scripts (all 6 variants + orchestrators)
- Deployment (atomic switchover)

Teams update "main" scripts but miss orchestrators, stats calculators, or state management helpers.

**How to avoid:**
- Create migration checklist for ANY schema change:
  - [ ] DDL update + migration SQL script
  - [ ] Run migration on staging database
  - [ ] Update ALL scripts (use grep to find references)
  - [ ] Test incremental refresh on staging with migrated state
  - [ ] Document rollback procedure
  - [ ] Deploy atomically (scripts + schema in same release)
- Use state_management.py shared module (already exists) to centralize schema
- Add schema version check: scripts validate state table PK before using it

**Warning signs:**
- Schema changes happen "gradually" across scripts
- No staging database migration test
- "We'll migrate state later" deferral
- Incremental refresh disabled during "transition period"

**Phase to address:**
**Phase 2 (Data Source Fix):** If state schema changes needed, coordinate migration
**Phase 3 (Standardization):** Centralize state management in shared module (already done via state_management.py)

---

### Pitfall 5: Validation Logic Inconsistency (Some Scripts Validated, Some Raw)

**What goes wrong:**
PROJECT.md states architectural principle: "Price histories should only be used to create bars. All downstream consumers should use validated bar data." During standardization, 3 of 6 EMA scripts get updated to use cmc_price_bars_1d (validated), but 3 still use price_histories7 (raw). Production system has inconsistent data quality across EMA tables.

**Why it happens:**
- Validation logic is complex (OHLC invariants, gap detection, repair strategies)
- Some scripts are harder to update (complex SQL, legacy patterns)
- "We'll fix the rest later" leads to partial migration
- Team doesn't realize mixing validated + unvalidated data creates invisible data quality divergence

**How to avoid:**
- Phase 2 ALL-OR-NOTHING rule: Either ALL 6 variants use validated bars, or NONE do
- Create validation contract test: "All EMA scripts MUST use bar tables (NOT price_histories7)"
- Automated check in CI: grep for `price_histories7` in EMA scripts → fail if found (after Phase 2 complete)
- Document data lineage: price_histories7 → bars → EMAs (one-way flow, no shortcuts)

**Warning signs:**
- "3 scripts migrated, 3 to go" status update
- Some scripts reference `cmc_price_bars_1d`, some reference `price_histories7`
- "We'll standardize later" deferral
- Data lineage diagram shows multiple paths to EMA tables

**Phase to address:**
**Phase 2 (Data Source Fix):** Atomic migration of ALL 6 variants to validated bars
**Phase 6 (Documentation):** Enforce data lineage principle in ARCHITECTURE.md

---

### Pitfall 6: Edge Case Coverage Gaps (Missing Test Cases from Different Variants)

**What goes wrong:**
Each of the 6 EMA variants evolved independently and handles different edge cases:
- Variant A: DST transitions
- Variant B: Partial calendar periods
- Variant C: ISO week edge cases
- Variant D: Missing data gaps

During standardization, team tests "happy path" but misses edge cases unique to each variant. Production hits DST transition → script fails because standardized version only tested tf_day (no calendar alignment edge cases).

**Why it happens:**
Edge case knowledge is embedded in variant-specific code, not documented. Team standardizes based on "most common path" without extracting edge case handling from all 6 variants.

**How to avoid:**
- Phase 1: Extract edge cases from EACH variant
  - For each script: read code, identify special handling (try/except, conditional logic, repair strategies)
  - Document: "cal_iso handles ISO week 53 edge case", "cal_anchor handles partial periods", etc.
  - Create edge case matrix: variant × edge case → handling approach
- Phase 3: Merge edge case handling into standardized version
  - Don't pick "best variant" — extract best edge case handling from ALL variants
  - Create test cases for each documented edge case
  - Verify standardized version passes all edge case tests

**Warning signs:**
- Review only documents "main flow" without edge cases
- "Variant X is the best, we'll use its logic" without checking other variants' edge cases
- Test suite has 10 tests (only happy path), not 100+ tests (happy + edge cases)
- Code has mysterious try/except blocks with no documentation

**Phase to address:**
**Phase 1 (Review):** Extract edge cases from each variant
**Phase 3 (Standardization):** Merge all edge case handling + create tests

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip baseline capture before refactoring | Save 2 hours setup time | Impossible to verify output correctness → silent drift → production failures | Never (baseline capture is mandatory for quant systems) |
| "We'll migrate state later" deferral | Ship faster | Half of scripts use old state schema, half use new → incremental refresh broken → expensive full refreshes | Never (state migration must be atomic) |
| Consolidate variants before understanding consumers | Reduce "code duplication" | Break downstream backtests/strategies that depend on variant-specific behavior → lost production capability | Never for production systems (defer to Phase 4-5 after stability proven) |
| Update 3 of 6 scripts to validated bars | Show progress | Inconsistent data quality across EMA tables → silent divergence → unreliable analysis | Never (ALL-OR-NOTHING rule for data source changes) |
| Use "best variant" logic without checking others | Fast standardization | Miss edge cases from other variants → production failures on edge conditions | Never (must extract edge cases from ALL variants) |
| Hardcode configuration in standardized version | Simpler code | Lose flexibility variants provided → can't support different use cases → force new variants to be created | Acceptable ONLY if consumer analysis proves configuration not needed |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Bar table validation | Assume validated bars exist for all timeframes | Check existence per TF: 1D uses cmc_price_bars_1d (validated), multi-TF may use different tables |
| State table queries | Hardcode primary key (id, tf) in WHERE clause | Use state_management.py shared module with (id, tf, period) PK |
| Orchestrator scripts | Hardcode script paths | Use relative imports or config-driven paths (run_all_ema_refreshes.py already has SCRIPTS dict) |
| Database connection pooling | Share engine across parallel workers | Use NullPool in workers (already implemented in refresh_cmc_ema_multi_tf_from_bars.py line 67) |
| Incremental refresh logic | Assume state table always has data | Handle cold start (no state) + warm start (state exists) scenarios |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Full refresh during standardization | "Safe" because it rebuilds everything | Incremental refresh is the default → validate it works early | First production deployment (6 EMA variants × 1000s of ids × 365 days = hours of compute) |
| Sequential orchestrator (no parallelization) | Simple code | Use parallel execution (run_all_ema_refreshes.py already uses multiprocessing for multi_tf) | >10 ids or >10 periods (runtime becomes bottleneck) |
| Loading all state into memory | Works for 10 ids | Filter state by selected ids BEFORE loading (already implemented in compute_dirty_window_start) | >100 ids in state table (memory exhaustion) |
| No connection pooling limits | Workers grab unlimited connections | Set max_connections limit + use NullPool in workers + coordinate with orchestrator | >6 parallel workers (Postgres "too many clients" error - already documented in run_all_ema_refreshes.py line 300) |

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Database credentials in code | Credential leak in version control | Use db_config.env file (already implemented in run_all_ema_refreshes.py line 88) + .gitignore |
| No audit trail for data changes | Can't trace who changed EMA values or why | Add src_load_ts, updated_at timestamps to all tables (bars already have this) |
| Raw SQL injection in dynamic queries | Malicious input could corrupt database | Use parameterized queries (already implemented in refresh_cmc_price_bars_1d.py line 74) |

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Silent failures in orchestrator | User thinks "it worked" but 3 of 6 scripts failed | Use --continue-on-error flag + summary report (already implemented in run_all_ema_refreshes.py line 431) |
| No progress visibility | User doesn't know if script hung or is processing | Add logging with worker IDs (already implemented in refresh_cmc_ema_multi_tf_from_bars.py line 64) |
| Unclear error messages | "Script failed" without context | Log specific failure: "Step cal_anchor FAILED: DATABASE CONNECTION LIMIT REACHED" (already implemented line 410) |
| No dry-run mode | User can't preview what will change | Add --dry-run flag to orchestrators (already implemented in run_all_bar_builders.py line 456) |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Review Phase:** Often missing baseline output snapshots — verify side-by-side comparison data captured
- [ ] **Review Phase:** Often missing consumer dependency graph — verify ALL downstream consumers documented (not just "main" scripts)
- [ ] **Review Phase:** Often missing edge case extraction — verify edge cases from ALL variants documented, not just one
- [ ] **Data Source Fix:** Often missing validation that ALL scripts migrated — verify no price_histories7 references remain in EMA calculators
- [ ] **Standardization:** Often missing state migration coordination — verify DDL + data + scripts deployed atomically
- [ ] **Standardization:** Often missing test coverage for merged edge cases — verify tests exist for edge cases from ALL variants
- [ ] **Schema Changes:** Often missing rollback plan — verify rollback procedure documented and tested on staging
- [ ] **Consolidation:** Often missing consumer validation — verify backtests still produce same results after consolidation

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Silent calculation drift detected in production | HIGH (rebuild trust + revalidate historical analysis) | 1. Roll back to old scripts immediately 2. Capture baseline from old version 3. Fix drift in new version 4. Run side-by-side validation 5. Document drift in migration notes |
| Orphaned dependency breaks production job | MEDIUM (find + fix consumer) | 1. Emergency patch: revert table/function name change 2. Grep codebase for ALL references 3. Update ALL consumers simultaneously 4. Redeploy atomically |
| Premature consolidation breaks backtest | HIGH (restore variant or recreate capability) | 1. Restore old variant from git history 2. Document consumer requirements 3. Re-consolidate with configuration support OR keep variant |
| State table migration breaks incremental refresh | MEDIUM (run full refresh once) | 1. Run full refresh with --rebuild flag 2. Verify new state table populated 3. Test incremental refresh on small ID set 4. Resume production with incremental |
| Validation logic inconsistency (mixed data sources) | HIGH (rebuild affected EMA tables) | 1. Identify which scripts use raw vs validated data 2. Migrate ALL scripts to validated bars 3. Rebuild EMA tables from validated bars 4. Verify data lineage compliance |
| Missing edge case causes production failure | LOW to MEDIUM (add handling + backfill) | 1. Extract edge case handling from old variant 2. Add to standardized version + test 3. Backfill affected date ranges if needed |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Silent calculation drift | Phase 1 (Review): Capture baselines | Phase 2/3: Run side-by-side comparison, verify delta < epsilon |
| Incomplete inventory | Phase 1 (Review): Grep + dependency graph | Phase 3: Verify zero orphaned consumers before removing code |
| Premature consolidation | Phase 1 (Review): Document variant justification | Phase 4-5: Only consolidate after stability proven |
| Schema change coordination | Phase 2/3: Atomic migration checklist | Staging deployment test + incremental refresh validation |
| Validation logic inconsistency | Phase 2 (Data Source Fix): ALL-OR-NOTHING rule | CI check: no price_histories7 in EMA scripts |
| Edge case coverage gaps | Phase 1 (Review): Extract edge cases from ALL variants | Phase 3: Test suite includes edge cases from all variants |

## Sources

**Web Research (2026):**
- [5 Critical ETL Pipeline Design Pitfalls to Avoid](https://airbyte.com/data-engineering-resources/etl-pipeline-pitfalls-to-avoid) - Schema drift, silent failures, hardcoded configuration
- [Best practices and pitfalls of the data pipeline process | TechTarget](https://www.techtarget.com/searchdatamanagement/feature/Best-practices-and-pitfalls-of-the-data-pipeline-process) - Tool sprawl, standardization governance
- [Why Data Pipelines Fail and How Enterprise Teams Fix Them](https://closeloop.com/blog/top-data-pipeline-challenges-and-fixes/) - Lack of scalability planning, automated maintenance
- [Code Refactoring: When to Refactor and How to Avoid Mistakes – Tembo](https://www.tembo.io/blog/code-refactoring) - Testing safety nets, incremental approach
- [10 refactoring best practices: When and how to refactor code | TechTarget](https://www.techtarget.com/searchsoftwarequality/tip/When-and-how-to-refactor-code) - Behavior preservation, API versioning
- [Data validation best practices and techniques for finance teams](https://www.cubesoftware.com/blog/data-validation-best-practices) - Standardized data dictionary, rule-based validation
- [How to Build Data Pipelines for the Finance Industry - 2026 | Integrate.io](https://www.integrate.io/blog/data-pipelines-finance-industry/) - Audit trails, security throughout ETL
- [Technical debt: a strategic guide for 2026](https://monday.com/blog/rnd/technical-debt/) - Agile workflow integration, active area focus
- [Is Premature optimization opposite of Technical debt | Scrum.org](https://www.scrum.org/forum/scrum-forum/36110/premature-optimization-opposite-technical-debt) - Premature optimization as debt

**Project-Specific Evidence:**
- EMA_STATE_STANDARDIZATION.md: Documents breaking PK change (id, tf) → (id, tf, period)
- run_all_ema_refreshes.py: Shows 6 variants exist, connection pooling warnings (line 300-304)
- refresh_cmc_price_bars_1d.py: Demonstrates validation logic (OHLC invariants, rejects table)
- refresh_cmc_ema_multi_tf_from_bars.py: Shows NullPool pattern for workers (line 67), special 1D handling (line 88)
- PROJECT.md: States architectural principle (price_histories7 → bars → EMAs one-way flow)
- validate_ema_rowcounts.py: Shows validation expectations from dim_timeframe

---
*Pitfalls research for: EMA & Bar Architecture Standardization*
*Researched: 2026-02-05*
*Focus: Production safety during standardization of existing working systems*
