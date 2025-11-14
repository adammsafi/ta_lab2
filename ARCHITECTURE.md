# ta_lab2 Architecture

This document explains how the `ta_lab2` package is organized and how data flows through it.

At a high level, `ta_lab2` is:

> A multi-timescale technical analysis lab for building features, regimes, signals, and backtests on BTC (and later, other assets).

Core flow:

**Data source (CSV / DB) → IO / resample → features → regimes → signals → pipelines / backtests → viz / analysis / CLI**

---

## Package overview

Root package: `ta_lab2`

Important top-level modules:

- `ta_lab2.__init__`
  - Public surface for a few convenience functions.
  - Example: `add_rolling_vol_from_returns_batch`.

- `ta_lab2.cli`
  - Command-line entry point.
  - Functions:
    - `build_parser`, `main` – top-level CLI wiring.
    - `cmd_pipeline` – run feature / regime / signal pipelines from the command line.
    - `cmd_regime_inspect` – inspect regime labels / policies.
  - Internal helpers:
    - `_read_df`, `_default_policy_yaml`, `_ensure_feats_if_possible`.

- `ta_lab2.io`
  - Simple IO helpers:
    - `read_parquet`, `write_parquet`.
  - Intended to be extended to DB-backed loaders/writers later.

- `ta_lab2.resample`
  - “Raw” resampling and binning utilities (for time and seasons):
    - `bin_by_calendar`
    - `bin_by_season`
  - Internal helpers to enforce datetime index, aggregation schemes, etc.

- `ta_lab2.compare`
  - Helpers to compare behavior across timeframes:
    - `build_timeframe`, `prep_for_stats`.

- `ta_lab2.logging_setup`
  - `setup_logging` – central place for logging configuration.

---

## Features layer (`ta_lab2.features.*`)

These modules create *columns* (features) on top of a price/volume DataFrame.

- `features.calendar`
  - Time-based features:
    - `expand_datetime_features_inplace`, `expand_multiple_timestamps`.
  - Adds day-of-week, month, week-of-year, etc.

- `features.correlation`
  - Autocorrelation and cross-correlation tools:
    - `acf`, `pacf_yw`, `rolling_autocorr`, `xcorr`.

- `features.ema`
  - EMA-focused utilities:
    - `compute_ema`, `add_ema_columns`, `add_ema_d1`, `add_ema_d2`, `add_ema`.
    - Helpers like `_flip_for_direction`, `prepare_ema_helpers`.

- `features.indicators`
  - Classic TA indicators:
    - `rsi`, `macd`, `stoch_kd`, `bollinger`, `atr`, `adx`, `obv`, `mfi`.

- `features.returns`
  - Return calculations:
    - `b2t_pct_delta`, `b2t_log_delta`, `add_returns`.

- `features.vol`
  - Volatility estimators:
    - `add_parkinson_vol`, `add_garman_klass_vol`, `add_rogers_satchell_vol`,
      `add_atr`, `add_logret_stdev_vol`,
      `add_rolling_realized_batch`, `add_rolling_vol_from_returns_batch`,
      `add_volatility_features`.

- `features.trend`
  - Trend labels:
    - `compute_trend_labels`.

- `features.segments`
  - Price move segmentation:
    - `build_flip_segments`.

- `features.ensure`
  - “Ensure X exists” helpers:
    - `ensure_close`, `ensure_ema`, `ensure_rsi`, `ensure_macd`, `ensure_adx`, `ensure_obv`.

- `features.feature_pack`
  - Bundling multiple features:
    - `attach_core_features`.

- `features.resample`
  - Higher-level resample tools (on top of raw resample):
    - `resample_one`, `resample_many`,
      `add_season_label`, `seasonal_summary`.

The **features layer** is deliberately modular: you can mix and match indicators and vol measures as needed.

---

## Regime layer (`ta_lab2.regimes.*`)

Regimes use features to classify the market / environment and then derive policies.

- `regimes.labels`
  - Core labeling functions:
    - `label_trend_basic`
    - `label_vol_bucket`
    - `label_liquidity_bucket`
    - Higher-level layers:
      - `label_layer_monthly`, `label_layer_weekly`, `label_layer_daily`, `label_layer_intraday`.
    - `compose_regime_key` to combine labels.

- `regimes.flips`
  - Signed state and flip-based regimes:
    - `sign_from_series`, `detect_flips`,
      `label_regimes_from_flips`, `attach_regimes`, `regime_stats`.

- `regimes.comovement`
  - EMA comovement and alignment:
    - `build_alignment_frame`, `rolling_agreement`,
      `compute_ema_comovement_stats`, `compute_ema_comovement_hierarchy`.

- `regimes.data_budget`
  - How much data you have at each timeframe:
    - `DataBudgetContext`, `assess_data_budget`.

- `regimes.feature_utils`
  - Feature bundles specifically for regimes:
    - `_ema`, `add_ema_pack`, `add_atr14`, `ensure_regime_features`.

- `regimes.policy_loader`
  - Load policy tables from YAML:
    - `_default_policy_yaml_path`, `load_policy_table`.

- `regimes.resolver`
  - Convert labels into policies:
    - `resolve_policy_from_table`, `resolve_policy`,
      plus internal `_match_policy`, `apply_hysteresis`, `_tighten`.
    - `TightenOnlyPolicy` type.

- `regimes.proxies`
  - Proxy regimes based on cycle/macro:
    - `ProxyInputs`, `ProxyOutcome`,
      `infer_cycle_proxy`, `infer_weekly_macro_proxy`.

- `regimes.telemetry`
  - Recording snapshots of regime state:
    - `RegimeSnapshot`, `append_snapshot`.

- `regimes.run_btc_pipeline` / `regimes.old_run_btc_pipeline`
  - Older and newer ways of running a BTC-specific regime pipeline.
  - `old_run_btc_pipeline` is legacy; new work should go through
    `regimes.run_btc_pipeline` or the `pipelines` module.

- `regimes.regime_inspect`
  - CLI-friendly inspection entry point:
    - `_read_df`, `main`.

The **regime layer** maps rich feature sets into discrete states and **policy objects** that can inform sizing, stops, and allowed trade types.

---

## Signals layer (`ta_lab2.signals.*`)

Signals turn data + features + regimes into actionable trading signals.

- `signals.breakout_atr`
  - ATR breakout strategy:
    - `make_signals`.

- `signals.ema_trend`
  - EMA trend-following signals:
    - `make_signals`.

- `signals.rsi_mean_revert`
  - RSI mean-reversion strategy:
    - `make_signals`.

- `signals.rules`
  - Reusable rule primitives:
    - `ema_crossover_long`, `ema_crossover_short`,
      `rsi_ok_long`, `rsi_ok_short`,
      `volatility_filter`.

- `signals.position_sizing`
  - How big to trade:
    - `clamp_size`, `ema_smooth`,
      `volatility_size_pct`, `target_dollar_position`,
      `fixed_fractional`, `inverse_volatility`.

- `signals.registry`
  - Registry of strategies:
    - `get_strategy`, `ensure_for`, `grid_for`,
      plus internal `_ensure_*` helpers.

- `signals.generator`
  - Higher-level signal orchestration:
    - `generate_signals`.

- `signals.__init__`
  - Surface helpers:
    - `attach_signals_from_config`.

The **signals layer** is the “strategy library” – this is where new strategies get added and registered.

---

## Pipelines (`ta_lab2.pipelines.*`)

Opinionated workflows that tie together features, regimes, and signals.

- `pipelines.btc_pipeline`
  - BTC-specific pipeline entrypoint:
    - `run_btc_pipeline`, `main`.
  - Utilities:
    - `_infer_timestamp_col`, `_coerce_df`,
      `_maybe_from_config`, `_find_default_csv`,
      `_call_ema_comovement`, `_call_ema_hierarchy`,
      `_call_build_segments`.

- `pipelines.__init__`
  - Package marker; for now, BTC is the main pipeline.

Pipelines are where you express “from raw BTC historical data → enriched DataFrame with features, regimes, signals → summaries/plots.”

---

## Backtests (`ta_lab2.backtests.*`)

Backtest runners and summaries for strategies built from signals.

- `backtests.btpy_runner`
  - Lightweight backtest runner:
    - `run_bt`, with `BTResult`.

- `backtests.vbt_runner`
  - Vectorbt-based backtester:
    - `run_vbt_on_split`, `sweep_grid`,
      and helper types: `SignalFunc`, `CostModel`, `Split`, `ResultRow`, `ResultBundle`.

- `backtests.splitters`
  - Train/test splitting:
    - `Split`, `expanding_walk_forward`, `fixed_date_splits`.

- `backtests.metrics`
  - Performance metrics:
    - `cagr`, `max_drawdown`, `sharpe`, `sortino`, `mar`, `summarize`.

- `backtests.reports`
  - Save and plot backtest summaries:
    - `save_table`, `equity_plot`, `leaderboard`.

- `backtests.costs`
  - Transaction cost modeling:
    - `CostModel`.

- `backtests.orchestrator`
  - Multi-strategy coordination:
    - `run_multi_strategy`, `MultiResult`, `_leaderboard`.

This layer consumes **signals** and **price data** to produce performance stats and plots.

---

## Analysis (`ta_lab2.analysis.*`)

Reusable analysis utilities for features, performance, and regimes.

- `analysis.performance`
  - Returns and equity curve tooling:
    - `pct_change`, `log_returns`, `equity_from_returns`,
      `sharpe`, `sortino`, `max_drawdown`, `calmar`,
      `annual_return`, `hit_rate`, `turnover`,
      `position_returns`, `evaluate_signals`.

- `analysis.feature_eval`
  - Feature importance and redundancy:
    - `corr_matrix`, `redundancy_report`,
      `future_return`, `binarize_target`,
      `quick_logit_feature_weights`,
      `feature_target_correlations`.

- `analysis.parameter_sweep`
  - Grid / random search over parameters:
    - `grid`, `random_search`.

- `analysis.regime_eval`
  - Regime-based performance cuts:
    - `metrics_by_regime`, `regime_transition_pnl`.

Use these to understand *why* a given signal or regime works or fails.

---

## Research queries (`ta_lab2.research.queries.*`)

Script-style entrypoints for specific research workflows, mainly around EMA strategies.

Examples:

- `opt_cf_ema`, `opt_cf_ema_refine`, `opt_cf_ema_sensitivity`
- `opt_cf_generic`
- `run_ema_50_100`
- `wf_validate_ema`

Each module typically has:

- `load_df`, `ensure_ema`, some `_norm_cols` helper, and a `main` function.

These are more “labs” than core APIs, and may be refactored into pipelines or notebooks over time.

---

## Viz (`ta_lab2.viz.*`)

- `viz.all_plots`
  - Plot helpers:
    - `plot_ema_with_trend`
    - `plot_consolidated_emas_like`
    - `plot_realized_vol`

This is where charting logic lives instead of being scattered across notebooks.

---

## Utils (`ta_lab2.utils.*`)

- `utils.cache`
  - Simple disk caching decorator:
    - `disk_cache`.

Use this for expensive computations that don’t change often (e.g. big resamples).

---

## Typical data flows

### A. Analysis via pipeline

1. Load raw BTC data (CSV or DB).
2. Run `pipelines.btc_pipeline.run_btc_pipeline`:
   - Uses `features.*` (returns, vol, EMA, trend, segments).
   - Uses `regimes.*` (labels, data_budget, resolver).
   - Attaches signals via `signals.*`.
3. Optionally:
   - Backtest via `backtests.*`.
   - Visualize via `viz.all_plots`.
   - Evaluate via `analysis.*`.

### B. Regime-only inspection

1. Load weekly + daily data from CSV/Parquet or DB.
2. Ensure regime features (`regimes.feature_utils.ensure_regime_features`).
3. Label layers via `regimes.labels.*`.
4. Resolve policies via `regimes.resolver.resolve_policy`.
5. Inspect via:
   - CLI: `python -m ta_lab2.cli regime-inspect ...`
   - Notebook, calling the same underlying functions.

---

## What goes where (rules of thumb)

- **New indicator / feature** → `ta_lab2.features.*`
- **Regime logic / policy** → `ta_lab2.regimes.*`
- **Trading rules / signal logic** → `ta_lab2.signals.*`
- **Full workflow for a specific asset** → `ta_lab2.pipelines.*`
- **Backtest or metrics** → `ta_lab2.backtests.*` or `ta_lab2.analysis.*`
- **One-off research experiments** → `ta_lab2.research.queries.*`
- **Visualization** → `ta_lab2.viz.*`
- **CLI wiring** → `ta_lab2.cli`
- **Cross-cutting utilities** → `ta_lab2.utils.*` (sparingly)

This architecture should keep the package understandable as it grows and make it clear where to put new code.
