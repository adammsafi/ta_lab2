# Phase 81: GARCH & Conditional Volatility - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Conditional volatility forecasting via GARCH family models, integrated into position sizing and risk management. Includes model fitting, forecast storage, comparison against existing vol estimators, and daily refresh wiring. Does NOT include strategy-specific signal generation (Phase 82) or portfolio construction (Phase 86).

</domain>

<decisions>
## Implementation Decisions

### Model scope & variants
- **Full suite:** GARCH(1,1) + EGARCH + GJR-GARCH + FIGARCH — all four variants fitted per asset
- **Window types:** Both rolling AND expanding windows — compare which performs better per asset/regime
- **Forecast horizons:** 1-day and 5-day ahead conditional vol forecasts
- **Input returns:** Both log returns AND arithmetic returns — log returns already exist in returns tables. Compare which input produces better forecasts.
- **Research needed:** Best practices for each variant's strengths (e.g., EGARCH for leverage effects, FIGARCH for long memory). Researcher should investigate when each variant dominates.

### Integration with position sizing
- **Blend approach:** Research best practice. User leans toward blend (weighted average of GARCH + existing estimators) and/or replace (GARCH as sole vol input), potentially with regime-switching (data must back this up). Build infrastructure to support all three modes.
- **Fallback on convergence failure:** Research best practice for handling GARCH non-convergence (common with short series or regime breaks). Candidate approaches: fall back to GK/Parkinson, carry forward last valid forecast with decay, widen confidence band, or block trading.
- **Risk engine scope:** Build all three options — (1) sizing-only, (2) sizing + risk limits, (3) sizing + advisory signal to risk — and test historically which is optimal and under what circumstances. Each may be optimal in different market conditions.
- **Blend weights:** Rolling accuracy weighting (inverse RMSE of each estimator vs realized vol over trailing window). Auto-weight, not static config.

### Forecast storage & refresh
- **Storage architecture:** Dedicated `garch_forecasts` table (PK includes id, venue_id, ts, tf, model_type, horizon) PLUS materialized view joining to features table for convenience
- **Re-fit cadence:** Research-driven decision — study best practices and let data determine optimal re-fit frequency (daily vs weekly vs monthly vs regime-triggered). Build infrastructure flexible enough to support any cadence.
- **Minimum history:** 126 days (6 months) — aggressive threshold to include newer but liquid assets. Accept that parameter estimates may be less stable for shorter series.
- **Diagnostics:** Separate `garch_diagnostics` table linked by model_run_id. Store AIC, BIC, convergence status, Ljung-Box p-value on standardized residuals. Keeps forecast table lean.

### Comparison methodology
- **Accuracy metrics:** All four — RMSE vs realized vol, QLIKE (quasi-likelihood, penalizes under-prediction), combined RMSE+QLIKE, and Mincer-Zarnowitz R² (calibration regression). Study all to determine which is most informative for this use case.
- **Evaluation window:** Both in-sample AND out-of-sample. In-sample shows fit quality, OOS shows generalization. Rolling OOS with expanding training window.
- **Granularity:** Per-asset AND aggregate (Phase 80 lesson — aggregation masks significant per-asset variation). Show which assets benefit most from GARCH vs simpler estimators.
- **Output format:** Both static report (markdown + CSV) AND Streamlit dashboard panel. Report for archival/comparison, dashboard for live monitoring.

### Claude's Discretion
- Exact GARCH library choice (arch package is standard, but researcher should confirm)
- Database schema details (column names, indexes, partitioning)
- Materialized view refresh strategy
- Dashboard panel layout and chart types
- Exact convergence criteria and max iterations for MLE
- How to handle assets where ALL four GARCH variants fail to converge

</decisions>

<specifics>
## Specific Ideas

- Log returns already exist in returns tables — no need to compute them. Pipeline should load directly.
- Phase 80 showed AMA features dominate active tier (18/20 active features are AMA-derived) — GARCH vol is complementary, providing a conditional vol dimension the AMA features don't capture.
- Per-asset variation was a key Phase 80 finding — comparison methodology MUST show per-asset results, not just aggregates.
- The rolling accuracy (inverse RMSE) weighting for blend is similar to the "forecast combination" literature — researcher should look at Timmermann (2006) or similar for best practices.
- User wants data-driven decisions for re-fit cadence, blend approach, and risk scope — these should produce testable hypotheses, not just opinions.

</specifics>

<deferred>
## Deferred Ideas

- Strategy-specific vol targeting (momentum vs mean-reversion use vol differently) — Phase 82/85
- Per-asset GARCH variant selection (auto-select best variant per asset) — could be Phase 81 stretch or future phase
- Intraday GARCH (sub-daily vol forecasting) — not in scope, daily/5-day horizons only
- GARCH-in-mean (volatility as return predictor) — interesting but separate from vol forecasting for sizing
- **Rolling vs expanding window comparison** — Phase 81 uses expanding window for OOS evaluation. Comparing rolling (fixed lookback) vs expanding windows is deferred to after initial results are available; can be added as a parameter to the evaluator in a future phase.
- **Log vs arithmetic returns comparison** — Phase 81 uses log returns (ret_log) for all GARCH fitting. Comparing log vs arithmetic input returns is deferred; the infrastructure supports swapping the column name, but the comparison is a research exercise for after the baseline is established.

</deferred>

---

*Phase: 81-garch-conditional-volatility*
*Context gathered: 2026-03-22*
