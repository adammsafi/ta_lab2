# Phase 8: ta_lab2 Signals - Context

**Gathered:** 2026-01-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Build signal generation system producing trading signals (EMA crossovers, RSI mean reversion, ATR breakout) from cmc_daily_features and enable reproducible backtesting with comprehensive PnL metrics. Signals are stored in the database with full feature context, enabling historical analysis and backtest validation.

Scope: Signal generation, database storage, backtest integration v1, reproducibility validation. Optimization and Monte Carlo extensions are future phases.

</domain>

<decisions>
## Implementation Decisions

### Existing Infrastructure to Leverage

**Signal functions already exist:**
- `src/ta_lab2/signals/ema_trend.py` — EMA crossover with filters
- `src/ta_lab2/signals/rsi_mean_revert.py` — RSI mean reversion with thresholds
- `src/ta_lab2/signals/breakout_atr.py` — ATR breakout (skeleton exists)
- `src/ta_lab2/signals/registry.py` — Strategy registry pattern
- `src/ta_lab2/signals/generator.py` — Signal generation utilities
- `src/ta_lab2/signals/position_sizing.py` — Volatility-based sizing

**Backtest infrastructure already exists:**
- `src/ta_lab2/backtests/orchestrator.py` — run_multi_strategy orchestration
- `src/ta_lab2/backtests/vbt_runner.py` — vectorbt-based backtest engine
- `src/ta_lab2/backtests/costs.py` — CostModel for fees/slippage
- `src/ta_lab2/backtests/splitters.py` — Train/test split utilities
- `src/ta_lab2/backtests/reports.py` — Performance metric reporting

**Phase 8 focus:** Connect existing signal functions to database storage, integrate with cmc_daily_features, ensure reproducibility.

### Signal Storage Schema

- **Separate tables per signal type** (not unified cmc_signals_daily)
- Tables: `cmc_signals_ema_crossover`, `cmc_signals_rsi_mean_revert`, `cmc_signals_atr_breakout`
- Type-specific columns enable signal-specific parameters without schema bloat
- Each table follows pattern: (id, ts, signal_id, direction, state, feature snapshot, metadata)

### Signal Configuration

- **Database-driven configuration via dim_signals table** (like dim_indicators for TA features)
- Signal parameters stored as JSONB for flexibility
- Enables changing signal parameters without code changes
- Example: RSI thresholds (30/70, 25/75, etc.) configurable per signal_id
- EMA crossover pairs loaded from dim_signals (not hardcoded)

### Signal Output Capture

- **Full context (signal + feature snapshot)** stored for each signal event
- Signal tables include:
  - Core signal data: id, ts, signal_id, direction (long/short), state (open/closed)
  - Feature snapshot: close, relevant EMAs, RSI, ATR, vol metrics used in signal generation
  - Entry/exit tracking: entry_price, entry_ts, exit_price, exit_ts, pnl_pct
  - Metadata: signal_version, feature_version_hash, params_used (JSONB)
- Self-contained records enable backtest without reconstructing features
- Larger storage but complete audit trail

### Signal State Management

- **Stateful signals** tracking position lifecycle
- Signal rows track: position_state (open/closed/pending), entry/exit pairs
- Each signal has entry event (opens position) and exit event (closes position)
- Backtest engine can use state directly without reconstructing position history
- More complex signal generation but self-documenting and easier to audit

### Signal Refresh Strategy

- **Both incremental and full refresh supported:**
  - **Incremental (default):** CLI flag controls mode, state tracking via SignalStateManager
  - **Auto-detect dirty window:** Script checks cmc_daily_features watermark, auto-decides if full recalc needed
- Incremental refresh: Only compute signals for new feature data (efficient daily updates)
- Full refresh triggered when: --full-refresh flag OR cmc_daily_features major version change
- State manager tracks last_signal_ts per (id, signal_type, signal_id)

### Signal Architecture

- **Claude's discretion:** Decide whether to follow BaseFeature pattern or use signal-specific architecture
- Signals have different needs than features (state tracking, entry/exit pairs, position lifecycle)
- May warrant different abstraction than features
- Consider: BaseSignal class vs extending existing signals/generator.py utilities

### Data Quality Assumptions

- **No pre-validation of features before signal generation**
- Assumes features validated by FeatureValidator in Phase 7
- Signal generation trusts cmc_daily_features data quality
- If signals behave unexpectedly, user investigates features separately

### Signal Types and Parameters

**EMA Crossover:**
- **Multiple EMA pairs loaded from dim_signals table**
- Not hardcoded — query active pairs from database configuration
- Examples: 9/21 (short-term), 50/200 (long-term), custom pairs user defines
- Leverage existing ema_trend.py adapter logic

**RSI Mean Reversion:**
- **Configurable thresholds via dim_signals** (not hardcoded 30/70)
- Support for dynamic/adaptive thresholds:
  - Per-asset calibration (asset-specific thresholds based on historical RSI)
  - Rolling window adaptation (thresholds adjust based on recent behavior)
  - Volatility regime detection (different thresholds for high/low vol regimes)
- **All adaptive approaches built for Phase 8, will need testing and calibration**
- User will test data to determine which approach works best per asset/market
- Leverage existing rsi_mean_revert.py adapter logic

**ATR Breakout:**
- **Combination approach OR Claude's discretion**
- Options: Price move > N * ATR AND/OR Bollinger Band break
- User will need to test data to determine best definition
- Leverage existing breakout_atr.py skeleton
- Uses cmc_daily_features columns: atr_14, bb_up_20_2, bb_lo_20_2

### Backtest Integration

**PnL Calculation:**
- **Both modes available:**
  - Clean mode: PnL = (exit - entry) / entry (no fees, no slippage)
  - Realistic mode: PnL includes fees and slippage from CostModel
- CLI flag controls mode (--clean-pnl vs --realistic-pnl)
- Enables comparing signal quality (clean) vs practical returns (realistic)
- Leverage existing backtests/costs.py CostModel

**Position Sizing:**
- **Build support for all sizing methods, most likely configurable via CLI:**
  - Fixed percentage of capital (e.g., 10% per trade)
  - Risk-based sizing (Kelly criterion)
  - Equal dollar amount per trade
  - Volatility-aware sizing (existing position_sizing.py)
- CLI flag controls sizing method selection
- Future: Monte Carlo simulations and optimizations build on this foundation
- Leverage existing signals/position_sizing.py utilities

**Performance Metrics:**
- **Comprehensive metrics** (not just basic)
- Include all standard quant metrics:
  - Return, Sharpe ratio, Sortino ratio, Calmar ratio, max drawdown
  - Win rate, profit factor, average win/loss
  - Trade distribution, holding periods, trade count
- Leverage existing backtests/reports.py or extend as needed
- Metrics stored with backtest results for historical tracking

**Backtest Results Storage:**
- **Cache results in database** (not compute-only)
- Tables: `cmc_backtest_runs`, `cmc_backtest_trades`, `cmc_backtest_metrics`
- Enables historical backtest tracking
- Faster reruns (cached trades, recompute metrics on-demand)
- Stores: backtest_id, signal_type, signal_params_hash, run_timestamp, metrics

### Reproducibility Requirements

**Determinism:**
- **Comprehensive reproducibility: timestamp queries + seed tracking + versioning**
- Timestamp-based queries only (no random sampling, no ordering ambiguity)
- Random seed tracking for any Monte Carlo/randomized components (future)
- Version all inputs: signal_version, feature_version_hash, backtest_config_version

**Signal and Feature Versioning:**
- **Git-style hashing preferred, Claude decides exact implementation**
- Each signal stores hash of feature data used (cmc_daily_features at that timestamp)
- Backtest verifies hash matches current features to detect data changes
- Detects: feature recalculations, data corrections, schema changes
- Falls back to timestamp-based reconstruction if needed

**Reproducibility Validation:**
- **Combination approach: automated tests + hash comparison + manual checklist**
- Automated test suite: Run same backtest twice, assert identical PnL and all metrics
- Hash tracking: Store hash of backtest results (trades + metrics), rerun computes new hash
- Manual checklist: Document edge cases, user verifies reruns for complex scenarios
- Test suite fails if any difference detected (strict reproducibility enforcement)

**Data Change Detection:**
- **Configurable strictness** via CLI flags:
  - `--strict`: Fail if features changed since signal generation (strict reproducibility)
  - `--warn`: Detect changes, log warning, proceed with current data (transparency)
  - `--trust`: No change detection, assume features immutable (performance)
- Default: `--warn` mode (balance safety and usability)

### Claude's Discretion

- Exact BaseSignal architecture vs signal-specific patterns
- Git-style hashing implementation details for versioning
- Which volatility estimator for adaptive RSI thresholds (Parkinson vs GK)
- ATR breakout definition (combination approach specifics)
- Backtest metric calculation details (leverage existing reports.py or extend)
- dim_signals table schema design (JSONB structure for params)
- Signal table schemas (exact columns beyond core requirements)
- State transition logic for stateful signals (open → pending → closed)
- Error handling when signal generation encounters edge cases

</decisions>

<specifics>
## Specific Ideas

- "Leverage existing signals/* adapters — don't rewrite what works"
- "Backtest orchestrator already exists (orchestrator.py, vbt_runner.py) — integrate with it"
- "dim_signals should follow dim_indicators pattern (JSONB params, is_active flag)"
- "We will need to test and calibrate dynamic RSI thresholds — build flexibility for experimentation"
- "ATR breakout needs testing — combination approach OR Claude decides based on literature"
- "Position sizing via CLI flags — support all methods for future Monte Carlo work"
- "Hash-based versioning preferred (like git) — catches any feature data changes"

</specifics>

<deferred>
## Deferred Ideas

- Monte Carlo simulations for parameter optimization — future phase or backlog
- Walk-forward optimization — future enhancement
- Multi-asset portfolio backtesting — Phase 9 or later
- Live signal generation integration — separate phase
- Signal visualization dashboard — separate phase
- Automated parameter tuning via ML — research backlog

</deferred>

---

*Phase: 08-ta_lab2-signals*
*Context gathered: 2026-01-30*
