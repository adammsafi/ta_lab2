---
phase: 51-perps-readiness
plan: 05
subsystem: risk
tags: [risk, perps, perpetuals, margin, liquidation, gate, sqlalchemy, decimal, pandas, mocking]

requires:
  - phase: 51-perps-readiness
    plan: 01
    provides: cmc_perp_positions + cmc_margin_config tables; dim_risk_limits with margin_alert_threshold + liquidation_kill_threshold columns; cmc_risk_events CHECK constraints with liquidation_warning/critical/margin_alert event types and margin_monitor source
  - phase: 51-perps-readiness
    plan: 04
    provides: compute_margin_utilization() + load_margin_tiers() + MarginState/MarginTier dataclasses + FundingAdjuster + compute_funding_payments
  - phase: 46-risk-controls
    plan: all
    provides: RiskEngine base (Gates 1/1.5/2/3/4) + RiskLimits + check_order() pattern

provides:
  - RiskEngine Gate 1.6: margin/liquidation check integrated into check_order() buy-only path
  - _check_margin_gate(): queries cmc_perp_positions + cmc_margin_config, computes utilization, fires at three severity levels
  - RiskLimits.margin_alert_threshold (1.5) and liquidation_kill_threshold (1.1) with NULL-safe DB loading
  - ta_lab2.risk package exports: MarginTier, MarginState, compute_margin_utilization, load_margin_tiers, compute_cross_margin_utilization
  - ta_lab2.backtests package exports: FundingAdjuster, FundingAdjustedResult, compute_funding_payments
  - 35 unit tests for Gate 1.6 (test_risk_margin_gate.py)
  - 32 integration tests for Phase 51 components (test_perps_integration.py)

affects:
  - future perp paper trading phases: RiskEngine Gate 1.6 is the enforcement mechanism for margin buffer policy
  - 52-operational-dashboard: can display margin utilization from cmc_perp_positions via risk events
  - 53+: any phase using check_order() with perp positions gets automatic liquidation protection

tech-stack:
  added: []
  patterns:
    - "Gate 1.6 severity ordering: most-severe-first check avoids dead code (critical <= warning <= buffer)"
    - "Perp-only gate: Gate 1.6 inside buy-only block; returns None immediately for sells or no active position"
    - "NULL-safe DB loading: _load_limits() reads new columns 9+10, falls back to dataclass defaults if NULL (backward compatible)"
    - "Mock sequence extension pattern: existing test side_effect lists extended with _no_perp_position() mock for Gate 1.6 DB read"
    - "Method-local imports in _check_margin_gate(): from ta_lab2.risk.margin_monitor import ... avoids circular import at module level"

key-files:
  created:
    - tests/test_risk_margin_gate.py
    - tests/test_perps_integration.py
  modified:
    - src/ta_lab2/risk/risk_engine.py
    - src/ta_lab2/risk/__init__.py
    - src/ta_lab2/backtests/__init__.py
    - tests/risk/test_risk_engine.py
    - tests/risk/test_integration.py

key-decisions:
  - "Gate 1.6 placed inside buy-only block: sell orders always bypass (reducing exposure is always safe). Gate runs AFTER cap gates (3+4) and BEFORE Gate 5 (allow)."
  - "Severity ordering (most to least severe): critical (<=1.1x, blocks) -> warning (<=1.5x, logs only) -> buffer (<=2.0x, blocks) -> safe (>2.0x). This order prevents dead code and matches PERP-04 specification."
  - "Warning does NOT block: The 'warning' gate result returns from _check_margin_gate but check_order() only blocks on 'critical' or 'buffer'. This matches the plan spec: warning is informational."
  - "NULL-safe dim_risk_limits loading: Old rows that predate the Phase 51 migration may have NULL for columns 9+10. _load_limits() falls back to RiskLimits() dataclass defaults (1.5 / 1.1) rather than erroring."
  - "cmc_perp_positions query by strategy_id only: Gate 1.6 queries the most recent non-flat position for the strategy. No asset_id filter (perp positions are identified by venue+symbol+strategy_id, not cmc_assets.id)."
  - "Existing test mock sequences updated: 5 tests in test_risk_engine.py and 2 in test_integration.py needed _no_perp_position() added to their side_effect list for buy orders that reach Gate 1.6."

patterns-established:
  - "Gate extension pattern: adding new gates requires updating existing buy-order test mock sequences with the new gate's DB call"
  - "Package export pattern: backtests/__init__.py now follows same pattern as risk/__init__.py (explicit __all__ + top-level imports)"

duration: 12min
completed: 2026-02-25
---

# Phase 51 Plan 05: RiskEngine Gate 1.6 + Package Exports Summary

**RiskEngine Gate 1.6 (margin/liquidation buffer) integrated into check_order() with three-level severity: critical (<=1.1x, blocks), warning (<=1.5x, logs only), buffer (<=2.0x, blocks); 67 new tests verify gate behavior and Phase 51 component interoperability**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-02-25T23:51:16Z
- **Completed:** 2026-02-25T00:03:30Z
- **Tasks:** 2/2
- **Files modified:** 7

## Accomplishments

- Extended `RiskEngine` with Gate 1.6 (`_check_margin_gate`): queries `cmc_perp_positions` for active perp positions, loads margin tiers from `cmc_margin_config` via `load_margin_tiers()`, computes utilization via `compute_margin_utilization()`, enforces three severity levels with correct check ordering (most-severe-first)
- Extended `RiskLimits` with `margin_alert_threshold` (1.5) and `liquidation_kill_threshold` (1.1); updated `_load_limits()` SQL to read 2 new columns with NULL fallback for backward compatibility with pre-Phase 51 rows
- Updated package exports: `ta_lab2.risk.__all__` now includes 5 margin monitor symbols; `ta_lab2.backtests.__init__.py` created with 3 funding adjuster symbols
- 35 unit tests in `test_risk_margin_gate.py` and 32 integration tests in `test_perps_integration.py`; all 82 existing risk tests continue to pass (7 test mock sequences updated with Gate 1.6 DB call)

## Task Commits

Each task was committed atomically:

1. **Task 1: RiskEngine Gate 1.6 + margin gate tests** - `fbe4d1de` (feat)
2. **Task 2: Package exports + integration tests** - `b6edeef0` (feat)

**Plan metadata:** (included in this SUMMARY commit)

## Files Created/Modified

- `src/ta_lab2/risk/risk_engine.py` - RiskLimits extended with 2 new fields; _load_limits() reads 11 columns; _check_margin_gate() private method; Gate 1.6 call inside check_order() buy-only block
- `src/ta_lab2/risk/__init__.py` - Added MarginTier, MarginState, compute_margin_utilization, load_margin_tiers, compute_cross_margin_utilization to imports + __all__
- `src/ta_lab2/backtests/__init__.py` - Created with FundingAdjuster, FundingAdjustedResult, compute_funding_payments imports + __all__
- `tests/test_risk_margin_gate.py` - 35 tests: TestRiskLimitsNewFields (5), TestMarginGateDirectMethod (11), TestMarginGateEventLogging (4), TestCheckOrderMarginGateIntegration (7), TestMarginGateThresholdOrdering (8)
- `tests/test_perps_integration.py` - 32 tests: TestFullModuleImports (11), TestFundingToMarginFlow (3), TestMarginGateBlocksCritical (2), TestMarginGateAllowsWarning (2), TestMarginGateBlocksBuffer (2), TestFundingSignConvention (4), TestPerpsPackageStructure (8)
- `tests/risk/test_risk_engine.py` - Updated _default_limits_row() to include 2 new columns; added _no_perp_position() helper; 4 buy-order tests updated with Gate 1.6 mock
- `tests/risk/test_integration.py` - Updated _default_limits_row(), added _no_perp_position() helper; 2 buy-order tests updated with Gate 1.6 mock

## Decisions Made

- **Gate 1.6 inside buy-only block:** Sell orders always bypass (reducing exposure is safe). Gate runs after cap gates (3+4) but before Gate 5 (allow). Warning result allows the order; only critical and buffer block.
- **Severity ordering most-severe-first:** critical (<=1.1x) checked before warning (<=1.5x) checked before buffer (<=2.0x). This prevents dead code where a 1.0x utilization would match all three conditions -- the first match wins.
- **Warning logs but does NOT block:** `_check_margin_gate()` returns `"warning"` which `check_order()` explicitly excludes from the `if margin_result in ("critical", "buffer"):` block. Order proceeds with adjusted_quantity.
- **NULL-safe column loading:** `_load_limits()` reads columns at index 9 (margin_alert_threshold) and 10 (liquidation_kill_threshold). If NULL (pre-Phase 51 DB rows), falls back to `RiskLimits()` dataclass defaults (1.5 / 1.1). No migration required for existing rows.

## Deviations from Plan

None - plan executed exactly as written.

Gate 1.6 implemented with correct severity ordering, sell bypass, warning-only behavior, and DB loading pattern exactly as specified. Existing test updates were anticipated in the plan's critical notes ("adding new gates may require extra mock returns"). Package exports added exactly as specified in must_haves.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted both task commits on first attempt; required re-staging and re-committing. Standard Windows/git behavior, no code impact.

## User Setup Required

None - all changes are library code and tests. No external service configuration required.

## Next Phase Readiness

- All 5 PERP requirements covered: PERP-01 (schema, Plan 01), PERP-02 (funding rates, Plan 02), PERP-03 (margin model integrated into RiskEngine Gate 1.6), PERP-04 (liquidation buffer 2x/1.5x/1.1x thresholds in Gate 1.6), PERP-05 (venue downtime playbook, Plan 03)
- Phase 51 complete: no blockers for subsequent phases
- Gate 1.6 activates automatically for any buy order when `cmc_perp_positions` has an active non-flat row for the strategy; no additional executor changes needed

---
*Phase: 51-perps-readiness*
*Completed: 2026-02-25*
