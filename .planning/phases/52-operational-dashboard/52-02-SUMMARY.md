---
phase: 52-operational-dashboard
plan: "02"
subsystem: ui
tags: [streamlit, plotly, dashboard, trading, risk, pnl, positions, circuit-breaker]

# Dependency graph
requires:
  - phase: 52-01
    provides: "4 query modules (trading/risk/drift/executor) + 3 chart builders (build_pnl_drawdown_chart, build_tracking_error_chart, build_equity_overlay_chart)"
  - phase: 51
    provides: "Paper trading tables: cmc_positions, cmc_fills, cmc_orders, dim_executor_config"
  - phase: 47
    provides: "Risk tables: dim_risk_state, dim_risk_limits, cmc_risk_events"

provides:
  - "6_trading.py: Trading page with portfolio KPIs, PnL+drawdown stacked chart, 12-column positions table, last-20-fills trade log"
  - "7_risk_controls.py: Risk & Controls page with kill switch cards, daily loss / position proximity gauges, circuit breaker expander, filterable event history"
  - "Kill switch + drift pause alert banners at top of both pages (impossible to miss)"
  - "AUTO_REFRESH_SECONDS = 900 (@st.fragment run_every) on both pages"

affects:
  - "52-03 (remaining pages)"
  - "any future operational dashboard pages"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Alert banners outside fragment pattern: load_risk_state called at module level for kill switch/drift banners, no cache delay"
    - "st.sidebar controls outside fragment (fragment restriction workaround)"
    - "Circuit breaker JSON parsing pattern: json.loads() on TEXT fields with fallback to empty dict"
    - "Proximity gauge pattern: st.progress(pct) + st.caption color context (green/orange/red thresholds)"

key-files:
  created:
    - "src/ta_lab2/dashboard/pages/6_trading.py"
    - "src/ta_lab2/dashboard/pages/7_risk_controls.py"
  modified: []

key-decisions:
  - "Kill switch / drift pause banners load risk_state outside fragment (no 15-min cache delay for safety-critical alerts)"
  - "Positions table has aggregate view (default) and per-strategy view toggled via st.sidebar"
  - "Daily loss proximity computed as (day_open_value - current_value) / day_open_value using unrealized PnL + day_open_portfolio_value from dim_risk_state"
  - "Circuit breaker consecutive-loss progress bars rendered inside expander (auto-expanded when breakers are tripped)"
  - "AUTO_REFRESH_SECONDS = 900 as module-level constant on both pages for easy reconfiguration"

patterns-established:
  - "Safety-critical banners at module level (outside fragment) so they always show current state regardless of fragment cache"
  - "Fragment receives _engine (underscore-prefixed) + sidebar values as parameters"
  - "Try/except per section with st.warning() display, matching existing dashboard pattern"

# Metrics
duration: 2min
completed: 2026-02-26
---

# Phase 52 Plan 02: Trading and Risk & Controls Pages Summary

**Two Streamlit operational pages: Trading (portfolio KPIs, stacked PnL+drawdown chart, 12-column positions table, 20-fill trade log) and Risk & Controls (kill switch cards, proximity progress bars, circuit breaker expander, filterable event history) -- both with prominent safety banners and 15-min auto-refresh**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-26T04:57:57Z
- **Completed:** 2026-02-26T05:00:28Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Trading page (6_trading.py, 328 lines): portfolio value / daily PnL / cumulative PnL / open-position-count KPIs; stacked two-panel PnL+drawdown Plotly chart with HTML download button; 12-column positions table (Asset, Side, Qty, Avg Cost, Current Price, Unrealized PnL, % of Portfolio, Strategy, Entry Date, Realized PnL, Signal Type, Regime Label) with aggregate/per-strategy toggle; last-20-fills trade log
- Risk & Controls page (7_risk_controls.py, 370 lines): kill switch + drift pause + circuit breaker status cards with time-since deltas; daily loss proximity gauge and position utilization gauge with color-coded captions; circuit breaker expander showing per-asset/strategy consecutive loss progress bars; filterable risk event history (type + days filters from sidebar)
- Both pages: red/yellow alert banners at top loaded outside fragment for zero-cache-delay safety; AUTO_REFRESH_SECONDS = 900 with @st.fragment(run_every=...); no st.set_page_config() calls; st.sidebar controls outside fragment

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Trading page (6_trading.py)** - `164bf917` (feat)
2. **Task 2: Create Risk & Controls page (7_risk_controls.py)** - `164bf917` (feat)

(Tasks 1 and 2 committed together as a single logical unit)

**Plan metadata:** committed with docs commit below

## Files Created/Modified

- `src/ta_lab2/dashboard/pages/6_trading.py` - Trading page: portfolio KPIs, PnL+drawdown chart, positions table, fills trade log
- `src/ta_lab2/dashboard/pages/7_risk_controls.py` - Risk & Controls page: kill switch cards, proximity gauges, CB expander, event history

## Decisions Made

- Alert banners load `load_risk_state()` outside the `@st.fragment` so they always reflect the true current state regardless of the 15-minute fragment refresh cycle. Safety-critical alerts must not be cached.
- Daily loss consumed is computed as `max(0, -(current_value - day_open_value) / day_open_value)` -- positive consumed value represents loss, compared against `daily_loss_pct_threshold` from `dim_risk_limits`.
- Circuit breaker JSON fields (`cb_consecutive_losses`, `cb_breaker_tripped_at`) are parsed with `json.loads()` with fallback to `{}` -- stored as TEXT in PostgreSQL, matching the Phase 47 schema design.
- Positions aggregate view groups by (symbol, signal_type, regime_label) with summed PnL and quantity, average cost basis, and last mark price. Strategy/entry_date columns hidden in aggregate view.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook (ruff-format + mixed-line-endings) reformatted both files on first commit attempt. Re-staged and committed cleanly on second attempt. No code logic changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 6_trading.py and 7_risk_controls.py are complete and importable
- Wave 2 of Phase 52 (this plan) is complete
- Phase 52 Wave 3 (52-03 and beyond) can proceed: Drift Monitor and Executor Status pages
- All query modules and chart builders from 52-01 verified working via import checks

---
*Phase: 52-operational-dashboard*
*Completed: 2026-02-26*
