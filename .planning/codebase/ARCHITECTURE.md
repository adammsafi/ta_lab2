# Architecture

**Analysis Date:** 2026-01-21

## Pattern Overview

**Overall:** Layered data processing pipeline with pluggable signal strategies and multi-timeframe regime detection.

**Key Characteristics:**
- **Feature-driven design**: Modular calculators for technical indicators (EMA, RSI, volatility, etc.)
- **Pipeline orchestration**: Multi-stage data transformation from raw OHLCV through enrichment to backtesting
- **Database-centric**: Uses PostgreSQL as persistent layer for historical bars, EMAs, and pipeline state
- **Registry-based strategies**: Pluggable signal generators with canonical registry lookup
- **Regime-aware**: Multi-layer regime detection (trend, volatility, liquidity) that feeds position sizing

## Layers

**Data Layer (I/O):**
- Purpose: Load raw market data from PostgreSQL, write computed results back
- Location: `src/ta_lab2/io.py`, `src/ta_lab2/config.py`
- Contains: Database connection helpers, settings loaders, CSV read/write utilities
- Depends on: SQLAlchemy, psycopg (DB drivers)
- Used by: All pipeline stages and scripts

**Features/Feature Engineering:**
- Purpose: Compute technical indicators and normalized features on raw OHLCV data
- Location: `src/ta_lab2/features/` (ema.py, indicators.py, vol.py, returns.py, calendar.py, segments.py, trend.py, correlation.py)
- Contains: Column builders, rolling calculations, EMA multi-timeframe logic
- Depends on: pandas, numpy
- Used by: Pipelines, backtests, regime detection

**Regimes & Labeling:**
- Purpose: Classify market states (trend, volatility, liquidity, stress) into discrete labels
- Location: `src/ta_lab2/regimes/` (labels.py, resolver.py, comovement.py, proxies.py)
- Contains: Labelers for Up/Down/Sideways trend, Low/Normal/High volatility, policy resolution
- Depends on: Features layer (requires computed EMAs, ATR, ADX)
- Used by: Position sizing, order filtering, backtest parameter control

**Signals & Strategies:**
- Purpose: Generate entry/exit signals based on feature conditions and optional filtering
- Location: `src/ta_lab2/signals/` (generator.py, registry.py, ema_trend.py, rsi_mean_revert.py, rules.py)
- Contains: Core signal generators, rule primitives, strategy registry, position sizing
- Depends on: Features layer (requires EMAs, RSI, ATR)
- Used by: Backtesting orchestrator

**Backtesting:**
- Purpose: Simulate strategies across historical data with cost models and performance metrics
- Location: `src/ta_lab2/backtests/` (orchestrator.py, vbt_runner.py, metrics.py, costs.py, splitters.py)
- Contains: Vectorized backtest engine (vectorbt wrapper), performance metrics (Sharpe, Calmar, MAR), cost models
- Depends on: Signals, pandas, vectorbt (optional)
- Used by: Research scripts, performance analysis

**Analysis:**
- Purpose: Evaluate backtest results and feature predictiveness
- Location: `src/ta_lab2/analysis/` (performance.py, parameter_sweep.py, feature_eval.py, regime_eval.py)
- Contains: Metrics computation (annual return, max DD, hit rate, turnover), grid search
- Depends on: Backtests
- Used by: Research pipelines

**Pipelines:**
- Purpose: Orchestrate end-to-end workflows from raw data through feature computation
- Location: `src/ta_lab2/pipelines/btc_pipeline.py` (main orchestrator), `src/ta_lab2/regimes/run_btc_pipeline.py` (CLI wrapper)
- Contains: Feature composition, conditional execution (do_calendar, do_indicators, do_ema flags)
- Depends on: Features, Regimes, Signals
- Used by: CLI, scripts

**Scripts:**
- Purpose: Maintain historical data and computed features in database
- Location: `src/ta_lab2/scripts/` (bars/, emas/, etl/, pipeline/, prices/)
- Contains: Refresh jobs (bars, EMAs, stats), audit jobs, incremental/full rebuild logic
- Depends on: Features, I/O
- Used by: Daily refresh orchestrator (`run_go_forward_daily_refresh.py`)

## Data Flow

**Incremental Refresh (Daily):**

1. **Price Update** (`scripts/bars/refresh_cmc_price_bars_*.py`)
   - Query CMC API or external source
   - Upsert into `public.cmc_price_bars_1d` (and multi-timeframe tables)
   - Sets watermark in `public.ta_lab2_pipeline_state`

2. **EMA Calculation** (`scripts/emas/refresh_cmc_ema_multi_tf*.py`)
   - Load latest price bars from DB
   - Compute EMAs (fast/mid/slow windows)
   - Write to `public.cmc_ema_multi_tf` and variants (cal, cal_anchor)

3. **Stats Aggregation** (`scripts/emas/stats/*/refresh_ema_*_stats.py`)
   - Compute rolling statistics on EMA columns (coverage, lag, etc.)
   - Write to stats tables (e.g., `public.cmc_ema_multi_tf_stats_1d`)

4. **Full Pipeline** (`run_btc_pipeline()` or `run_go_forward_daily_refresh.py`)
   - Load bars + EMAs from DB
   - Call feature enrichers (calendar, returns, volatility, indicators)
   - Compute regimes (multi-layer labeling)
   - Compute signals (based on regimes & feature conditions)

**State Management:**
- Watermarks stored in `public.ta_lab2_pipeline_state` (table: `state_key`, `state_value`, `updated_at`)
- Each script checks its watermark before running; skips if already processed (unless `--force` or `--rebuild`)
- Prevents redundant computation but allows incremental updates

**Backtest Flow:**
1. Load signal dataframe (from pipeline output or CSV)
2. Slice by `Split` windows (train/test periods)
3. For each parameter grid: generate signals, compute equity, calculate metrics
4. Aggregate results into leaderboard ranked by MAR -> Sharpe -> CAGR

## Key Abstractions

**Feature Builders:**
- Purpose: In-place DataFrame column builders (return modified df)
- Examples: `add_ema_columns()`, `add_returns()`, `add_atr()`
- Location: `src/ta_lab2/features/ema.py`, `src/ta_lab2/features/vol.py`, etc.
- Pattern: Most accept `df`, optional `price_col`, and return `df` (not Series)

**Regime Resolver:**
- Purpose: Combine multi-layer regime labels into a tighten-only policy
- Examples: `resolve_policy()`, `resolve_policy_from_table()`
- Location: `src/ta_lab2/regimes/resolver.py`
- Pattern: Higher layers can only tighten risk (reduce size_mult, increase stop_mult), never loosen

**Signal Generator:**
- Purpose: Compose entry/exit rules from features
- Examples: `generate_signals()`, `make_signals()` (per strategy)
- Location: `src/ta_lab2/signals/generator.py`, `src/ta_lab2/signals/ema_trend.py`
- Pattern: Returns tuple of (entry: Series[bool], exit: Series[bool], size: Optional[Series[float]])

**Strategy Registry:**
- Purpose: Pluggable strategy lookup without hardcoding
- Examples: `get_strategy(name)`, `REGISTRY[name]`
- Location: `src/ta_lab2/signals/registry.py`
- Pattern: All registered strategies conform to uniform signature (df, **params) -> tuple

**Performance Metrics:**
- Purpose: Compute annualized metrics from return series
- Examples: `sharpe()`, `calmar()`, `annual_return()`, `max_drawdown()`
- Location: `src/ta_lab2/analysis/performance.py`
- Pattern: Accept returns Series, return float scalar; handle edge cases gracefully

## Entry Points

**CLI:**
- Location: `src/ta_lab2/cli.py`
- Triggers: `ta-lab2` command (registered in pyproject.toml)
- Responsibilities: Argument parsing, pipeline execution, output formatting

**Pipeline Orchestrator:**
- Location: `src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py`
- Triggers: Manual execution or cron job
- Responsibilities: Check watermarks, sequence steps (bars → EMAs → stats), forward state

**Package Root:**
- Location: `src/ta_lab2/__init__.py`
- Exports: Public API (add_ema, add_returns, expand_datetime_features_inplace, etc.)
- Backward compatibility: Fallback shims for optional features

**Feature Scripts:**
- Location: `src/ta_lab2/scripts/{bars,emas,prices,etl}/`
- Executable: Direct `python -m` or via CLI
- Responsibilities: Load data, compute, persist, manage state

## Error Handling

**Strategy:** Fail-safe defaults with extensive optional fallbacks

**Patterns:**
- Try-except imports: Optional dependencies (astronomy, vectorbt) fail gracefully
- Fallback callables: Missing optional strategies return stub implementations
- Null-coalescing configs: Env vars → root config → defaults
- Column existence checks: Auto-disable features if required columns missing (e.g., RSI filter if rsi_col absent)

## Cross-Cutting Concerns

**Logging:**
- Setup via `src/ta_lab2/logging_setup.py`
- Scripts use `logging.getLogger(__name__)` pattern
- Database operations logged to console and optional syslog

**Validation:**
- `src/ta_lab2/features/ensure.py`: Ensure required columns exist before operations
- Time dimension consistency: `src/ta_lab2/time/` modules verify calendar/session specs
- Config validation: Settings schema enforced at load time

**Authentication:**
- Database: Credentials via `TARGET_DB_URL` env (or `.env` file via `load_local_env()`)
- External APIs: CMC API key via `MARKETDATA_CMC_KEY` (handled in scripts)

---

*Architecture analysis: 2026-01-21*
