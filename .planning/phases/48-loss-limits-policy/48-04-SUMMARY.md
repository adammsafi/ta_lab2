---
phase: 48-loss-limits-policy
plan: 04
subsystem: risk, database, analysis
tags: [postgresql, sqlalchemy, pool-caps, override-governance, risk-management, cli, reporting]

# Dependency graph
requires:
  - phase: 48-01
    provides: "pool_name column on dim_risk_limits, reason_category/expires_at/extended_at on cmc_risk_overrides (migration 328fdc315e1b)"
  - phase: 46-risk-controls
    provides: dim_risk_limits and cmc_risk_overrides tables with Phase 48 schema additions
  - phase: 42-strategy-selection
    provides: "Phase 42 bake-off MaxDD empirical values (-38.6%/-38.7% mean) used for pool cap derivation"
provides:
  - define_pool_caps.py: CLI deriving 4 pool caps from Phase 42 bake-off MaxDD data; seeds dim_risk_limits
  - validate_override_governance.py: 4 live DB validation tests + OVERRIDE_POLICY.md generator
  - dim_risk_limits seeded with 4 pool rows (conservative/core/opportunistic/aggregate)
affects:
  - Phase 46 RiskEngine: aggregate row (daily_loss=15%) is now live in dim_risk_limits
  - Phase 50+: pool-specific rows documented for future multi-pool deployment

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SELECT-before-INSERT/UPDATE pattern for tables without UNIQUE constraint on business key"
    - "savepoint/rollback pattern for CHECK constraint validation tests (SAVEPOINT + ROLLBACK TO SAVEPOINT)"
    - "Empirical fallback pattern: try DB first, fall back to hardcoded constants when table absent"
    - "Dual-purpose CLI: report generator + DB seeder in single script with --seed-db flag"

key-files:
  created:
    - src/ta_lab2/scripts/analysis/define_pool_caps.py
    - src/ta_lab2/scripts/analysis/validate_override_governance.py
    - src/ta_lab2/scripts/analysis/run_var_simulation.py
  modified: []

key-decisions:
  - "SELECT-before-INSERT for pool rows: dim_risk_limits pool_name has no UNIQUE constraint; SELECT-then-UPDATE/INSERT prevents duplicates"
  - "Aggregate cap hardcoded at 15%: aligns with Phase 42 V1 circuit breaker decision; not computed from bake-off data"
  - "Conservative cap = min(base_loss, vision_target): safety buffer applied but capped at Vision Draft DD target"
  - "Core cap = min(base_loss * 2, vision_target) / Opportunistic = min(base_loss * 3, vision_target): scaled multipliers with vision ceiling"
  - "SAVEPOINT pattern for CHECK constraint test: allows rollback of just the failing test without aborting outer BEGIN/END transaction"
  - "reports/ gitignored: report files (POOL_CAPS.md, OVERRIDE_POLICY.md) generated on-demand; scripts are the reproducibility artifacts"

patterns-established:
  - "Pool cap report generation: reports/loss_limits/ directory, POOL_CAPS.md with derivation chain + V1 enforcement table"
  - "Override governance policy: OVERRIDE_POLICY.md with live validation status embedded in report header"
  - "DB governance validation tests: 4-test suite (schema/constraint/insert/query) with PASS/FAIL logging"

# Metrics
duration: 4min
completed: 2026-02-25
---

# Phase 48 Plan 04: Pool Cap Definition + Override Governance Summary

**Pool cap CLIs seeding dim_risk_limits with 4 pool rows derived from Phase 42 bake-off MaxDD data, and override governance validation confirming CHECK constraint enforcement with OVERRIDE_POLICY.md generated.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-25T20:37:05Z
- **Completed:** 2026-02-25T20:42:00Z
- **Tasks:** 2
- **Files modified:** 3 (2 new CLIs + run_var_simulation.py ruff fixes)

## Accomplishments

- define_pool_caps.py derives Conservative (7.73%)/Core (15.46%)/Opportunistic (23.19%)/Aggregate (15.00%) daily loss caps from Phase 42 bake-off MaxDD (-38.6% mean) at 10% sizing fraction with 2x safety buffer
- All 4 pool rows seeded to dim_risk_limits via SELECT-before-INSERT/UPDATE pattern (limit_ids 4-7)
- validate_override_governance.py passes all 4 DB validation tests: schema columns present, CHECK constraint enforced, valid insertion + cleanup, expiry detection query valid
- POOL_CAPS.md generated documenting derivation chain, pool table, V1 enforcement rules
- OVERRIDE_POLICY.md generated documenting expiry rules (24h default, 168h max), 5 reason categories, CLI examples, DB schema, live validation results (4/4 PASS)
- No test row left behind in cmc_risk_overrides after validation

## Task Commits

Each task was committed atomically:

1. **Task 1: Pool cap definition CLI and policy document** - `d7ffce6d` (feat)
   - Also includes run_var_simulation.py (48-03 artifact) with ruff F841/F401 fixes
2. **Task 2: Override governance validation and policy document** - `2f157ba6` (feat)

**Plan metadata:** committed below with docs commit

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/define_pool_caps.py` - Pool cap derivation CLI: POOL_DEFINITIONS, derive_caps(), seed_dim_risk_limits(), generate_pool_caps_md(), --seed-db flag
- `src/ta_lab2/scripts/analysis/validate_override_governance.py` - Override governance validation: 4 DB tests with savepoint pattern, generate_override_policy_md(), OVERRIDE_POLICY.md
- `src/ta_lab2/scripts/analysis/run_var_simulation.py` - Phase 48-03 CLI (included here with ruff F841/F401 bug fixes)

## Decisions Made

- **SELECT-before-INSERT for pool rows:** `dim_risk_limits.pool_name` has no UNIQUE constraint (by design — NULL rows for portfolio-wide defaults), so cannot use ON CONFLICT. SELECT for existing row, then UPDATE or INSERT.
- **Aggregate cap hardcoded at 15%:** Phase 42 V1 deployment decision specifies 15% circuit breaker; not derived from bake-off arithmetic — this is a design constraint not a computed value.
- **Pool caps scaled by multiplier (1x/2x/3x):** Conservative gets base_loss, Core gets base_loss*2, Opportunistic gets base_loss*3; each capped at Vision Draft DD target per pool.
- **SAVEPOINT pattern in CHECK constraint test:** `engine.begin()` opens a single transaction for all 4 tests. The CHECK constraint test must rollback just the failing INSERT without aborting the outer transaction. PostgreSQL SAVEPOINT + ROLLBACK TO SAVEPOINT handles this cleanly.
- **reports/ gitignored confirms script-as-artifact pattern:** Reports are generated on-demand; the Python script is the reproducibility artifact committed to git (matching Phase 42 pattern for BAKEOFF_SCORECARD.md).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ruff F841 (unused variable) and F401 (unused import) in run_var_simulation.py**

- **Found during:** Task 1 (pre-commit hook blocked commit)
- **Issue:** `run_var_simulation.py` (Phase 48-03 artifact, untracked) had `data_source = source` assigned but never read (F841) and `from plotly.subplots import make_subplots` imported but unused (F401). Pre-commit ruff hook blocked the commit.
- **Fix:** Removed the unused `data_source` variable (replaced with `_source` prefix for intent clarity); removed the unused `make_subplots` import.
- **Files modified:** `src/ta_lab2/scripts/analysis/run_var_simulation.py`
- **Verification:** `ruff check src/ta_lab2/scripts/analysis/run_var_simulation.py` passes
- **Committed in:** `d7ffce6d` (Task 1 commit, alongside define_pool_caps.py)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in Phase 48-03 file blocking commit)
**Impact on plan:** Necessary to unblock git commit. The fix is a bug in an adjacent Phase 48-03 file; no scope creep relative to Plan 04 objectives.

## Issues Encountered

- ruff-format hook auto-reformatted validate_override_governance.py (mixed line endings from Windows write). Second commit attempt with re-staged file succeeded cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- LOSS-03 closed: 4 pool rows live in dim_risk_limits with data-driven caps
- LOSS-04 closed: Override governance validated at DB level; OVERRIDE_POLICY.md documents all rules
- Phase 48 is now fully complete (all 4 plans done)
- Phase 46 RiskEngine can now pick up the aggregate pool row (limit_id=7, daily_loss=15%) from dim_risk_limits
- Pool-specific rows (conservative/core/opportunistic) are defined for future multi-pool deployment (Phase 52+ scope)

---
*Phase: 48-loss-limits-policy*
*Completed: 2026-02-25*
