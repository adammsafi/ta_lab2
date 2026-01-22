# Codebase Structure

**Analysis Date:** 2026-01-21

## Directory Layout

```
ta_lab2/
├── src/ta_lab2/                    # Main package (src layout)
│   ├── __init__.py                 # Public API exports + fallback shims
│   ├── config.py                   # Settings shim & env loading
│   ├── io.py                       # Database I/O helpers
│   ├── logging_setup.py            # Logging configuration
│   ├── cli.py                      # CLI entry point (ta-lab2 command)
│   ├── compare.py                  # Comparison utilities
│   ├── resample.py                 # Data resampling helpers
│   │
│   ├── features/                   # Feature engineering (technical indicators)
│   │   ├── __init__.py
│   │   ├── ema.py                  # EMA core functions + column builders
│   │   ├── indicators.py           # RSI, MACD, Bollinger, ADX, OBV, MFI, Stoch
│   │   ├── vol.py                  # ATR, rolling volatility
│   │   ├── returns.py              # Pct/log returns, rolling vol
│   │   ├── calendar.py             # Date features (day_of_week, session, lunar)
│   │   ├── trend.py                # Trend classification
│   │   ├── segments.py             # Flip-based segmentation
│   │   ├── correlation.py          # ACF, PACF, rolling correlation
│   │   ├── ensure.py               # Column existence validators
│   │   ├── resample.py             # Resampling logic (daily, hourly, etc.)
│   │   ├── feature_pack.py         # Feature composition helpers
│   │   └── m_tf/                   # Multi-timeframe EMA logic
│   │       ├── ema_multi_timeframe.py
│   │       ├── ema_multi_tf_v2.py
│   │       ├── ema_multi_tf_cal.py
│   │       ├── ema_multi_tf_cal_anchor.py
│   │       ├── views.py            # DB view generation
│   │       └── ema_research/       # Research-phase work (charts, tests)
│   │
│   ├── signals/                    # Strategy signal generators
│   │   ├── __init__.py
│   │   ├── registry.py             # Strategy registry (lookup by name)
│   │   ├── generator.py            # Core signal composition (EMA cross + filters)
│   │   ├── ema_trend.py            # EMA crossover strategy adapter
│   │   ├── rsi_mean_revert.py      # RSI-based mean revert (optional)
│   │   ├── breakout_atr.py         # ATR breakout strategy (optional)
│   │   ├── rules.py                # Primitive rule functions (ema_crossover, rsi_ok, etc.)
│   │   ├── position_sizing.py      # ATR-based position sizing
│   │   └── __init__.py
│   │
│   ├── regimes/                    # Market regime detection & policy
│   │   ├── __init__.py
│   │   ├── labels.py               # Trend/vol/liquidity labelers
│   │   ├── resolver.py             # Policy resolution from multi-layer regimes
│   │   ├── comovement.py           # EMA comovement stats
│   │   ├── proxies.py              # Liquidity/stress proxies
│   │   ├── segments.py             # Segment analysis
│   │   ├── flips.py                # Trend flip detection
│   │   ├── feature_utils.py        # Regime feature helpers
│   │   ├── data_budget.py          # Memory-efficient data loading
│   │   ├── telemetry.py            # Logging/instrumentation
│   │   ├── policy_loader.py        # Load policies from YAML/dict
│   │   ├── regime_inspect.py       # Inspect regime states
│   │   ├── run_btc_pipeline.py     # CLI wrapper for pipeline
│   │   └── old_run_btc_pipeline.py # Deprecated version
│   │
│   ├── backtests/                  # Backtesting engines & metrics
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # Multi-strategy backtest runner
│   │   ├── vbt_runner.py           # Vectorbt wrapper (grid sweep)
│   │   ├── btpy_runner.py          # Backtrader wrapper (optional)
│   │   ├── metrics.py              # Performance metrics (Sharpe, Calmar, etc.)
│   │   ├── costs.py                # Commission & slippage models
│   │   ├── splitters.py            # Walk-forward / period splitters
│   │   └── reports.py              # Report generation
│   │
│   ├── analysis/                   # Post-backtest analysis
│   │   ├── __init__.py
│   │   ├── performance.py          # Return/equity curves, metric calcs
│   │   ├── parameter_sweep.py      # Grid search & sensitivity
│   │   ├── feature_eval.py         # Feature importance / correlation
│   │   └── regime_eval.py          # Regime-specific performance
│   │
│   ├── pipelines/                  # Orchestration workflows
│   │   ├── __init__.py
│   │   └── btc_pipeline.py         # Main end-to-end pipeline
│   │
│   ├── scripts/                    # Executable data processing scripts
│   │   ├── __init__.py
│   │   ├── bars/                   # Price bar refresh & audit
│   │   │   ├── refresh_cmc_price_bars_1d.py
│   │   │   ├── refresh_cmc_price_bars_multi_tf.py
│   │   │   ├── refresh_cmc_price_bars_multi_tf_cal*.py (3 variants)
│   │   │   ├── audit_price_bars_*.py (integrity, samples, tables)
│   │   │   └── common_snapshot_contract.py
│   │   ├── emas/                   # EMA refresh & audit
│   │   │   ├── refresh_cmc_ema_multi_tf*.py (3 variants)
│   │   │   ├── audit_ema_*.py (integrity, samples, expected_coverage)
│   │   │   ├── run_all_ema_refreshes.py
│   │   │   ├── sync_cmc_ema_multi_tf_u.py
│   │   │   └── stats/              # EMA statistics aggregation
│   │   │       ├── daily/          # Daily EMA stats
│   │   │       ├── multi_tf/       # Multi-timeframe EMA stats
│   │   │       ├── multi_tf_cal/   # Calendar-adjusted EMA stats
│   │   │       └── multi_tf_cal_anchor/  # Anchored EMA stats
│   │   ├── pipeline/               # Orchestration
│   │   │   └── run_go_forward_daily_refresh.py  # Main state-based orchestrator
│   │   ├── etl/                    # ETL tasks
│   │   │   ├── update_cmc_history.py
│   │   │   └── backfill_ema_diffs.py
│   │   ├── prices/                 # Price history utilities
│   │   ├── returns/                # Return calculations
│   │   ├── research/               # Research queries
│   │   │   └── queries/
│   │   │       ├── opt_cf_*.py
│   │   │       └── wf_validate_ema.py
│   │   └── sandbox/                # Experimental/ad-hoc scripts
│   │
│   ├── time/                       # Time dimension (sessions, calendars)
│   │   ├── __init__.py
│   │   ├── specs.py                # Calendar specs (trading hours, holidays)
│   │   ├── dim_sessions.py         # Session definitions
│   │   ├── dim_timeframe.py        # Timeframe definitions (1min, hourly, daily)
│   │   └── qa.py                   # Time dimension validation
│   │
│   ├── tools/                      # CLI utilities & maintenance
│   │   ├── __init__.py
│   │   ├── dbtool.py               # Database utilities (snapshots, checks)
│   │   └── snapshot_diff.py        # Compare snapshots with diff reporting
│   │
│   ├── utils/                      # Shared utilities
│   │   ├── cache.py                # Memoization helpers
│   │
│   ├── viz/                        # Visualization & plots
│   │   └── all_plots.py            # Matplotlib-based charting
│   │
│   └── live/                       # Live trading (stub/future)
│
├── pyproject.toml                  # Package metadata & dependencies
├── config.py                       # Root-level config (Settings class, load_settings)
├── db_config.env                   # DB credentials (local, .gitignored)
│
└── tests/                          # Test suite
    ├── test_bar_*.py               # Bar OHLCV tests
    ├── test_bar_contract_*.py      # Contract validation
    └── test_bar_ohlcv_*.py         # Correctness checks
```

## Directory Purposes

**src/ta_lab2/:**
- Purpose: Main package code
- Contains: All application logic
- Key files: `__init__.py` (public API), `config.py` (settings shim), `io.py` (database)

**features/:**
- Purpose: Technical indicator and feature computation
- Contains: Rolling calculations, indicator builders, multi-timeframe logic
- Key files: `ema.py` (core EMA functions), `indicators.py` (RSI, MACD, etc.), `vol.py` (ATR, volatility)

**signals/:**
- Purpose: Entry/exit signal generation from features
- Contains: Rule primitives, strategy adapters, registry
- Key files: `registry.py` (strategy lookup), `generator.py` (signal composition), `ema_trend.py` (EMA strategy)

**regimes/:**
- Purpose: Market state classification and policy resolution
- Contains: Trend/vol/liquidity labelers, tighten-only policy engine
- Key files: `labels.py` (labeling functions), `resolver.py` (policy resolution)

**backtests/:**
- Purpose: Vectorized backtest execution and performance calculation
- Contains: Backtest orchestrator, metric engines, cost models
- Key files: `orchestrator.py` (multi-strategy runner), `metrics.py` (Sharpe, Calmar, etc.), `vbt_runner.py` (vectorbt wrapper)

**analysis/:**
- Purpose: Post-backtest analysis and optimization
- Contains: Grid search, feature evaluation, regime performance
- Key files: `performance.py` (metrics), `parameter_sweep.py` (grid search)

**pipelines/:**
- Purpose: End-to-end data processing orchestration
- Contains: Feature composition, conditional execution
- Key files: `btc_pipeline.py` (main orchestrator)

**scripts/:**
- Purpose: Executable data refresh and maintenance jobs
- Contains: Price bar updaters, EMA calculators, auditors, state managers
- Key files: `bars/refresh_cmc_price_bars_1d.py` (price refresh), `emas/refresh_cmc_ema_multi_tf*.py` (EMA refresh)

**tools/:**
- Purpose: Database maintenance and inspection utilities
- Contains: Snapshot diffing, table checks, schema utilities
- Key files: `snapshot_diff.py` (compare DB snapshots)

**time/:**
- Purpose: Calendar and timeframe specifications
- Contains: Trading hour definitions, session specifications, timeframe constants
- Key files: `dim_sessions.py` (session defs), `dim_timeframe.py` (timeframe defs)

## Key File Locations

**Entry Points:**
- `src/ta_lab2/cli.py`: CLI main (ta-lab2 command)
- `src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py`: Daily refresh orchestrator
- `src/ta_lab2/regimes/run_btc_pipeline.py`: Pipeline CLI wrapper

**Configuration:**
- `src/ta_lab2/config.py`: Settings shim & environment loader
- `pyproject.toml`: Package metadata & dependencies
- `config.py` (root): Root-level Settings class & load_settings()

**Core Logic:**
- `src/ta_lab2/features/ema.py`: EMA computation & column builders
- `src/ta_lab2/regimes/resolver.py`: Policy resolution engine
- `src/ta_lab2/signals/registry.py`: Strategy registry
- `src/ta_lab2/backtests/orchestrator.py`: Multi-strategy backtest runner
- `src/ta_lab2/pipelines/btc_pipeline.py`: Feature composition & orchestration

**Testing:**
- `tests/test_bar_ohlcv_correctness.py`: Bar OHLCV validation
- `tests/test_bar_contract*.py`: Contract & gap testing

## Naming Conventions

**Files:**
- Refresh jobs: `refresh_<entity>_<variant>.py` (e.g., `refresh_cmc_price_bars_1d.py`)
- Audit jobs: `audit_<entity>_<check_type>.py` (e.g., `audit_ema_integrity.py`)
- Feature modules: lowercase + underscore (e.g., `ema.py`, `vol.py`)
- Strategy modules: lowercase + underscore (e.g., `ema_trend.py`, `rsi_mean_revert.py`)

**Directories:**
- Layer names: lowercase plural (e.g., `features/`, `signals/`, `regimes/`)
- Multi-stage: nested by variant (e.g., `scripts/bars/`, `scripts/emas/stats/`)
- Old/deprecated: `old/` subdirectory within functional dirs

**Functions:**
- Public API: lowercase + underscore (e.g., `add_ema_columns()`, `compute_ema()`)
- Internal helpers: `_leading_underscore` prefix
- Builder functions (mutate df): `add_*` or `ensure_*` prefix
- Calculators (return Series/value): bare or descriptive name (e.g., `compute_ema()`, `sharpe()`)

**Variables:**
- DataFrames: `df`, `df_prices`, `df_ema` (noun form)
- Series: `s`, `s_ema`, `ret` (descriptive)
- Constants: `UPPERCASE_SNAKE_CASE` (e.g., `REGISTRY`, `STATE_TABLE`)
- Column names: lowercase + underscore (e.g., `ema_21`, `close_ema_50`)

**Types:**
- Type aliases: CamelCase (e.g., `Split`, `CostModel`)
- Dataclasses: CamelCase (e.g., `TightenOnlyPolicy`)

## Where to Add New Code

**New Feature (Technical Indicator):**
- Primary code: `src/ta_lab2/features/<indicator_name>.py`
- Column builder: Define `add_<indicator>()` function in same file
- Expose in: `src/ta_lab2/features/__init__.py` and optionally `src/ta_lab2/__init__.py`
- Tests: `tests/test_<indicator_name>.py`

**New Signal Strategy:**
- Implementation: `src/ta_lab2/signals/<strategy_name>.py`
- Adapter: Define `make_signals(df, **params)` -> tuple(entry, exit, size)
- Register: Add to `REGISTRY` in `src/ta_lab2/signals/registry.py`
- Tests: `tests/test_<strategy_name>.py`

**New Regime Labeler:**
- Implementation: Add function to `src/ta_lab2/regimes/labels.py`
- Signature: `label_<regime_type>(df, ...) -> pd.Series`
- Policy integration: Update `src/ta_lab2/regimes/resolver.py` if policy table changes
- Tests: `tests/test_regimes.py`

**New Data Refresh Job:**
- Location: `src/ta_lab2/scripts/<domain>/<refresh_type>.py`
- Pattern: Load from DB → compute → upsert → update state
- Entry: `if __name__ == "__main__":` with argparse for CLI args
- State key: Use `_state_key_for_step()` pattern from `run_go_forward_daily_refresh.py`

**Utilities:**
- Shared helpers: `src/ta_lab2/utils/<module>.py`
- Database utilities: `src/ta_lab2/tools/<module>.py`
- Visualization: `src/ta_lab2/viz/<module>.py`

## Special Directories

**src/ta_lab2/features/m_tf/:**
- Purpose: Multi-timeframe EMA logic (proprietary complexity)
- Generated: No
- Committed: Yes
- Contains: Variants (basic, v2, cal, cal_anchor) + research subdirectory
- Key decision point: All multi-TF aggregation lives here

**src/ta_lab2/scripts/{bars,emas,etl}/old/:**
- Purpose: Archive of deprecated/previous implementations
- Generated: No
- Committed: Yes (for history)
- Guidance: Do not use; reference only for understanding evolution

**tests/:**
- Purpose: Test suite (pytest)
- Generated: No
- Committed: Yes
- Pattern: Mirror source structure (test_bar_*.py, test_signals_*.py)

**sql/ (if present):**
- Purpose: Database DDL and migrations
- Generated: No
- Committed: Yes
- Sections: ddl/, migrations/, checks/, metrics/, snapshots/, dim/

---

*Structure analysis: 2026-01-21*
