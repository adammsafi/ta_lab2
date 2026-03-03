---
phase: 69-l4-resolver-integration
plan: 01
subsystem: regimes
tags: [fnmatch, glob, policy-table, macro-regime, L4, tighten-only, MINT-02, yaml]

# Dependency graph
requires:
  - phase: 68-hmm-macro-analytics
    provides: L4 macro regime classifier producing keys like Hiking-Contracting-RiskOff-Unwind
  - phase: 27-regime-integration
    provides: resolver.py with TightenOnlyPolicy, resolve_policy, _match_policy
provides:
  - fnmatch glob pattern support in _match_policy() for keys containing *, ?, [
  - L4_MACRO_POLICY_ENTRIES (8 entries) covering adverse through neutral macro states
  - DEFAULT_POLICY_TABLE extended with L4 macro entries (15 total entries)
  - MINT-02 assertion enforcing size_mult <= 1.0 and gross_cap <= 1.0 on all L4 entries
  - YAML overlay in configs/regime_policies.yaml with 7 L4 macro rules
  - MINT-02 validation in policy_loader.load_policy_table() for YAML glob entries
affects:
  - 69-02 (regime refresher wiring)
  - 69-03 (executor integration)
  - risk/ (risk engine reading policy for gross_cap)
  - executor/ (paper executor reading policy for size_mult, orders)

# Tech tracking
tech-stack:
  added: [fnmatch (stdlib)]
  patterns:
    - "Glob-first matching: _match_policy checks for *, ?, [ before falling back to token-based"
    - "MINT-02 assertion pattern: module-level assert on all L4 entries at import time"
    - "L4 policy specificity order: most specific patterns (strongly_contracting+riskoff) precede broader ones"

key-files:
  created: []
  modified:
    - src/ta_lab2/regimes/resolver.py
    - src/ta_lab2/regimes/policy_loader.py
    - configs/regime_policies.yaml

key-decisions:
  - "Glob patterns check first (before token-based): avoids ambiguity when L4 keys contain dashes that would accidentally match token-based L0-L2 entries"
  - "L4_MACRO_POLICY_ENTRIES defined BEFORE DEFAULT_POLICY_TABLE.update() to preserve insertion order for glob specificity"
  - "8 in-code L4 entries include Unknown* catch-all; YAML overlay provides 7 (omits Unknown* since fallback is sufficient)"
  - "MINT-02 enforced twice: module-level assertion (import-time) and policy_loader validation (load-time)"

patterns-established:
  - "Glob-first _match_policy: keys with *, ?, [ use fnmatch.fnmatch; plain keys use token substring check"
  - "L4 tighten-only: all L4 macro entries have size_mult <= 1.0 and gross_cap <= 1.0"
  - "YAML L4 rules follow same specificity order as in-code L4_MACRO_POLICY_ENTRIES"

# Metrics
duration: 2min
completed: 2026-03-03
---

# Phase 69 Plan 01: Resolver fnmatch + L4 Macro Policy Entries + YAML Overlay Summary

**fnmatch glob pattern support added to _match_policy() and 8 L4 macro regime entries (covering RiskOff, contraction, unwind, unknown states) merged into DEFAULT_POLICY_TABLE with MINT-02 tighten-only invariant enforced at import time and YAML load time**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-03T11:43:22Z
- **Completed:** 2026-03-03T11:45:32Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Extended `_match_policy()` to support fnmatch glob patterns (keys with `*`, `?`, `[`) with zero regression for existing L0-L2 token-based entries
- Added `L4_MACRO_POLICY_ENTRIES` (8 entries) to `DEFAULT_POLICY_TABLE` covering: strongly_contracting+riskoff (0.30), contracting+riskoff (0.50), hiking+riskoff (0.55), generic riskoff (0.60), unwind (0.65), strong contraction (0.65), mild contraction (0.80), unknown (1.0)
- MINT-02 tighten-only invariant enforced via module-level assertion (import-time) and `policy_loader.load_policy_table()` validation (YAML load-time)
- YAML overlay extended with 7 L4 macro rules with glob patterns; `load_policy_table()` returns 8 glob-pattern entries after merge

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend _match_policy() with fnmatch and add L4 macro policy entries** - `2a65334e` (feat)
2. **Task 2: Add L4 macro rules to YAML overlay and verify policy_loader compatibility** - `c00cfcd1` (feat)

**Plan metadata:** pending (docs commit below)

## Files Created/Modified
- `src/ta_lab2/regimes/resolver.py` - Added `import fnmatch`, updated `_match_policy()` with glob-first branch, added `L4_MACRO_POLICY_ENTRIES` dict with 8 entries, MINT-02 assertion loop, `DEFAULT_POLICY_TABLE.update(L4_MACRO_POLICY_ENTRIES)`
- `src/ta_lab2/regimes/policy_loader.py` - Added MINT-02 validation block after YAML merge loop in `load_policy_table()`
- `configs/regime_policies.yaml` - Added 7 L4 macro regime rules under "L4 Macro Regime Rules" section header with glob patterns

## Decisions Made
- Glob patterns check FIRST before token-based matching to prevent false matches: a key like `*-RiskOff-*` would accidentally match any regime containing "RiskOff" in token-based mode without fnmatch's anchoring semantics
- `L4_MACRO_POLICY_ENTRIES` uses `continue` in the glob branch so non-matching glob patterns don't fall through to token matching
- YAML overlay omits `Unknown*` catch-all (7 entries vs 8 in-code) -- the in-code fallback is sufficient and the Unknown* entry exists in DEFAULT_POLICY_TABLE from the in-code merge
- MINT-02 enforced at two levels for defense-in-depth: module assertions catch developer errors at import time; loader validation catches YAML misconfiguration at load time

## Deviations from Plan

None - plan executed exactly as written. Pre-commit hook fixed mixed line endings in regime_policies.yaml (CRLF on Windows); required re-staging and new commit (not an amendment).

## Issues Encountered
- Pre-commit hook (`mixed-line-ending`) failed on first commit attempt for `configs/regime_policies.yaml` due to Windows CRLF. Hook auto-fixed the file; re-staged and created a new commit per GSD protocol (never amend).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 02 (regime refresher wiring): `resolve_policy()` now accepts `L4` parameter and matches macro keys via glob; refresher can pass `L4=macro_regime_key` directly
- Plan 03 (executor integration): `TightenOnlyPolicy.gross_cap` populated from L4 entries; executor can use `policy.size_mult` and `policy.gross_cap` for position sizing
- No blockers for Plans 02 or 03

---
*Phase: 69-l4-resolver-integration*
*Completed: 2026-03-03*
