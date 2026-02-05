# Phase 24: Pattern Consistency - Context

**Gathered:** 2026-02-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Standardize patterns across the 6 EMA variants and 6 bar builders where Phase 21 gap analysis identified inconsistency or duplication worth addressing. Apply standardization ONLY where analysis justifies (no premature abstraction). Keep all 6 EMA variants - they exist for legitimate reasons.

This phase addresses MEDIUM and LOW priority gaps from Phase 21 - code quality and pattern consistency, NOT new features or data quality fixes (those were Phase 22-23).

</domain>

<decisions>
## Implementation Decisions

### Shared Utility Extraction Scope

- **Aggressiveness:** Claude's discretion - balance refactoring benefit vs complexity
- **BaseBarBuilder:** Create if doesn't exist (check Phases 6-7 first), mirror BaseEMARefresher success pattern
- **Location:** Claude decides based on dependency graph analysis
- **Target ratio:** Claude decides based on actual duplication found (EMAs achieved 80% shared / 20% variant-specific)
- **Compatibility:** Allow refactoring - variants can be updated to use new shared functions for cleaner long-term code

**Rationale:** User trusts analysis-driven approach. Phase 21 found 80% of EMA code already shared (BaseEMARefresher, EMAStateManager, compute_ema). The remaining 20% are intentional differences (data sources, calendar alignment, alpha calculation). Bar builders show similar 80% duplication opportunity.

### Data Loading Standardization Approach

- **Query construction:** Extract query builder functions (user chose "Yes")
- **Query implementation:** Claude decides most maintainable approach (SQL strings vs SQLAlchemy Core vs templates)
- **Table abstraction:** Variant-aware - builder knows variant-to-table mapping (user chose this)
- **Query scope:** Claude decides based on relevant analysis (full queries vs core structure vs composable)
- **State integration:** Claude decides based on separation of concerns (query builder includes state logic vs separate)

**Rationale:** User wants query builders but delegates technical decisions (SQL approach, pagination, state integration) to Claude based on code analysis and best practices.

### State Management Consistency Level

- **State schemas:** Claude decides based on actual variance found (analyze current schemas, standardize where beneficial)
- **Cross-category:** Claude decides based on semantic differences (whether bars and EMAs have different state needs)
- **State manager:** Check if BarStateManager exists from Phase 6-7, create if missing following EMA pattern

**Rationale:** User wants consistency with existing patterns (EMAStateManager) but delegates schema decisions to analysis of actual needs.

### Validation Code Sharing Strategy

- **OHLC validation:** Check code first and review already completed work (verify if truly identical)
- **EMA validation:** Check if Phase 22 placed it correctly (verify current implementation, then decide)
- **NULL & gaps:** Claude decides based on complexity (extract if non-trivial, keep inline if simple)
- **Reject logging:** Claude decides (shared function vs per-builder based on schema variance)

**Rationale:** Phase 22 already added validation. Phase 24 organizes it - check what exists, refactor only if analysis shows benefit.

### Claude's Discretion

- Extraction aggressiveness (conservative vs moderate vs aggressive)
- Query builder implementation technology (SQL strings, SQLAlchemy, templates)
- Utility module location in codebase
- Target sharing ratio for bar builders
- Query scope (full queries vs composable functions)
- State watermarking integration approach
- State schema standardization level
- NULL/gap validation approach (shared vs inline)
- Reject table logging pattern

</decisions>

<specifics>
## Specific Ideas

- **Review Phases 1-10 and current state first** - User explicitly requested: "review phase 1-10 and the current state of things because a lot of this work was already done and doesn't need to be duplicated"
- **Check existing work before building** - User emphasized multiple times: "check if it exists first", "check code first and review already completed work", "check all earlier phases and the current state of things"
- **Mirror EMA success** - BaseEMARefresher, EMAStateManager, compute_ema provide 80% code sharing across 6 EMA variants - bar builders should follow this proven pattern
- **Variant-to-table mapping** - User wants centralized mapping rather than table names passed as parameters
- **Allow refactoring** - User comfortable with variant code updates to adopt new shared functions

**Key Context from Phase 21:**
- 80% of EMA code already shared (BaseEMARefresher, EMAStateManager, compute_ema)
- 20% differences are intentional (data sources, calendar alignment, alpha calculation)
- NOT code duplication - "All 6 EMA variants exist for legitimate reasons"
- Bar builders show ~80% duplication opportunity (gap analysis GAP-M02)

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope.

User focused on understanding what already exists and applying proven patterns (BaseEMARefresher) to bar builders.

</deferred>

---

*Phase: 24-pattern-consistency*
*Context gathered: 2026-02-05*
