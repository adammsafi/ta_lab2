---
phase: 70-cross-asset-aggregation
plan: 03
subsystem: portfolio
tags: [cross-asset, covariance, portfolio-optimizer, telegram, sign-flip, macro, regime]

# Dependency graph
requires:
  - phase: 70-02
    provides: compute_crypto_macro_corr, cmc_cross_asset_agg table with high_corr_flag
  - phase: 58-portfolio-construction-sizing
    provides: PortfolioOptimizer class, portfolio.yaml config
  - phase: 47-drift-guard
    provides: ta_lab2.notifications.telegram (send_alert, is_configured)

provides:
  - PortfolioOptimizer._apply_high_corr_override() -- covariance inflation when high_corr_flag=True
  - send_sign_flip_alerts() -- Telegram alerting on crypto-macro sign flips
  - portfolio.yaml high_corr_override section (enabled, blend_factor)
  - compute_crypto_macro_corr() now accepts alert_new_only parameter

affects:
  - 71-event-risk-gates
  - 72-macro-observability
  - Any consumer of PortfolioOptimizer.run_all()

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Covariance blending: S_adj = (1-b)*S + b*S_full_corr for regime-aware optimization"
    - "Alert grouping: >3 flips on same date sends summary instead of N individual messages"
    - "Graceful degradation: DB failure, missing table, Telegram unconfigured all no-op"
    - "alert_new_only parameter pattern: caller controls whether historical runs generate alerts"

key-files:
  created: []
  modified:
    - src/ta_lab2/portfolio/optimizer.py
    - configs/portfolio.yaml
    - src/ta_lab2/macro/cross_asset.py

key-decisions:
  - "blend_factor=0.3 default: blends 30% toward full-corr matrix; tunable without code change"
  - "Off-diagonal inflation uses sqrt(var_i * var_j) formula (correlation=1.0 for all pairs)"
  - "DB query for high_corr_flag is per-call (not cached) so no stale state across intraday runs"
  - "alert_new_only=True default: prevents spam on --full historical recompute"
  - "Spam threshold=3: groups same-date flips when >3 occur"
  - "send_alert() called with plain string severity ('warning'), not AlertSeverity enum"

patterns-established:
  - "Override pattern: config switch + DB flag + try/except = safe cross-module coupling"
  - "Telegram alert grouping by date with threshold to prevent alert fatigue"

# Metrics
duration: 4min
completed: 2026-03-03
---

# Phase 70 Plan 03: Cross-Asset Downstream Consumers Summary

**PortfolioOptimizer covariance inflation on high-corr regime flag + Telegram sign-flip alerts with grouping and graceful degradation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-03T14:34:43Z
- **Completed:** 2026-03-03T14:38:16Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- PortfolioOptimizer reads `high_corr_flag` from `cmc_cross_asset_agg` (latest row) and inflates off-diagonal covariance when True, reducing illusory diversification benefit
- `blend_factor=0.3` (configurable in `portfolio.yaml`) blends toward fully-correlated matrix; master switch `enabled: true` allows disabling without code change
- `send_sign_flip_alerts()` added to `cross_asset.py` with date-based grouping, spam threshold, and graceful fallback when Telegram unconfigured
- `compute_crypto_macro_corr()` extended with `alert_new_only=True` parameter to suppress historical spam during `--full` reruns

## Task Commits

Each task was committed atomically:

1. **Task 1: Portfolio optimizer covariance override** - `e7721092` (feat)
2. **Task 2: Telegram sign-flip alerts in cross-asset module** - `f7a97369` (feat)

**Plan metadata:** (included in docs commit below)

## Files Created/Modified

- `src/ta_lab2/portfolio/optimizer.py` - Added `_apply_high_corr_override()` method; call site in `run_all()` after Ledoit-Wolf, before condition number check; `high_corr_override` config loaded in `__init__`
- `configs/portfolio.yaml` - Added `high_corr_override` section with `enabled: true`, `blend_factor: 0.3`
- `src/ta_lab2/macro/cross_asset.py` - Added `send_sign_flip_alerts()` function; added `alert_new_only` param to `compute_crypto_macro_corr()`; alert call before return in compute function

## Decisions Made

- **blend_factor=0.3 as default:** Conservative blend; 30% toward full-corr is meaningful but doesn't force extreme weights. Tunable via YAML with no code change.
- **Off-diagonal formula:** `S_full_corr[i,j] = sqrt(var_i * var_j)` gives correlation=1.0 while preserving asset-specific variance on diagonal. This is mathematically sound for a "worst-case diversification" scenario.
- **DB query per call (not cached):** Optimizer may run multiple times per session; caching could lead to stale state if regime transitions mid-session. Single-row SELECT is negligible overhead.
- **Spam threshold=3:** Based on typical asset universe size (10-50 assets x 4 macro vars = 40-200 pairs); >3 same-day flips is a systemic event deserving summary treatment.
- **`alert_new_only=True` default:** Historical recompute (`--full`) should not spam. Incremental runs (default) alert on genuinely new sign flips only.
- **Plain string severity ('warning'):** Matches `send_alert()` API signature. ImportError/NameError avoided by not importing `AlertSeverity` enum.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Ruff format hook reformatted `cross_asset.py` on first commit attempt (whitespace in warning string). Restaged and recommitted successfully. No logic changes.

## User Setup Required

None - no external service configuration required. Telegram alerts require `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars (existing requirement from Phase 47), and `sign_flip_alerts: true` in `configs/cross_asset_config.yaml` under the `telegram` section.

## Next Phase Readiness

- Phase 70 (Cross-Asset Aggregation) is now COMPLETE (all 3 plans done)
- Cross-asset signals are computed (Plan 02), stored in DB, and consumed by downstream systems (Plan 03)
- Phase 71 (Event Risk Gates) can reference `high_corr_flag` from `cmc_cross_asset_agg` for risk gate conditions
- Phase 72 (Macro Observability) can display sign-flip history from `crypto_macro_corr_regimes`

---
*Phase: 70-cross-asset-aggregation*
*Completed: 2026-03-03*
