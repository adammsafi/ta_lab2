---
phase: 51-perps-readiness
plan: 04
subsystem: backtests
tags: [perps, perpetuals, funding-rates, margin, vectorbt, decimal, pandas, sqlalchemy]

requires:
  - phase: 51-perps-readiness
    plan: 01
    provides: cmc_funding_rates and cmc_margin_config tables ready for queries
  - phase: 51-perps-readiness
    plan: 02
    provides: get_funding_rate_with_fallback function and cmc_funding_rates populated by refresh_funding_rates.py

provides:
  - FundingAdjustedResult dataclass: equity_adjusted, total_funding_paid, total_return_adjusted, sharpe_adjusted, funding_payments_series
  - compute_funding_payments: pure function, sign-correct per-bar funding payments with tz-naive alignment
  - load_funding_rates_for_backtest: daily (tf='1d') and per_settlement (tf IN 1h/4h/8h) modes
  - get_funding_rate_with_fallback: exact match then cross-venue avg +/-30min window (re-exported from funding_adjuster.py)
  - FundingAdjuster class: post-simulation funding P&L adjustment for vbt portfolios (lazy vbt import)
  - MarginTier dataclass: notional bracket with IM rate, MM rate, max leverage
  - MarginState dataclass: full margin state with utilization, warning/critical flags, optional liquidation price
  - compute_margin_utilization: tiered rate selection, isolated/cross mode, liquidation price estimation
  - compute_cross_margin_utilization: portfolio-level cross-margin ratio
  - load_margin_tiers: SQL loader from cmc_margin_config with Decimal(str(round(float,8))) pattern

affects:
  - 51-05: liquidation buffer and RiskEngine Gate 1.6 will use MarginState.is_liquidation_critical and FundingAdjuster
  - future perp backtests: funding_adjuster.py is the standard P&L adjustment entry point
  - future carry trade analysis: funding rates queryable via load_funding_rates_for_backtest

tech-stack:
  added: []
  patterns:
    - "Lazy vbt import: FundingAdjuster.adjust() imports vectorbt inside the method to avoid ImportError in test environments"
    - "tz-naive alignment pattern: _strip_tz() strips tz from DatetimeIndex before reindex/ffill (MEMORY.md pitfall)"
    - "Decimal via str(round(float, 8)): _to_decimal() helper in margin_monitor.py matches project Decimal pattern"
    - "Conservative fallback defaults: IM=10% / MM=5% when no tier rows found, prefer safety over leniency"
    - "Tier selection: highest tier where notional_floor <= position_value (ascending scan, last-applicable wins)"
    - "DB-free testing: all DB functions tested via mock engine; pure computation functions tested directly"

key-files:
  created:
    - src/ta_lab2/backtests/funding_adjuster.py
    - src/ta_lab2/risk/margin_monitor.py
    - tests/test_funding_adjuster.py
    - tests/test_margin_monitor.py
  modified: []

key-decisions:
  - "Equity as position_timeline approximation: FundingAdjuster.adjust() uses pf.value() as absolute notional (position_value). Accurate for 1x leverage backtest; for levered positions the caller should supply actual notional."
  - "Cumulative funding adjustment: equity_adj = equity + cumsum(payments). Payments are signed (negative=outflow for longs), so cumsum naturally compounds the funding drag/gain over time."
  - "Liquidation price not estimated for cross mode: cross-margin positions share wallet balance; per-position liq price is venue-dependent and requires portfolio-level calculation outside this module."
  - "Decimal('inf') for last tier cap: cmc_margin_config stores notional_cap as NUMERIC, but the last tier is unbounded. load_margin_tiers converts None/inf strings to Decimal('inf') for correct applies_to() comparison."
  - "Warning threshold is inclusive (<=1.5, <=1.1): matches dim_risk_limits defaults (margin_alert_threshold=1.5, liquidation_kill_threshold=1.1) from Plan 01."

patterns-established:
  - "Post-simulation adjustment pattern: backtester runs with zero funding cost, then FundingAdjuster replays payments against equity. Keeps vbt_runner.py unchanged."
  - "Margin tier scan: iterate ascending tiers, track last-applicable (highest floor <= position). Stop when floor exceeds position."

duration: 5min
completed: 2026-02-25
---

# Phase 51 Plan 04: FundingAdjuster and MarginMonitor Summary

**Post-simulation funding P&L adjustment (FundingAdjuster) and tiered perpetual margin model (MarginMonitor) with 64 unit tests covering sign conventions, threshold boundaries, Binance BTC tier selection, and cross-margin utilization**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-25T23:42:29Z
- **Completed:** 2026-02-25T23:47:26Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Created `funding_adjuster.py`: FundingAdjustedResult dataclass, `compute_funding_payments` pure function with correct long/short sign convention, daily and per_settlement DB loading modes, `FundingAdjuster.adjust()` with lazy vectorbt import and tz-naive alignment
- Created `margin_monitor.py`: MarginTier and MarginState dataclasses with Decimal precision, `compute_margin_utilization` with 3-tier rate selection and 1.5x/1.1x warning/critical thresholds, `compute_cross_margin_utilization` for portfolio-level risk, `load_margin_tiers` from cmc_margin_config
- 29 funding adjuster tests (sign conventions, frequency alignment, mock DB, helpers) and 35 margin monitor tests (tier selection, threshold boundaries, liquidation price formulas, fallback defaults, cross-margin) -- all pass

## Task Commits

Each task was committed atomically:

1. **Task 1: FundingAdjuster module + unit tests** - `10e74dec` (feat)
2. **Task 2: Margin model module + unit tests** - `1104cc6e` (feat)

**Plan metadata:** (included in this SUMMARY commit)

## Files Created/Modified

- `src/ta_lab2/backtests/funding_adjuster.py` - FundingAdjustedResult, compute_funding_payments, load_funding_rates_for_backtest, get_funding_rate_with_fallback, FundingAdjuster class
- `src/ta_lab2/risk/margin_monitor.py` - MarginTier, MarginState, compute_margin_utilization, compute_cross_margin_utilization, load_margin_tiers
- `tests/test_funding_adjuster.py` - 29 unit tests (473 lines), no DB required
- `tests/test_margin_monitor.py` - 35 unit tests (500 lines), no DB required

## Decisions Made

- **Equity as position_timeline approximation:** `FundingAdjuster.adjust()` uses `pf.value()` as the absolute notional for funding calculation. This is accurate for 1x leverage backtests; callers running leveraged positions should supply actual notional. The approximation is documented in the module docstring.
- **Lazy vectorbt import in FundingAdjuster.adjust():** `import vectorbt as vbt` deferred to inside the method body. Allows `from ta_lab2.backtests.funding_adjuster import compute_funding_payments` in test and CI environments where vectorbt is not installed, without modifying vbt_runner.py.
- **Cumulative funding adjustment formula:** `equity_adj = equity + cumsum(payments)`. Payments are already sign-correct (longs: negative=outflow, shorts: positive=inflow), so cumsum naturally compounds funding drag/gain. This was verified against plan spec: "Adjust equity: equity_adj = equity - cumulative_funding" is equivalent when payments are pre-negated.
- **Decimal('inf') for unbounded tier cap:** The last margin tier has no upper notional bound. `load_margin_tiers` converts None/empty/infinity strings from DB to `Decimal('inf')` for correct `applies_to()` evaluation without special-case branching.
- **Liquidation price skipped for cross mode:** Cross-margin positions share total wallet balance; per-position liquidation price depends on portfolio composition, not just the single position. Returning None for cross mode is conservative and honest -- Plan 05 can implement portfolio-level cross liquidation if needed.

## Deviations from Plan

None - plan executed exactly as written.

All specified functions, dataclasses, sign conventions, modes, and thresholds implemented as described. Test coverage exceeded minimums (473 lines vs 80 required; 500 lines vs 60 required).

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted both task commits on first attempt; required re-staging and re-committing. Standard Windows/git behavior, no code impact.

## User Setup Required

None - both modules are library code. No external service configuration required. DB is only accessed at runtime via injected engine.

## Next Phase Readiness

- `FundingAdjuster` ready for Plan 05 (liquidation buffer): call `adjuster.adjust(pf)` to get funding-adjusted equity and `total_funding_paid`
- `MarginState.is_liquidation_critical` (True when util <= 1.1) is the signal for RiskEngine Gate 1.6 in Plan 05
- `load_margin_tiers` reads from `cmc_margin_config` seeded in Plan 01 (Binance BTC/ETH + Hyperliquid BTC/ETH -- 8 rows ready)
- `compute_cross_margin_utilization` accepts `List[MarginState]` -- Plan 05 can build the list from `cmc_perp_positions` table
- No blockers for Plan 05

---
*Phase: 51-perps-readiness*
*Completed: 2026-02-25*
