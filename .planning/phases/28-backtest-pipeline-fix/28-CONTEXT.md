# Phase 28: Backtest Pipeline Fix - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the signal-to-backtest pipeline so strategies can be validated end-to-end. This means fixing the dict serialization bug in signal generators' feature_snapshot column, fixing vectorbt timestamp errors in the backtest runner, and verifying the full flow: cmc_features -> signals -> backtest -> PnL. Signal generators, backtest runner, and result storage must all work without errors.

</domain>

<decisions>
## Implementation Decisions

### Feature Snapshot Fix
- Change feature_snapshot column type to **JSONB** (not TEXT)
- Capture **full feature row** from cmc_features at signal time (complete audit trail)
- Write snapshot **inline during signal generation** — fetch features, compute signal, write both signal + snapshot in one INSERT (atomic)
- Add **GIN index** on JSONB column for queryability (e.g., `WHERE feature_snapshot->>'rsi_14' > '70'`)
- Root cause: RSI and EMA generators don't serialize dicts before to_sql(); ATR generator already does it correctly with json.dumps()

### Backtest Output
- **Full report**: PnL summary + trade log + equity curve + drawdown series + monthly returns
- Store results in **database tables** (backtest_runs, backtest_trades, backtest_metrics)
- Each run gets **run_id (UUID) + metadata** (timestamp, config snapshot) for versioning and run comparison
- **Dynamic granularity** for equity curve: use the finer of daily marks or per-trade marks. Design for future intraday data even though current bars are daily — multiple trades per day should be handled
- Include **benchmark comparison** (configurable, default: buy-and-hold of the asset) for alpha measurement
- Support **multiple position sizing modes**: fixed fractional, equal weight, volatility-scaled
- **Configurable transaction costs**: default fee schedule (e.g., 10bps per trade) with override via config. Slippage configurable separately
- Support **long and short** directions
- **Allow stochastic elements**: support Monte Carlo or randomized entry within a bar for robustness testing
- Support **train/test splits**: configurable in-sample/out-of-sample windows for walk-forward validation
- **Per-asset + portfolio rollup**: run individual assets, then aggregate into portfolio view with correlation-aware metrics
- **CLI + programmatic interface**: `python -m ta_lab2.scripts.run_backtest --signal rsi --asset BTC --start 2024-01-01` plus importable Python API

### Signal Refresher Behavior
- **Fix all 3 generators equally** (RSI, EMA crossover, ATR breakout) — same treatment, full pipeline coverage
- Support **multi-TF from the start** — signal generators accept --tf flag, produce signals for any timeframe in dim_timeframe
- **Skip and log** on bad data (NaN features, missing rows) — matches EMA "warn and continue" pattern
- **Incremental refresh** by default (only compute signals for new feature rows), with **--full-rebuild flag** for re-computing everything — matches bar/EMA incremental pattern

### Vectorbt Compatibility
- **Keep vectorbt as pip dependency** — do NOT fork or replace
- Fix timestamp issues at the **boundary layer**: sanitize tz-aware timestamps before passing to vectorbt (tz_localize(None)), re-localize after getting results back (tz_localize("UTC"))
- Estimated ~10-20 lines of changes across vbt_runner.py and backtest_from_signals.py
- Leverage vectorbt's research features (indicator exploration, interactive plotting) for strategy development
- **Fallback plan**: if vectorbt becomes unmaintainable (breaking changes, abandoned), switch to custom engine (~400-500 LOC, ~1 plan of work). 80% of Phase 28 work is engine-agnostic and transfers

### Claude's Discretion
- Exact DDL for backtest result tables (column types, indexes, partitioning)
- How to structure the portfolio rollup aggregation
- Implementation of stochastic elements (which randomization approach)
- Specific walk-forward split defaults (window sizes, step sizes)
- How to handle the frequency parameter for multi-TF backtests (vectorbt's freq kwarg)

</decisions>

<specifics>
## Specific Ideas

- Equity curve granularity should be dynamic — based on whichever is more granular between daily marks and per-trade marks. "Even though we only have daily data we can still have multiple trades a day and we should plan for a world where we have intra-day data even though we don't have it yet"
- The existing btpy_runner.py (backtesting.py alternative) can be used as a reference for comparison testing
- ATR generator's json.dumps() pattern is the correct fix for the other two generators
- Cost model already exists in costs.py with CostModel dataclass — leverage it
- Splitters already exist in splitters.py — leverage for walk-forward splits

</specifics>

<deferred>
## Deferred Ideas

- Forking vectorbt for full code ownership — revisit if dependency becomes problematic
- Custom backtest engine (~400-500 LOC) — documented as fallback plan, 1 plan to implement if needed
- Streamlit/Dash visualization app for backtest results — separate phase
- Scheduled/automated backtest runs — separate phase

</deferred>

---

*Phase: 28-backtest-pipeline-fix*
*Context gathered: 2026-02-20*
