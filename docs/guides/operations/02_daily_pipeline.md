# Part 2: The Daily Pipeline

## Overview

The daily pipeline is the heart of ta_lab2. It transforms raw price data into actionable trading signals through a 21-stage Directed Acyclic Graph (DAG) (v1.2.0 extended; 15 stages in v1.0.0). Each stage depends on the output of earlier stages, and each stage has its own watermark system that enables incremental processing.

Understanding the pipeline is essential because everything else in the system -- research, paper trading, risk management, drift monitoring -- depends on the pipeline producing correct, fresh data.

**Key principle:** The pipeline is designed to be idempotent. You can run any stage multiple times without creating duplicates or corrupting data. Every write uses the PostgreSQL upsert pattern (temp table + `ON CONFLICT`), so re-runs are always safe.

---

## 2.1 Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     DAILY PIPELINE DAG (v1.2.0: 21 stages)                 │
│                                                                             │
│  Stage  1: BARS (2h)         Stage  2: EMAs (1h)     Stage  3: AMAs (1h)  │
│  Stage  4: DescStats (1h)    Stage  5: MacroFeats(5m) Stage  6: MacroReg  │
│  Stage  7: MacroAnalytics    Stage  8: CrossAsset     Stage  9: Regimes   │
│  Stage 10: Features (30m)    Stage 11: GARCH (30m)*   Stage 12: Signals  │
│  Stage 13: StopCalibration   Stage 14: Portfolio(10m)  Stage 15: Executor │
│  Stage 16: Drift (10m)**     Stage 17: IC Staleness   Stage 18: SigAnomaly│
│  Stage 19: PipelineLog       Stage 20: Stats/QC (1h)  Stage 21: Alerts   │
│                                                                             │
│  * GARCH is non-fatal with --continue-on-error (convergence failures OK)  │
│  ** Drift and Executor (stages 15-16) require --paper-start DATE           │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Reading the diagram:** Numbers show execution order (dependency order). The timeout annotation (e.g., "2h") is the maximum allowed execution time before the orchestrator kills the stage. Actual execution time is much shorter for incremental runs.

### Legacy DAG (v1.0.0, for reference)

In v1.0.0, the pipeline had 15 stages ending at Stats/QC. v1.2.0 added 6 stages:
- **Stage 11: GARCH Forecasts** -- volatility model fitting per asset
- **Stage 13: Stop Calibration** -- MAE/MFE-based stop ladder calibration
- **Stage 14: Portfolio Allocation** -- Black-Litterman MV/CVaR/HRP weights
- **Stage 17: IC Staleness Monitor** -- decay detection on ic_results
- **Stage 18: Signal Anomaly Gate** -- pre-execution z-score anomaly check
- **Stage 19: Pipeline Run Log** -- dead-man switch / daily run audit

### How Watermarks Work

Every data table has a companion `_state` table that tracks the last-processed timestamp per asset. For example:

- `price_bars_multi_tf` (data) → `price_bars_multi_tf_state` (watermark)
- `ema_multi_tf` (data) → `ema_multi_tf_state` (watermark)

When a stage runs, it:
1. Reads the watermark: "What was the last timestamp I processed for asset X?"
2. Queries source data for rows newer than the watermark
3. Computes derived values for only those new rows
4. Writes results using upsert (safe for re-runs)
5. Advances the watermark

This means a daily run only processes 1 day of new data, not the entire history. First runs (no watermark) process everything and can take significantly longer.

### Dependency Chain in Detail

```
Raw Prices (cmc_price_histories7)
  └─► Bars (price_bars_multi_tf)
        ├─► EMAs (ema_multi_tf, 7 periods x N timeframes)
        │     └─► AMA values + returns
        ├─► Bar Returns (returns_bars_multi_tf)
        ├─► Descriptive Stats (asset_stats)
        └─► Features (features, 112 columns)
              └─► Signals (signals_ema_crossover, _rsi_mean_revert, _atr_breakout)
                    └─► Executor (orders, fills, positions)
                          └─► Drift Monitor (drift_metrics)

FRED Data (fred.series_values)
  └─► Macro Features (fred.macro_features)
        └─► Macro Regimes (cmc_macro_regime_history)
              └─► Macro Analytics (HMM states, transition probabilities)
                    └─► Cross-Asset Aggregation (cross_asset_corr)
```

---

## 2.2 The Full Pipeline Command

The `run_daily_refresh.py` orchestrator runs all stages in the correct dependency order. It is the command you will use most often.

### Basic Usage

```bash
# Standard daily refresh (all assets, all stages)
python -m ta_lab2.scripts.run_daily_refresh --all --ids all

# With paper trading and drift monitoring
# The --paper-start flag tells the drift monitor when paper trading began
python -m ta_lab2.scripts.run_daily_refresh --all --ids all --paper-start 2025-01-01

# Continue on errors (recommended for production)
# If one asset fails, the pipeline continues with remaining assets
python -m ta_lab2.scripts.run_daily_refresh --all --ids all --continue-on-error --verbose

# Specific assets only (comma-separated asset IDs)
python -m ta_lab2.scripts.run_daily_refresh --all --ids 1,52,825,1027

# Dry run (shows stages but writes nothing)
python -m ta_lab2.scripts.run_daily_refresh --all --ids 1 --dry-run
```

### The `--continue-on-error` Flag

Use `--continue-on-error` in production to let the pipeline proceed even when individual stages fail:

```bash
python -m ta_lab2.scripts.run_daily_refresh --all --ids all \
    --paper-start 2026-03-24 --continue-on-error
```

**Behavior:** If a non-fatal stage (e.g., GARCH convergence failure, IC staleness check) fails, the pipeline logs the error, marks the stage as failed, and continues to the next stage. The final pipeline run log captures which stages succeeded and which failed. Fatal errors (e.g., bars failing) still stop the pipeline.

**Note:** `--paper-start DATE` is REQUIRED for drift monitoring (Stage 16) to run. Without it, the drift stage is skipped silently.

### Understanding `--all` vs Individual Flags

The `--all` flag runs every stage. Without it, you can select individual stages:

```bash
# Only run bars and EMAs
python -m ta_lab2.scripts.run_daily_refresh --bars --emas --ids all

# Run everything except macro stages (useful if FRED data is not synced)
python -m ta_lab2.scripts.run_daily_refresh --all --no-macro --no-macro-regimes \
    --no-macro-analytics --no-cross-asset-agg --ids all
```

### When to Use Individual Stages

- **After loading new price data:** `--bars --ids <new_asset_id>` (just rebuild bars)
- **After FRED sync:** `--macro --macro-regimes` (just refresh macro stages)
- **Quick signal check:** `--signals --ids all` (just regenerate signals from existing features)
- **Debugging a single asset:** `--all --ids 1 --verbose` (full pipeline, one asset, max logging)

---

## 2.3 Stage-by-Stage Reference

### Stage 1: Bars (Timeout: 2 hours)

**What it does:** Transforms raw daily OHLCV from `cmc_price_histories7` into multi-timeframe bars. The builder creates rolling windows (7d, 14d, 30d, 90d, 200d), calendar-aligned bars (ISO and US conventions), and anchor-aligned snapshots (week-to-date, month-to-date, year-to-date).

**Why multiple bar types?** Different analysis requires different alignment. Rolling bars are smoothly overlapping and good for indicator computation. Calendar bars align to human-meaningful boundaries (Monday-Friday weeks, calendar months). Anchor bars tell you "how is this asset performing so far this month?"

**Builders (in execution order):**
1. `1d` -- Canonical daily bars from CoinMarketCap
2. `1d_tvc` -- Daily bars from TradingView (if TVC data loaded)
3. `vwap` -- VWAP-consolidated bars (merges overlapping sources)
4. `multi_tf` -- Rolling bars (7d through 200d)
5. `cal_iso` -- Calendar-aligned (ISO week = Monday start)
6. `cal_us` -- Calendar-aligned (US convention = Sunday start)
7. `cal_anchor_iso` -- Partial snapshots: WTD, MTD, QTD, YTD (ISO)
8. `cal_anchor_us` -- Partial snapshots: WTD, MTD, QTD, YTD (US)

```bash
# Run bars only
python -m ta_lab2.scripts.run_daily_refresh --bars --ids all

# Run specific builders (comma-separated)
python -m ta_lab2.scripts.bars.run_all_bar_builders --ids all --builders 1d,multi_tf

# Skip calendar-anchor builders (saves time when you don't need WTD/MTD)
python -m ta_lab2.scripts.bars.run_all_bar_builders --ids all --skip cal_anchor_iso,cal_anchor_us

# Full rebuild (ignores watermarks, recomputes from scratch)
python -m ta_lab2.scripts.bars.run_all_bar_builders --ids all --full-rebuild

# Use 8 parallel workers (speed up multi-asset runs)
python -m ta_lab2.scripts.bars.run_all_bar_builders --ids all --num-processes 8
```

**Verify:**
```sql
-- Check bar counts per timeframe for BTC
SELECT tf, count(*) as rows, min(ts) as earliest, max(ts) as latest
FROM price_bars_multi_tf
WHERE id = 1
GROUP BY tf
ORDER BY tf;

-- Check watermarks (shows last-processed timestamp per asset)
SELECT * FROM price_bars_multi_tf_state WHERE id = 1;
```

---

### Stage 2: EMAs (Timeout: 1 hour)

**What it does:** Computes Exponential Moving Averages across all assets and timeframes. Seven standard periods are computed: 5, 9, 10, 21, 50, 100, 200. EMAs are computed on closing prices and then derivative values (d1 = first difference, d2 = second difference, plus rolling variants) are calculated.

**Why these periods?** They represent short-term (5, 9, 10), medium-term (21, 50), and long-term (100, 200) trends. EMA crossovers between different periods are used by signal generators to detect trend changes.

**Refreshers:**
1. `multi_tf` -- EMAs on rolling bars
2. `cal` -- EMAs on calendar-aligned bars (US + ISO)
3. `cal_anchor` -- EMAs on anchor-aligned bars

```bash
# Run EMAs only
python -m ta_lab2.scripts.run_daily_refresh --emas --ids all

# Specific refreshers only
python -m ta_lab2.scripts.emas.run_all_ema_refreshes --ids all --only multi_tf

# Custom periods (override the standard 7)
python -m ta_lab2.scripts.emas.run_all_ema_refreshes --ids all --periods 10,21,50

# Use period lookup table (recommended -- ensures consistency)
python -m ta_lab2.scripts.emas.run_all_ema_refreshes --ids all --periods lut

# Full refresh (ignore state, recompute all)
python -m ta_lab2.scripts.emas.run_all_ema_refreshes --ids all --full-refresh

# With post-refresh validation (checks data integrity after write)
python -m ta_lab2.scripts.emas.run_all_ema_refreshes --ids all --validate

# Alert on validation errors via Telegram
python -m ta_lab2.scripts.emas.run_all_ema_refreshes --ids all --validate --alert-on-validation-error
```

**Bar Freshness Check:** EMAs check that bars are fresh (< 48 hours old by default). If bars are stale, EMAs refuse to compute to avoid building on outdated data. Override this safety check with:
```bash
python -m ta_lab2.scripts.run_daily_refresh --emas --skip-stale-check
python -m ta_lab2.scripts.run_daily_refresh --emas --staleness-hours 72
```

**Verify:**
```sql
SELECT tf, period, count(*) as rows, max(ts) as latest
FROM ema_multi_tf_u
WHERE id = 1
GROUP BY tf, period
ORDER BY tf, period;
```

**GOTCHA:** Column names in `ema_multi_tf_u` are `d1`, `d2`, `d1_roll`, `d2_roll` (NOT `ema_d1`, NOT `ema_d2`). This is a historical naming choice that has been preserved for backwards compatibility with existing queries.

---

### Stage 3: AMAs (Timeout: 1 hour)

**What it does:** Computes Adaptive Moving Averages -- indicators that adjust their smoothing speed based on market conditions. This is the largest table family (~91M rows when fully populated), because it computes 4 indicator types (KAMA, DEMA, TEMA, HMA) across all assets and timeframes.

**The four AMA types:**
- **KAMA** (Kaufman Adaptive): Adapts to market noise -- fast in trending markets, slow in range-bound markets
- **DEMA** (Double EMA): Reduces lag by applying EMA twice
- **TEMA** (Triple EMA): Further lag reduction via triple application
- **HMA** (Hull MA): Designed to eliminate lag while maintaining smoothness

```bash
# Run AMAs for all assets and timeframes
python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs

# KAMA only (fastest subset)
python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --indicators KAMA

# Specific refreshers
python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --only multi_tf,cal

# Full rebuild (WARNING: can take hours for all assets)
python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs --full-rebuild
```

**Pipeline stages within AMA refresh:**
```
AMA values (multi_tf, cal, cal_anchor)
    → AMA returns (all sources)
    → _u sync (values → ama_multi_tf_u)
    → _u sync (returns → returns_ama_multi_tf_u)
    → Z-scores (standardized values for cross-asset comparison)
```

**WARNING:** A full AMA rebuild for all assets is the longest single operation in the system. For 7 assets across all timeframes and indicators, expect 2-4 hours. Incremental runs are fast (seconds to minutes).

---

### Stage 4: Descriptive Stats (Timeout: 1 hour)

**What it does:** Refreshes `asset_stats` (rolling descriptive statistics) and `cross_asset_corr` (correlation matrices). These tables power the Asset Stats and correlation heatmap pages in the dashboard.

```bash
python -m ta_lab2.scripts.run_daily_refresh --desc-stats --ids all
```

---

### Stage 5: Macro Features (Timeout: 5 min)

**What it does:** Transforms raw FRED series into derived features: net liquidity, rate spreads, VIX regime, dollar strength, credit stress, carry trade indicators, M2 growth, Fed policy regime, CPI surprise. These features live in `fred.macro_features` (18 raw FRED series → 14 derived columns).

**Prerequisite:** FRED data must be synced from the GCP VM first (see Part 5). If FRED data is not available, this stage produces empty output but does not fail.

```bash
# Incremental refresh (only new dates)
python -m ta_lab2.scripts.macro.refresh_macro_features

# Full history rebuild
python -m ta_lab2.scripts.macro.refresh_macro_features --full

# Dry run (show what would be computed)
python -m ta_lab2.scripts.macro.refresh_macro_features --dry-run --verbose

# Custom date range
python -m ta_lab2.scripts.macro.refresh_macro_features --start-date 2020-01-01 --end-date 2026-01-01

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-macro
```

---

### Stage 6: Macro Regimes (Timeout: 5 min)

**What it does:** Classifies the macro environment along 4 dimensions, producing a composite regime label used by the risk engine's macro gates and by the portfolio optimizer for allocation adjustment.

**The 4 dimensions:**
- **Monetary Policy:** Cutting / Neutral / Hiking (from Fed Funds Rate and target range)
- **Liquidity:** Expanding / Stable / Contracting (from net liquidity = Fed balance - TGA - RRP)
- **Risk Appetite:** RiskOn / Neutral / RiskOff (from VIX, credit spreads, financial conditions)
- **Carry:** Stable / Elevated / Unwind (from JPY carry trade z-scores)

```bash
# Default profile
python -m ta_lab2.scripts.macro.refresh_macro_regimes

# Conservative profile (wider thresholds -- less sensitive to regime changes)
python -m ta_lab2.scripts.macro.refresh_macro_regimes --profile conservative

# Aggressive profile (tighter thresholds -- more responsive)
python -m ta_lab2.scripts.macro.refresh_macro_regimes --profile aggressive

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-macro-regimes
```

**Regime Composite Format:** `Monetary-Liquidity-Risk-Carry`
Example: `Cutting-Expanding-RiskOn-Stable` = favorable environment for risk assets.

**Bucketed Macro State and Trading Impact:**

| State | Meaning | Trading Impact |
|-------|---------|----------------|
| Favorable | Rate cuts + expanding liquidity + risk-on | Full allocation allowed |
| Constructive | Mixed but positive bias | Normal allocation |
| Neutral | No strong signal | Default allocation |
| Cautious | Tightening or risk-off signals | Reduced allocation |
| Adverse | Rate hikes + contracting + risk-off + carry unwind | Minimal/zero allocation |

---

### Stage 7: Macro Analytics (Timeout: 15 min)

**What it does:** Fits Hidden Markov Models to macro feature time series, computes regime transition probabilities, and runs lead-lag analysis between macro indicators and crypto returns.

```bash
python -m ta_lab2.scripts.macro.run_macro_analytics

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-macro-analytics
```

---

### Stage 8: Cross-Asset Aggregation (Timeout: 10 min)

**What it does:** Computes cross-asset correlation matrices, aggregates funding rate data, and calculates crypto-macro comovement scores. The output drives the cross-asset correlation heatmap in the dashboard and informs portfolio diversification decisions.

```bash
python -m ta_lab2.scripts.cross_asset.run_cross_asset_agg

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-cross-asset-agg
```

---

### Stage 9: Regimes (Timeout: 30 min)

**What it does:** Classifies each asset's price trend into L0 (Bull/Bear/Neutral), L1 (sub-regimes like Early Bull, Late Bear), and L2 (micro-structure regimes). Uses EMA-based signals with hysteresis smoothing to prevent noisy regime flips.

**Why hysteresis?** Without it, regimes can oscillate rapidly when the asset is near a boundary. Hysteresis requires a regime to hold for a minimum number of bars before it is confirmed, reducing false signals.

```bash
# All assets
python -m ta_lab2.scripts.regimes.refresh_regimes --all

# Specific assets
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1,52,825

# Without hysteresis (raw labels -- useful for research)
python -m ta_lab2.scripts.regimes.refresh_regimes --all --no-hysteresis

# Custom minimum hold bars (default is 3)
python -m ta_lab2.scripts.regimes.refresh_regimes --all --min-hold-bars 5

# Inspect regime timeline for an asset
python -m ta_lab2.scripts.regimes.regime_inspect --id 1

# Dry run with verbose output
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1 --dry-run -v
```

**Verify:**
```sql
-- Check latest regime labels
SELECT id, ts, l0_label, l1_label, l2_label
FROM regimes
WHERE id = 1
ORDER BY ts DESC LIMIT 10;

-- Check regime transitions (when did regimes change?)
SELECT * FROM regime_flips WHERE id = 1 ORDER BY ts DESC LIMIT 5;
```

---

### Stage 10: Features (Timeout: 30 min)

**What it does:** Computes the 112-column `features` table. This is the primary feature store used by ML models, IC analysis, and signal generators.

**Feature categories (112 columns):**
- **Returns:** Arithmetic, log, realized (multiple horizons)
- **Volatility:** Close-to-close, Parkinson, Garman-Klass, Yang-Zhang, rolling windows
- **Momentum:** RSI(14), MACD (line, signal, histogram), rate of change
- **Moving Averages:** SMA/EMA ratios, MA slope
- **Volume:** Volume ratio, dollar volume, volume profile
- **ATR:** Average True Range (multiple periods)
- **Microstructure:** Range-to-volume, bar-range, close position in range

**Refresh order (respects internal dependencies):**
1. `vol` (depends on bars)
2. `ta` (depends on bars)
3. `features` (depends on vol + ta + EMAs + returns)
4. Cross-section normalizations

```bash
# All assets, 1D timeframe
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D

# All assets, all timeframes
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --all-tfs

# With codependence analysis (pairwise feature correlations, ~3 min extra)
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D --codependence

# Full refresh (rebuild from scratch)
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D --full-refresh

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-features
```

---

### Stage 11: Signals (Timeout: 30 min)

**What it does:** Generates trading signals from 3 generators. Each generator reads features and regimes, applies its logic, and writes signal rows with direction (long/short/flat) and strength (0-1).

**Signal generators:**
1. **EMA Crossover:** Fast EMA crosses above/below slow EMA → buy/sell
2. **RSI Mean Revert:** RSI below 30 → buy (oversold), RSI above 70 → sell (overbought)
3. **ATR Breakout:** Price breaks above/below ATR-based channel → trend continuation signal

```bash
# Default: incremental refresh with validation
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Full refresh (regenerate all signals)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --full-refresh

# Validate only (check signal integrity, no generation)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --validate-only

# Specific assets
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --ids 1 2 3

# Without regime context (signals ignore current regime)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --no-regime
```

**Verify:**
```sql
SELECT * FROM signals_ema_crossover WHERE id = 1 ORDER BY ts DESC LIMIT 5;
SELECT * FROM signals_rsi_mean_revert WHERE id = 1 ORDER BY ts DESC LIMIT 5;
SELECT * FROM signals_atr_breakout WHERE id = 1 ORDER BY ts DESC LIMIT 5;
```

---

### Stage 12: Portfolio (Timeout: 10 min)

**What it does:** Runs portfolio optimization (Mean-Variance, CVaR, or HRP), optional Black-Litterman adjustment, and bet sizing. The output determines how much capital to allocate to each strategy/asset combination.

```bash
# Skip in pipeline (often not needed for daily runs)
python -m ta_lab2.scripts.run_daily_refresh --all --no-portfolio
```

---

### Stage 13: Executor (Timeout: 5 min)

**What it does:** The paper executor reads unprocessed signals, sizes positions based on executor config, routes through the 7-gate risk engine, simulates fills with configurable slippage, and records everything to the database. See Part 4 for full details.

```bash
# Run executor
python -m ta_lab2.scripts.executor.run_paper_executor

# Dry run (see what would happen, no DB writes)
python -m ta_lab2.scripts.executor.run_paper_executor --dry-run --verbose

# Replay historical signals (for backtest parity verification)
python -m ta_lab2.scripts.executor.run_paper_executor --replay-historical \
    --start 2024-01-01 --end 2025-01-01

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-execute
```

---

### Stage 14: Drift Monitor (Timeout: 10 min)

**What it does:** Compares paper trading PnL against a "perfect" backtest replay to detect execution decay. Requires `--paper-start` to know when paper trading began.

```bash
python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01

# Dry run
python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01 --dry-run

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-drift
```

---

---

### v1.2.0 Extended Stages (Stages 11, 13-14, 17-21)

The following stages were added in v1.2.0 and run when `--all` is used. They fit between the original stages as follows: GARCH (after Features), Stop Calibration and Portfolio Allocation (after Signals), and IC Staleness / Signal Anomaly / Pipeline Log / Alerts (after Stats/QC).

#### Stage 11 (v1.2.0): GARCH Forecasts (Timeout: 30 min)

**What it does:** Fits 4 GARCH model variants per asset (GARCH, EGARCH, GJR-GARCH, FIGARCH) on daily bar returns, then blends them into a single daily volatility forecast. Forecasts are written to two tables:
- `garch_forecasts` -- per-asset daily vol forecast (blended + per-variant)
- `garch_diagnostics` -- convergence status, AIC/BIC, log-likelihood per model run

**Why 4 variants?** Different market regimes are better captured by different models. EGARCH captures asymmetric volatility (bad news increases vol more than good news). FIGARCH captures long-memory volatility (clustering persists for weeks). The blend weights are updated based on out-of-sample RMSE.

**Carry-forward fallback:** If a model fails to converge (common for assets with short history or extreme price gaps), the prior day's forecast is carried forward with exponential decay (half-life = 5 days). If no prior forecast exists, a Garman-Klass 21-bar estimate is used.

```bash
# Run GARCH forecasts only
python -m ta_lab2.scripts.garch.refresh_garch_forecasts --ids all

# With continue-on-error (individual asset failures are non-fatal)
python -m ta_lab2.scripts.garch.refresh_garch_forecasts --ids all --continue-on-error

# Specific assets only
python -m ta_lab2.scripts.garch.refresh_garch_forecasts --ids 1,52,825

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-garch
```

**Troubleshooting GARCH:**
- "Convergence failed" logged at WARNING level -- expected for illiquid or new assets; carry-forward activates automatically.
- "FIGARCH requires 200+ observations" -- normal for new assets; FIGARCH is skipped, others fit normally.
- If ALL variants fail for an asset: check for gaps in `returns_bars_multi_tf_u`. Missing returns rows prevent GARCH fitting.

**Verify:**
```sql
-- Check GARCH forecast coverage
SELECT id, count(*) as forecast_days, max(ts) as latest
FROM garch_forecasts
GROUP BY id
ORDER BY latest DESC LIMIT 10;

-- Check convergence health
SELECT id, model_type, converged, count(*) as runs
FROM garch_diagnostics
WHERE run_date >= CURRENT_DATE - 7
GROUP BY id, model_type, converged
ORDER BY id, model_type;
```

---

#### Stage 13 (v1.2.0): Stop Calibration (Timeout: 5 min)

**What it does:** Uses historical MAE/MFE (Maximum Adverse/Favorable Excursion) data from backtests to calibrate stop-loss and take-profit ladder tiers. Results are written to `stop_calibrations` with a 3-tier stop ladder and 2-tier take-profit configuration.

**Source data:** Reads from `strategy_bakeoff_results` (bakeoff winners from Phase 82 strategy evaluation). Uses the CPCV cross-validated results to compute MAE/MFE percentiles per asset and strategy combination.

```bash
# Run stop calibration
python -m ta_lab2.scripts.portfolio.calibrate_stops

# Dry run (see what would be written)
python -m ta_lab2.scripts.portfolio.calibrate_stops --dry-run

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-stop-calibration
```

**Verify:**
```sql
SELECT strategy_id, asset_id, sl_pct_tier1, sl_pct_tier2, sl_pct_tier3,
       tp_pct_tier1, tp_pct_tier2, calibrated_at
FROM stop_calibrations
ORDER BY calibrated_at DESC LIMIT 10;
```

---

#### Stage 14 (v1.2.0): Portfolio Allocation (Timeout: 10 min)

**What it does:** Runs Black-Litterman portfolio optimization, combining a market cap prior with IC-IR-weighted signals views. Produces allocations using 3 optimization methods (MV = Mean-Variance, CVaR, HRP = Hierarchical Risk Parity). Results written to `portfolio_allocations`.

**Black-Litterman views:** Derived from `ic_results` (IC-IR per feature per asset). Features with higher IC-IR get higher view confidence. If `ic_results` is empty for a timeframe, the optimizer falls back to prior-only (equal-weight with market cap adjustment).

**Prerequisite:** Requires `ic_results` to be populated (Phase 80 feature selection sweep). For daily incremental runs, the `ic_results` table is updated incrementally by the IC staleness monitor.

```bash
# Run portfolio allocation
python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations

# With specific optimization method
python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --method mv

# Dry run
python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --dry-run

# Skip in pipeline
python -m ta_lab2.scripts.run_daily_refresh --all --no-portfolio
```

**Verify:**
```sql
SELECT method, count(*) as assets, sum(weight) as total_weight, max(allocated_at) as latest
FROM portfolio_allocations
GROUP BY method
ORDER BY latest DESC;
```

---

### Stage 15: Stats/QC (Timeout: 1 hour)

**What it does:** Runs 6 quality-check runners that verify data integrity across all pipeline tables. Each runner examines specific quality dimensions: gap detection, freshness, OHLC integrity, row count consistency, and cross-table agreement.

**The 6 runners:**
1. Price bars stats (gap detection, freshness, OHLC validity)
2. EMA multi-TF stats (period count, coverage)
3. EMA calendar stats (alignment correctness)
4. EMA calendar-anchor stats (anchor date validity)
5. Returns EMA stats (return calculation integrity)
6. CMC features stats (null ratio, value range checks)

```bash
# Run all stats
python -m ta_lab2.scripts.stats.run_all_stats_runners

# Full refresh (ignore watermarks, recheck everything)
python -m ta_lab2.scripts.stats.run_all_stats_runners --full-refresh

# Verbose (see individual test results)
python -m ta_lab2.scripts.stats.run_all_stats_runners --verbose
```

**IMPORTANT:** Stats runners exit code 0 even when they detect FAILs. The orchestrator queries the DB after all runners complete to check for FAIL rows. Always verify via SQL:

```sql
-- Check for any FAILs across all stats tables
SELECT table_name, test_name, status, message, checked_at
FROM (
    SELECT 'bars' as table_name, test_name, status, message, checked_at
      FROM price_bars_multi_tf_stats WHERE status = 'FAIL'
    UNION ALL
    SELECT 'ema', test_name, status, message, checked_at
      FROM ema_multi_tf_stats WHERE status = 'FAIL'
    UNION ALL
    SELECT 'features', test_name, status, message, checked_at
      FROM features_stats WHERE status = 'FAIL'
) failed
ORDER BY checked_at DESC;
```

---

## 2.4 Weekly Operations

### Weekly QC Digest

The weekly digest aggregates all PASS/WARN/FAIL counts across the week, computes week-over-week delta, and optionally sends the summary to Telegram.

```bash
# Print to stdout + send to Telegram
python -m ta_lab2.scripts.stats.weekly_digest

# Print only (no Telegram)
python -m ta_lab2.scripts.stats.weekly_digest --no-telegram

# Via orchestrator
python -m ta_lab2.scripts.run_daily_refresh --weekly-digest
```

**What a healthy weekly digest looks like:**
```
Weekly QC Digest (2026-02-24 to 2026-03-02)
============================================
PASS:  147 (+3 vs last week)
WARN:    4 (-1 vs last week)
FAIL:    0 (unchanged)
```

Any FAIL count > 0 requires investigation. WARNings are typically stale data for weekly/monthly FRED series (expected) or assets with thin trading history.

### Weekly Drift Report

If you are paper trading, the drift report compares paper execution against backtest replay:

```bash
# Standard weekly report (generates Markdown + Plotly charts)
python -m ta_lab2.scripts.drift.run_drift_report

# Custom date range
python -m ta_lab2.scripts.drift.run_drift_report --week-start 2025-02-24 --week-end 2025-03-02

# With 6-source attribution decomposition (more compute, more detail)
python -m ta_lab2.scripts.drift.run_drift_report --with-attribution

# Custom output directory
python -m ta_lab2.scripts.drift.run_drift_report --output-dir reports/drift/week10
```

**Output files:**
- `reports/drift/V1_REPORT.md` -- Markdown summary with key metrics
- `reports/drift/V1_REPORT_*.html` -- 5 Plotly interactive charts (equity curve, TE over time, slippage distribution, attribution waterfall, PnL comparison)

---

## 2.5 Pipeline Configuration Reference

### Skip Flags

| Flag | Stage Skipped | When to Use |
|------|--------------|-------------|
| `--no-macro` | FRED macro feature refresh | FRED data not synced |
| `--no-macro-regimes` | Macro regime classification | Skipping macro analysis |
| `--no-macro-analytics` | HMM + lead-lag analytics | Faster daily runs |
| `--no-cross-asset-agg` | Cross-asset aggregation | Single-asset testing |
| `--no-features` | features refresh | Features already current |
| `--no-garch` | GARCH forecast refresh (v1.2.0) | Faster runs when vol forecasts not needed |
| `--no-stop-calibration` | Stop calibration (v1.2.0) | No bakeoff results available |
| `--no-portfolio` | Portfolio allocation (v1.2.0) | No portfolio optimization needed |
| `--no-execute` | Paper executor | Not paper trading yet |
| `--no-drift` | Drift monitor | Not monitoring drift |

### Timeout Reference

| Stage | Default Timeout | First Run | Incremental | Notes |
|-------|----------------|-----------|-------------|-------|
| Bars | 7,200s (2h) | 5-15 min | 1-2 min | Scales with # assets |
| EMAs | 3,600s (1h) | 3-10 min | < 1 min | 7 periods x N timeframes |
| AMAs | 3,600s (1h) | 30-240 min | 1-5 min | 91M+ rows total |
| Desc Stats | 3,600s (1h) | 2-5 min | < 1 min | Rolling window computation |
| Macro Features | 300s (5m) | < 1 min | < 1 min | Small table |
| Macro Regimes | 300s (5m) | < 1 min | < 1 min | Classification only |
| Macro Analytics | 900s (15m) | 5-10 min | 2-5 min | HMM fitting is CPU-intensive |
| Cross-Asset | 600s (10m) | 2-5 min | < 1 min | Correlation matrices |
| Regimes | 1,800s (30m) | 2-5 min | < 1 min | L0-L2 with proxy inference |
| Features | 1,800s (30m) | 5-10 min | 1-2 min | 112 columns |
| **GARCH (v1.2.0)** | **1,800s (30m)** | **5-30 min** | **1-5 min** | **Non-fatal; carry-forward on convergence failure** |
| Signals | 1,800s (30m) | 2-5 min | < 1 min | 3 generators |
| **Stop Calibration (v1.2.0)** | **300s (5m)** | **< 1 min** | **< 1 min** | **Non-fatal with --continue-on-error** |
| **Portfolio Allocation (v1.2.0)** | **600s (10m)** | **1-2 min** | **< 1 min** | **Black-Litterman MV/CVaR/HRP** |
| Executor | 300s (5m) | < 1 min | < 1 min | Signal scan + fill sim; requires --paper-start |
| Drift | 600s (10m) | 1-2 min | < 1 min | Backtest replay; requires --paper-start |
| Stats/QC | 3,600s (1h) | 5-10 min | 1-2 min | 6 runners |
| **IC Staleness Monitor (v1.2.0)** | **120s (2m)** | **< 1 min** | **< 1 min** | **Returns 0/1/2 (0=clean, 1=decay, 2=missing)** |
| **Signal Anomaly Gate (v1.2.0)** | **120s (2m)** | **< 1 min** | **< 1 min** | **Exit 2 = blocked (hard gate); exit 0 = clean** |
| **Pipeline Run Log (v1.2.0)** | **30s** | **< 1 min** | **< 1 min** | **Records stage completion audit to pipeline_run_log** |

### What to Do When a Stage Fails

1. **Check the error message.** The orchestrator prints which stage failed and the exception.
2. **Re-run the failing stage individually** with `--verbose` for detailed logging.
3. **Check watermarks.** If watermarks are corrupted, use `--full-rebuild` on the failing stage.
4. **Check upstream data.** If features fail, check that bars and EMAs are current. If signals fail, check that features exist.
5. **Check for resource issues.** AMA full-rebuilds can exhaust memory on machines with < 8GB RAM.
6. **Use `--continue-on-error`** in production to let the pipeline finish other assets even when one fails.
