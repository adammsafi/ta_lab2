# ta_lab2 – File & Symbol Map
_Generated: 2025-12-27T16:14:38_

### `__init__.py`
**Functions**
- `add_rolling_vol_from_returns_batch(df, *, price_col, modes, windows, annualize, direction)` — Fallback shim: delegates to the project implementation if present,

### `cli.py`
**Classes**
- `RegimePolicy`
- `PipelineSettings`

**Functions**
- `cmd_pipeline(args)` — Preserve the original default behavior: run the BTC pipeline.
- `_detect_repo_root(start)` — Walk upward looking for pyproject.toml or .git. Fall back to start.
- `_load_regime_policy(repo_root, policy_path)` — Optional YAML overlay for flat policy overrides.
- `_read_df(path)`
- `_ensure_feats_if_possible(df, tag)`
- `_maybe_load_policy_table(policy_path, repo_root)` — Load a policy *table* (not the flat overrides) if present.
- `_coerce_label(x)` — Normalize labeler outputs so fallback mode resembles the ATTACHED behavior:
- `_merge_policy_overrides(resolved, pol)`
- `_present_regime_result_text(symbol, budget, L0, L1, L2, L3, resolved)`
- `_present_regime_result_json(symbol, budget, L0, L1, L2, L3, resolved)`
- `cmd_regime_inspect(args)` — Inspect multi-timeframe regimes and resolved policy.
- `cmd_db(args)` — Read-only DB helper. Delegates to ta_lab2.tools.dbtool CLI.
- `build_parser()`
- `main(argv)`

### `compare.py`
**Functions**
- `prep_for_stats(df, time_col, newest_first)`
- `build_timeframe(symbol, base_daily, tf, dt_col)`

### `config.py`
_(no top-level classes or functions)_

### `io.py`
**Functions**
- `get_engine(db_url)` — Backwards-compatible helper to create a SQLAlchemy engine.
- `write_parquet(df, path, partition_cols)`
- `read_parquet(path)`
- `_as_mapping(obj)`
- `_get_attr_or_key(obj, name, default)` — Try obj.name, then obj[name] if obj is a Mapping; otherwise default.
- `_get_marketdata_config()` — Return the 'marketdata' section from config via load_settings().
- `_get_marketdata_engine(db_url)` — Build a SQLAlchemy Engine for the marketdata database.
- `_get_marketdata_tables()` — Return a mapping of logical table names → actual DB table names
- `_get_marketdata_schema_and_tables()` — Return (schema, tables) for marketdata.
- `_qualify_table(schema, table_name)` — Return fully-qualified table name if a schema is provided.
- `load_cmc_ohlcv_daily(ids, *, start, end, db_url, tz)` — Load daily OHLCV time series from the cmc_price_histories7 table
- `load_close_panel(ids, *, start, end, db_url, tz)` — Convenience loader: return a wide panel of close prices.
- `load_da_ids(*, db_url)` — Load the full CoinMarketCap ID mapping table.
- `load_exchange_info(*, db_url)` — Load descriptive information for exchanges.
- `load_dim_timeframe(*, db_url, schema, table, index_cols)` — Load the dim_timeframe reference table.
- `_compute_ema_long_from_close_panel(close_panel, periods)` — Compute EMAs over a wide close panel and return a long-format DataFrame.
- `write_ema_daily_to_db(ids, periods, *, start, end, db_url, chunksize)` — Compute daily EMAs for the given asset ids from OHLCV in cmc_price_histories7

### `logging_setup.py`
**Functions**
- `setup_logging(level)`

### `resample.py`
**Functions**
- `_ensure_datetime_index(df, dt_col)`
- `_apply_ohlcv_agg(w, ohlc_cols, sum_cols, extra_aggs)` — Return a flat agg mapping suitable for pandas >= 1.5.
- `_flatten_agg_columns(r)`
- `_auto_label_closed(freq, label, closed)` — Start-anchored (MS, QS, AS, BMS, W-<DAY>) -> ('left','left')
- `bin_by_calendar(df, dt_col, freq, *, ohlc_cols, sum_cols, extra_aggs, label, closed)`
- `_season_id_from_exact_row(ts, season_label)`
- `bin_by_season(df, dt_col, *, season_col_exact, season_col_approx, n, ohlc_cols, sum_cols, extra_aggs)`

## `ta_lab2/analysis`

### `analysis/__init__.py`
_(no top-level classes or functions)_

### `analysis/feature_eval.py`
**Functions**
- `corr_matrix(df, columns)` — Pearson correlation among selected feature columns.
- `redundancy_report(df, columns, thresh)` — Flag highly correlated pairs (> thresh).
- `future_return(close, horizon, log)` — Compute forward return over N bars (target).
- `binarize_target(y, threshold)` — Label up/down based on threshold (e.g., future return > 0).
- `quick_logit_feature_weights(df, feature_cols, close_col, horizon, log_ret)` — If sklearn is available: fit a simple logit predicting (fwd_return > 0).
- `feature_target_correlations(df, feature_cols, close_col, horizon, log_ret)` — Rank features by absolute correlation with forward returns.

### `analysis/parameter_sweep.py`
**Functions**
- `grid(param_grid, run, freq, costs_bps)` — Exhaustive grid search over param_grid.
- `random_search(space, run, n_samples, seed, freq, costs_bps)` — Randomly sample combinations from a parameter space.

### `analysis/performance.py`
**Functions**
- `pct_change(close, periods)` — Simple % returns (no log).
- `log_returns(close)` — Log returns (safer additive over time).
- `equity_from_returns(returns, start_equity)` — Cumulative equity curve from returns.
- `_annualize_scale(freq)` — Return periods-per-year scaling for common frequencies.
- `sharpe(returns, risk_free, freq)` — Annualized Sharpe; risk_free given as per-period rate.
- `sortino(returns, risk_free, freq)` — Annualized Sortino using downside std.
- `max_drawdown(equity)` — Max drawdown (as a negative fraction).
- `calmar(returns, freq)` — Calmar = annualized return / |MaxDD|.
- `annual_return(returns, freq)` — CAGR-like annualized return from per-period returns.
- `hit_rate(returns)` — Fraction of positive-return periods.
- `turnover(position)` — Average absolute change in position between bars.
- `position_returns(close, position, costs_bps)` — Convert price series + position into strategy returns.
- `evaluate_signals(df, close_col, position_col, costs_bps, freq)` — Compute a compact metrics dict from a signal DataFrame containing close and position.

### `analysis/regime_eval.py`
**Functions**
- `metrics_by_regime(df, regime_col, close_col, position_col, costs_bps, freq)` — Group evaluation by regime values; returns one row per regime.
- `regime_transition_pnl(df, regime_col, close_col, position_col, costs_bps)` — Evaluate performance around regime switches (entering/leaving states).

## `ta_lab2/backtests`

### `backtests/__init__.py`
_(no top-level classes or functions)_

### `backtests/btpy_runner.py`
**Classes**
- `BTResult`

**Functions**
- `_ensure_backtesting_available()` — Raise a clear error if Backtesting.py is not installed.
- `_make_strategy_class(stop_pct, trail_pct)` — Create a Strategy subclass that uses precomputed entry/exit columns.
- `run_bt(df, entries, exits, fee_bps, slippage_bps, stop_pct, trail_pct)` — Run Backtesting.py using precomputed boolean signals.

### `backtests/costs.py`
**Classes**
- `CostModel`

### `backtests/metrics.py`
**Functions**
- `cagr(equity, freq_per_year)`
- `max_drawdown(equity)`
- `sharpe(returns, rf, freq_per_year)`
- `sortino(returns, rf, freq_per_year)`
- `mar(cagr_value, mdd_value)`
- `psr_placeholder(returns, rf, freq_per_year)` — Placeholder Probabilistic Sharpe Ratio (PSR).
- `summarize(equity, returns, freq_per_year)`

### `backtests/orchestrator.py`
**Classes**
- `MultiResult`

**Functions**
- `_leaderboard(df)` — Rank rows by MAR, then Sharpe, then CAGR (desc).
- `run_multi_strategy(df, strategies, splits, cost, price_col, freq_per_year)` — Orchestrate backtests for multiple strategies.

### `backtests/reports.py`
**Functions**
- `_require_matplotlib()`
- `save_table(df, out_path)` — Save a DataFrame to CSV (creates parent dirs).
- `equity_plot(equity, title, out_path)` — Plot an equity curve. If out_path is provided, saves a PNG.
- `leaderboard(results, group_cols)` — Rank parameter sets inside each group by MAR, then Sharpe, then CAGR.

### `backtests/splitters.py`
**Classes**
- `Split`

**Functions**
- `expanding_walk_forward(index, insample_years, oos_years)` — Build expanding-window walk-forward splits by calendar years.
- `fixed_date_splits(windows, prefix)` — Build splits from explicit date windows (inclusive).

### `backtests/vbt_runner.py`
**Classes**
- `SignalFunc` — Callable that turns a price DataFrame + params into (entries, exits, size).
- `CostModel` — Costs in basis points; funding is daily bps applied to gross position value.
- `Split`
- `ResultRow`
- `ResultBundle`

**Functions**
- `_cagr(equity, freq_per_year)`
- `_max_drawdown(equity)`
- `_sharpe(returns, rf, freq_per_year)`
- `run_vbt_on_split(df, entries, exits, size, cost, split, price_col, freq_per_year)` — Run vectorbt on a single time split and compute core metrics.
- `sweep_grid(df, signal_func, param_grid, splits, cost, price_col, freq_per_year)`

## `ta_lab2/features`

### `features/__init__.py`
_(no top-level classes or functions)_

### `features/calendar.py`
**Functions**
- `expand_datetime_features_inplace(df, base_timestamp_col, prefix, *, to_utc, add_moon)` — One-call datetime feature expansion.
- `expand_multiple_timestamps(df, cols, *, to_utc, add_moon)` — Expand several timestamp columns in one call (legacy test helper).

### `features/correlation.py`
**Functions**
- `acf(x, nlags, demean)`
- `pacf_yw(x, nlags)`
- `rolling_autocorr(s, lag, window)`
- `xcorr(a, b, max_lag, demean)`

### `features/ema.py`
**Functions**
- `compute_ema(s, period, *, adjust, min_periods, name, window, **kwargs)` — Series EMA with a Pandas-backed implementation.
- `_flip_for_direction(obj, direction)` — If data are newest-first, flip to chronological for diff/EMA, and tell caller
- `_maybe_round(s, round_places)`
- `_ensure_list(x)`
- `add_ema_columns(df, base_price_cols, ema_periods, *, direction, overwrite, round_places, adjust, min_periods, price_cols, **kwargs)` — For each `col` in base_price_cols and each `w` in ema_periods, add:
- `add_ema_d1(df, base_price_cols, ema_periods, *, direction, overwrite, round_places, price_cols, **kwargs)` — First difference of EMA:
- `add_ema_d2(df, base_price_cols, ema_periods, *, direction, overwrite, round_places, price_cols, **kwargs)` — Second difference of EMA:
- `add_ema(df, col, periods, prefix)` — Legacy wrapper: adds EMA columns for one price column.
- `prepare_ema_helpers(df, base_price_cols, ema_periods, *, direction, scale, overwrite, round_places, price_cols, periods, **kwargs)` — Ensure first/second EMA diffs exist, then add scaled helper columns for each
- `add_ema_diffs_longform(df, *, group_cols, ema_col, d1_col, d2_col, time_col, round_places)` — Compute d1 and d2 for a *long-form* EMA table and add them in-place.
- `build_daily_ema_tail_from_seeds(df, *, asset_id, seeds, tf_label, tf_days)` — Build an *incremental* daily EMA tail for a single asset id, given
- `_get_engine(db_url)`
- `build_daily_ema_frame(ids, start, end, ema_periods, *, db_url)` — Build a longform daily EMA DataFrame suitable for cmc_ema_daily:
- `write_daily_ema_to_db(ids, start, end, ema_periods, *, db_url, schema, out_table, update_existing)` — Compute daily EMAs for the given ids and upsert into cmc_ema_daily

### `features/ensure.py`
**Functions**
- `ensure_close(df)`
- `ensure_ema(df, span)`
- `ensure_rsi(df, n, col)`
- `ensure_macd(df, fast, slow, signal)`
- `ensure_adx(df, n)`
- `ensure_obv(df)`

### `features/feature_pack.py`
**Functions**
- `_annualization(freq)`
- `attach_core_features(df, freq, ema_periods, vol_windows, acorr_lags)` — df must be a single-timeframe OHLCV frame with a monotonic UTC 'timestamp'.

### `features/indicators.py`
**Functions**
- `_ema(s, span)`
- `_sma(s, window)`
- `_tr(high, low, close)`
- `_ensure_series(obj, *, col)` — Return a Series from either a Series or DataFrame+col.
- `_return(obj, series, out_col, *, inplace)` — Default behavior: return a **Series** (named).
- `rsi(obj, window, *, period, price_col, out_col, inplace)` — RSI (Wilder). Back-compat:
- `macd(obj, *, price_col, fast, slow, signal, out_cols, inplace)` — MACD (12/26/9 by default).
- `stoch_kd(obj, *, high_col, low_col, close_col, k, d, out_cols, inplace)` — Stochastic %K/%D (df input expected).
- `bollinger(obj, window, *, price_col, n_sigma, out_cols, inplace)` — Bollinger Bands.
- `atr(obj, window, *, period, high_col, low_col, close_col, out_col, inplace)` — Average True Range (simple rolling mean of TR, matching your original).
- `adx(obj, window, *, period, high_col, low_col, close_col, out_col, inplace)` — ADX (vectorized conditions, preserves original behavior).
- `obv(obj, *, price_col, volume_col, out_col, inplace)` — On-Balance Volume.
- `mfi(obj, window, *, period, high_col, low_col, close_col, volume_col, out_col, inplace)` — Money Flow Index. Default: return Series; if `inplace=True`, assign and return df.

### `features/resample.py`
**Functions**
- `_validate_ohlcv_columns(df)` — Ensure that a DataFrame has the standard OHLCV columns.
- `_ensure_ts_index(df, ts_col, copy)` — Ensure df has a DatetimeIndex based on ts_col.
- `resample_ohlcv(df, freq, agg, label, closed, strict)` — Generic OHLCV resampler.
- `normalize_timeframe_label(tf)` — Normalize a human-readable timeframe key to a pandas offset alias.
- `add_calendar_features(df, ts_col, inplace)` — Expand calendar features in-place using the shared calendar utilities.
- `resample_parquet_file(input_path, output_path, freq, *, ts_col, strict, label, closed)` — Load a parquet file, resample OHLCV, and write out another parquet file.
- `resample_to_tf(df, freq, *, strict, label, closed)` — Compatibility wrapper used by ema_multi_timeframe.py.

### `features/returns.py`
**Functions**
- `_coerce_cols(cols)` — Normalize None / str / sequence -> list[str].
- `_as_float_series(df, col)`
- `_b2b_change(s, *, mode, direction)` — Compute bar-to-bar change for a single Series.
- `_apply_b2b(df, *, cols, mode, suffix, extra_cols, round_places, direction)`
- `b2t_pct_delta(df, *, cols, columns, extra_cols, round_places, direction, open_col, close_col, **kwargs)` — Add bar-to-bar **percent** change columns for each requested column.
- `b2t_log_delta(df, *, cols, columns, extra_cols, round_places, direction, open_col, close_col, **kwargs)` — Add bar-to-bar **log** change columns for each requested column.
- `add_returns(df, *, cols, columns, extra_cols, round_places, direction, open_col, close_col, **kwargs)` — Backward-compatible wrapper that mirrors the original API and adds BOTH:

### `features/segments.py`
**Functions**
- `build_flip_segments(df, price_col, state_col, timestamp_col)` — Build contiguous segments of identical trend states.

### `features/trend.py`
**Functions**
- `compute_trend_labels(df, price_col, window, mode, flat_thresh, label_col)` — Compute trend labels for a given price series.

### `features/vol.py`
**Functions**
- `add_parkinson_vol(df, high_col, low_col, windows, annualize, periods_per_year)` — Parkinson (1980) range-based volatility estimator.
- `add_garman_klass_vol(df, open_col, high_col, low_col, close_col, windows, annualize, periods_per_year)` — Garman–Klass (1980) volatility estimator.
- `add_rogers_satchell_vol(df, open_col, high_col, low_col, close_col, windows, annualize, periods_per_year)` — Rogers–Satchell (1991) volatility estimator.
- `add_atr(df, period, open_col, high_col, low_col, close_col)` — Average True Range (Wilder).
- `add_logret_stdev_vol(df, logret_cols, windows, annualize, periods_per_year, ddof, prefix)` — Rolling std of log returns.
- `add_rolling_realized_batch(df, windows, which, annualize, periods_per_year, open_col, high_col, low_col, close_col)` — Compute realized vol (Parkinson, RS, GK) across windows.
- `add_rolling_vol_from_returns_batch(df, *, close_col, windows, types, annualize, periods_per_year, ddof, prefix, price_col, modes, direction)` — Rolling historical volatility (new + legacy API).
- `add_volatility_features(df, *, do_atr, do_parkinson, do_rs, do_gk, atr_period, ret_windows, ret_types, ret_annualize, ret_periods_per_year, ret_ddof, ret_prefix, rv_windows, rv_which, rv_annualize, rv_periods_per_year, open_col, high_col, low_col, close_col, rolling_windows, direction)` — Unified volatility orchestrator with legacy support.

## `ta_lab2/features/m_tf`

### `features/m_tf/__init__.py`
_(no top-level classes or functions)_

### `features/m_tf/ema_multi_tf_cal.py`
**Classes**
- `CalTfSpec`

**Functions**
- `_load_alpha_lookup(engine, schema, table)` — Expected minimum columns:
- `_normalize_daily(df)`
- `_load_calendar_tf_specs(engine, *, scheme)` — Load the CAL (non-anchor) calendar-aligned timeframe universe from public.dim_timeframe.
- `_bars_table_for_scheme(scheme)`
- `_load_canonical_closes_from_bars(engine, *, bars_table, ids, tfs, start, end)` — Returns canonical close rows from the bars table (is_partial_end = FALSE).
- `_compute_bar_ema_on_closes(close_prices, alpha_bar, min_periods)` — Compute EMA in bar-space on the sequence of canonical close prices.
- `build_multi_timeframe_ema_cal_frame(df_daily, *, tf_closes, tf_days_map, ema_periods, alpha_lut)` — Build spec-correct calendar-aligned multi-timeframe EMA frame.
- `write_multi_timeframe_ema_cal_to_db(engine_or_db_url, ids, *, scheme, start, end, update_existing, ema_periods, schema, out_table, alpha_schema, alpha_table)` — Compute calendar-aligned multi-timeframe EMAs and upsert into:

### `features/m_tf/ema_multi_tf_cal_anchor.py`
**Classes**
- `TimeframeSpec`

**Functions**
- `_engine(db_url)`
- `_table_has_column(eng, *, schema, table, column)`
- `_load_timeframes_from_dim_timeframe(eng, *, schema, dim_timeframe_table, calendar_scheme)` — Load anchored calendar timeframes from dim_timeframe (no hard-coded TFs).
- `_load_daily_close(eng, *, schema, daily_table, ids, start, end)` — Load daily close series (UTC timestamps) for ids in [start, end].
- `_load_anchor_bars(eng, *, schema, bars_table, ids, tfs, start, end)` — Load anchored bar snapshot rows for (id, tf).
- `_ema(series, period)` — Standard EMA with alpha=2/(period+1), with min_periods=period.
- `_alpha_daily_equivalent(tf_days, period)` — Convert a "bar-space" EMA alpha to a daily-step alpha using nominal tf_days.
- `_canonical_subset_diff(x, is_canonical)` — Canonical-only diff computed BETWEEN CANONICAL ROWS (not day-to-day).
- `_infer_is_canonical_bar_row(b)` — Infer which rows in the bar snapshot table represent the *canonical* bar close.
- `_build_one_id_tf(daily, bars_tf, *, tf_days_for_alpha, period)` — Build full daily-grid output for a single (id, tf, period).
- `write_multi_timeframe_ema_cal_anchor_to_db(ids, *, calendar_scheme, start, end, ema_periods, db_url, schema, dim_timeframe_table, daily_table, bars_table, out_table, update_existing, verbose)` — Compute anchored calendar EMAs (US or ISO) by consuming the pre-built

### `features/m_tf/ema_multi_tf_v2.py`
**Classes**
- `TfUniverse` — Resolved TF universe for v2.

**Functions**
- `resolve_tf_universe_v2(*, db_url, alignment_type, canonical_only)` — Resolve {tf: tf_days} from dim_timeframe.
- `compute_daily_ema(prices, *, horizon_days)` — Standard daily EMA over `prices` with smoothing horizon `horizon_days`.
- `compute_multi_tf_v2_for_asset(*, df_id, periods, tf_days_by_tf)` — Compute the v2 multi-timeframe DAILY EMA for a single asset id.
- `load_daily_prices(engine, *, ids, price_schema, price_table)`
- `load_last_ts_by_key(engine, *, ids, tfs, periods, out_schema, out_table)` — Return {(id, tf, period): last_ts} for existing rows.
- `refresh_ema_multi_tf_v2_incremental(*, engine, db_url, periods, ids, alignment_type, canonical_only, price_schema, price_table, out_schema, out_table)` — Incremental refresh of ema_multi_tf_v2.
- `refresh_ema_multi_tf_v2(*, engine, db_url, **kwargs)` — Alias for refresh_ema_multi_tf_v2_incremental.

### `features/m_tf/ema_multi_timeframe.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, close (and optionally open/high/low/volume).
- `_resolve_tf_day_timeframes(*, db_url, tf_subset)` — Return mapping: tf_label -> tf_days, sourced from dim_timeframe,
- `_load_bar_closes(*, ids, tf, db_url, schema, bars_table, end)` — Load canonical TF closes from the persisted tf_day bars table.
- `_synthetic_tf_day_bars_from_daily(*, df_id_daily, tf, tf_days)` — Fallback for v1 when persisted bars are missing.
- `build_multi_timeframe_ema_frame(ids, start, end, ema_periods, tf_subset, *, db_url, bars_schema, bars_table_tf_day)` — Build longform EMAs on a DAILY grid for all canonical tf_day timeframes
- `write_multi_timeframe_ema_to_db(ids, start, end, ema_periods, tf_subset, *, db_url, schema, out_table, update_existing, bars_schema, bars_table_tf_day)` — Compute multi-timeframe EMAs (tf_day family) using dim_timeframe and persisted bars

### `features/m_tf/views.py`
_(no top-level classes or functions)_

## `ta_lab2/features/m_tf/ema_research`

### `features/m_tf/ema_research/mutli_tf_v1_vs_v2.py`
**Functions**
- `get_ema_series(df_mt, tf, period)` — Return EMA series indexed by ts for given tf/period.

## `ta_lab2/features/m_tf/old`

### `features/m_tf/old/ema_multi_tf_cal_AM20251208_jumpsOnEma.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(engine, ids, start, end, update_existing, ema_periods, tfs, schema, out_table)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_PM20251207_774_lines.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(engine, ids, start, end, update_existing, ema_periods, tfs, schema, out_table)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_all_bar_alpha.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(engine, ids, start, end, update_existing, ema_periods, tfs, schema, out_table)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_anchor_pre-bars.py`
**Functions**
- `_resolve_calendar_timeframes_anchor(db_url, tfs)` — Resolve which calendar-aligned timeframes to use for the anchor run.
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes_anchor(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset_anchor(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_anchor_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of year-anchored, calendar-aligned
- `write_multi_timeframe_ema_cal_anchor_to_db(ids, start, end, ema_periods, tfs, db_url, schema, price_table, out_table, update_existing)` — Compute year-anchored calendar-aligned multi-timeframe EMAs with

### `features/m_tf/old/ema_multi_tf_cal_anchor_pre-dim.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes_anchor(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset_anchor(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_anchor_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of year-anchored, calendar-aligned
- `write_multi_timeframe_ema_cal_anchor_to_db(ids, start, end, ema_periods, tfs, db_url, schema, price_table, out_table, update_existing)` — Compute year-anchored calendar-aligned multi-timeframe EMAs with

### `features/m_tf/old/ema_multi_tf_cal_anchor_predimUpdate20251219.py`
**Classes**
- `TimeframeSpec`

**Functions**
- `_engine(db_url)`
- `_table_has_column(eng, *, schema, table, column)`
- `_load_timeframes_from_dim_timeframe(eng, *, schema, dim_timeframe_table, calendar_scheme)` — Load anchored calendar timeframes from dim_timeframe (no hard-coded TFs).
- `_load_daily_close(eng, *, schema, daily_table, ids, start, end)` — Load daily close series (UTC timestamps) for ids in [start, end].
- `_load_anchor_bars(eng, *, schema, bars_table, ids, tfs, start, end)` — Load anchored bar snapshot rows for (id, tf).
- `_ema(series, period)` — Standard EMA with alpha=2/(period+1), with min_periods=period.
- `_alpha_daily_equivalent(tf_days, period)` — Convert a "bar-space" EMA alpha to a daily-step alpha using nominal tf_days.
- `_canonical_subset_diff(x, is_canonical)` — Canonical-only diff computed BETWEEN CANONICAL ROWS (not day-to-day).
- `_infer_is_canonical_bar_row(b)` — Infer which rows in the bar snapshot table represent the *canonical* bar close.
- `_build_one_id_tf(daily, bars_tf, *, tf_days_for_alpha, period)` — Build full daily-grid output for a single (id, tf, period).
- `write_multi_timeframe_ema_cal_anchor_to_db(ids, *, calendar_scheme, start, end, ema_periods, db_url, schema, dim_timeframe_table, daily_table, bars_table, out_table, update_existing, verbose)` — Compute anchored calendar EMAs (US or ISO) by consuming the pre-built

### `features/m_tf/old/ema_multi_tf_cal_old.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(ids, start, end, ema_periods, tfs, db_url, schema, price_table, out_table, update_existing)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_old_2.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(engine, ids, start, end, update_existing, ema_periods, tfs, schema, out_table)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_post-dim.py`
**Functions**
- `_resolve_calendar_timeframes(db_url, tfs)` — Resolve which calendar-aligned timeframes to use for this run.
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical month-end closes for month-based calendar-aligned tfs.
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(engine, ids, start, end, update_existing, ema_periods, tfs, schema, out_table)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_pre-bars.py`
**Functions**
- `_load_alpha_lookup(engine, *, schema, table)` — Load (tf, period) -> {alpha_daily_eq, alpha_bar, tf_days, effective_days} from ema_alpha_lookup.
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url, alpha_schema, alpha_table)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(engine, ids, start, end, update_existing, ema_periods, tfs, schema, out_table, alpha_schema, alpha_table)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_pre-dim.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_compute_monthly_canonical_closes(df_id, tf_label)` — Compute canonical close timestamps for month-based timeframes using
- `_compute_tf_closes_by_asset(daily, ids, tf_label, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_cal_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of calendar-aligned multi-timeframe EMAs
- `write_multi_timeframe_ema_cal_to_db(engine, ids, start, end, update_existing, ema_periods, tfs, schema, out_table)` — Compute calendar-aligned multi-timeframe EMAs with preview-style roll

### `features/m_tf/old/ema_multi_tf_cal_predimUpdate20251219.py`
**Classes**
- `CalTfSpec`

**Functions**
- `_load_alpha_lookup(engine, schema, table)` — Expected minimum columns:
- `_normalize_daily(df)`
- `_load_calendar_tf_specs(engine, *, scheme)` — IMPORTANT:
- `_bars_table_for_scheme(scheme)`
- `_load_canonical_closes_from_bars(engine, *, bars_table, ids, tfs, start, end)` — Returns canonical close rows from the bars table (is_partial_end = FALSE).
- `_compute_bar_ema_on_closes(close_prices, alpha_bar, min_periods)` — Compute EMA in bar-space on the sequence of canonical close prices.
- `build_multi_timeframe_ema_cal_frame(df_daily, *, tf_closes, tf_days_map, ema_periods, alpha_lut)` — Build spec-correct calendar-aligned multi-timeframe EMA frame.
- `write_multi_timeframe_ema_cal_to_db(engine_or_db_url, ids, *, scheme, start, end, update_existing, ema_periods, schema, out_table, alpha_schema, alpha_table)` — Compute calendar-aligned multi-timeframe EMAs and upsert into:

### `features/m_tf/old/ema_multi_tf_v2_oldasof_20251219.py`
**Classes**
- `TfUniverse` — Resolved TF universe for v2.

**Functions**
- `resolve_tf_universe_v2(*, db_url, alignment_type, canonical_only)` — Resolve {tf: tf_days} from dim_timeframe.
- `compute_daily_ema(prices, *, horizon_days)` — Standard daily EMA over `prices` with smoothing horizon `horizon_days`.
- `compute_multi_tf_v2_for_asset(*, df_id, periods, tf_days_by_tf)` — Compute the v2 multi-timeframe DAILY EMA for a single asset id.
- `load_daily_prices(engine, *, ids, price_schema, price_table)`
- `load_last_ts_by_key(engine, *, ids, tfs, periods, out_schema, out_table)` — Return {(id, tf, period): last_ts} for existing rows.
- `refresh_ema_multi_tf_v2_incremental(*, engine, db_url, periods, ids, alignment_type, canonical_only, price_schema, price_table, out_schema, out_table)` — Incremental refresh of ema_multi_tf_v2.
- `refresh_ema_multi_tf_v2(*, engine, db_url, **kwargs)` — Alias for refresh_ema_multi_tf_v2_incremental.

### `features/m_tf/old/ema_multi_tf_v2_pre-bar.py`
**Classes**
- `CliArgs`

**Functions**
- `_resolve_timeframe_tf_days(db_url, timeframe_tf_days)` — Resolve the mapping {tf: tf_days} to use for v2.
- `compute_daily_ema(prices, horizon_days)` — Compute a standard daily EMA over 'prices' with a smoothing horizon
- `compute_multi_tf_v2_for_asset(df_id, periods, timeframe_tf_days)` — Compute the v2 multi-timeframe DAILY EMA for a single asset (one id).
- `parse_args()`
- `load_daily_prices(engine, ids)` — Load daily price history from cmc_price_histories7.
- `load_last_ts_by_id(engine, ids)` — Look at ema_multi_tf_v2 and get the latest ts per id.
- `refresh_ema_multi_tf_v2_incremental(engine, periods, timeframe_tf_days, ids, db_url)` — Incremental refresh of ema_multi_tf_v2.
- `main()`

### `features/m_tf/old/ema_multi_tf_v2_pre-dim.py`
**Classes**
- `CliArgs`

**Functions**
- `compute_daily_ema(prices, horizon_days)` — Compute a standard daily EMA over 'prices' with a smoothing horizon
- `compute_multi_tf_v2_for_asset(df_id, periods, timeframe_tf_days)` — Compute the v2 multi-timeframe DAILY EMA for a single asset (one id).
- `parse_args()`
- `load_daily_prices(engine, ids)` — Load daily price history from cmc_price_histories7.
- `load_last_ts_by_id(engine, ids)` — Look at ema_multi_tf_v2 and get the latest ts per id.
- `refresh_ema_multi_tf_v2_incremental(engine, periods, timeframe_tf_days, ids)` — Incremental refresh of ema_multi_tf_v2.
- `main()`

### `features/m_tf/old/ema_multi_timeframe_pre-bars.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_resample_ohlcv_for_tf(df_id, freq)` — Simple local OHLCV resampler for a single asset's daily data.
- `_compute_tf_closes_by_asset(daily, ids, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `_resolve_timeframes_from_dim_timeframe(*, db_url, tfs)` — Resolve the set of (tf_label -> (freq, tf_days)) to use.
- `build_multi_timeframe_ema_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of multi-timeframe EMAs on a DAILY grid.
- `write_multi_timeframe_ema_to_db(ids, start, end, ema_periods, tfs, *, db_url, schema, price_table, out_table, update_existing)` — Compute multi-timeframe EMAs with preview-style roll and upsert into

### `features/m_tf/old/ema_multi_timeframe_pre-dim_tf.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, open, high, low, close, volume
- `_resample_ohlcv_for_tf(df_id, freq)` — Simple local OHLCV resampler for a single asset's daily data.
- `_compute_tf_closes_by_asset(daily, ids, freq)` — For each asset id, compute the *actual daily timestamps* that are the
- `build_multi_timeframe_ema_frame(ids, start, end, ema_periods, tfs, *, db_url)` — Build a longform DataFrame of multi-timeframe EMAs on a DAILY grid.
- `write_multi_timeframe_ema_to_db(ids, start, end, ema_periods, tfs, *, db_url, schema, price_table, out_table, update_existing)` — Compute multi-timeframe EMAs with preview-style roll and upsert into

### `features/m_tf/old/ema_multi_timeframe_predimUpdate20251219.py`
**Functions**
- `_normalize_daily(daily)` — Ensure daily OHLCV has columns: id, ts, close (and optionally open/high/low/volume).
- `_resolve_tf_day_timeframes(*, db_url, tf_subset)` — Return mapping: tf_label -> tf_days, sourced from dim_timeframe,
- `_load_bar_closes(*, ids, tf, db_url, schema, bars_table, end)` — Load canonical TF closes from the persisted tf_day bars table.
- `_synthetic_tf_day_bars_from_daily(*, df_id_daily, tf, tf_days)` — Fallback for v1 when persisted bars are missing.
- `build_multi_timeframe_ema_frame(ids, start, end, ema_periods, tf_subset, *, db_url, bars_schema, bars_table_tf_day)` — Build longform EMAs on a DAILY grid for all canonical tf_day timeframes
- `write_multi_timeframe_ema_to_db(ids, start, end, ema_periods, tf_subset, *, db_url, schema, out_table, update_existing, bars_schema, bars_table_tf_day)` — Compute multi-timeframe EMAs (tf_day family) using dim_timeframe and persisted bars

## `ta_lab2/io`

## `ta_lab2/live`

## `ta_lab2/pipelines`

### `pipelines/__init__.py`
_(no top-level classes or functions)_

### `pipelines/btc_pipeline.py`
**Functions**
- `_filter_kwargs(func, kwargs)`
- `_try_call_with_windows(func, df, ema_windows, **kwargs)`
- `_call_ema_comovement(df, ema_windows, **kwargs)`
- `_call_ema_hierarchy(df, ema_windows, **kwargs)`
- `_call_build_segments(df, *, price_col, state_col, date_col)`
- `_infer_timestamp_col(df, fallback)`
- `_coerce_df(df_or_path)`
- `_maybe_from_config(value, default)`
- `_find_default_csv()` — Best-effort discovery of a BTC price CSV in common spots.
- `run_btc_pipeline(csv_path, *, price_cols, ema_windows, returns_modes, returns_windows, resample, do_calendar, do_indicators, do_returns, do_volatility, do_ema, do_regimes, do_segments, config)` — End-to-end, testable pipeline aligned to the modular ta_lab2 layout.
- `main(csv_path, config_path, save_artifacts)` — Run the BTC pipeline end-to-end and (optionally) write artifacts.

## `ta_lab2/regimes`

### `regimes/__init__.py`
_(no top-level classes or functions)_

### `regimes/comovement.py`
**Functions**
- `_ensure_sorted(df, on)`
- `build_alignment_frame(low_df, high_df, *, on, low_cols, high_cols, suffix_low, suffix_high, direction)` — Merge-asof align low timeframe rows with the most recent high timeframe row.
- `sign_agreement(df, col_a, col_b, *, out_col)` — Mark True where signs of two series match (strictly > 0).
- `rolling_agreement(df, col_a, col_b, *, window, out_col, min_periods)` — Rolling share of days where signs match over a window.
- `forward_return_split(df, agree_col, fwd_ret_col)` — Compare forward returns when agree==True vs False.
- `lead_lag_max_corr(df, col_a, col_b, lags)` — Find lag that maximizes Pearson correlation between two columns.
- `_find_ema_columns(df, token)` — Auto-detect EMA columns by substring token (default: '_ema_').
- `_pairwise(cols)`
- `compute_ema_comovement_stats(df, *, ema_cols, method, agree_on_sign_of_diff, diff_window)` — Compute co-movement stats among EMA series.
- `compute_ema_comovement_hierarchy(df, *, ema_cols, method)` — Build a simple ordering (“hierarchy”) of EMA columns from the correlation matrix.

### `regimes/data_budget.py`
**Classes**
- `DataBudgetContext`

**Functions**
- `_count(df)`
- `assess_data_budget(*, monthly, weekly, daily, intraday)`

### `regimes/feature_utils.py`
**Functions**
- `_ema(s, n)`
- `add_ema_pack(df, *, tf, price_col)` — Add the EMA set used by our labelers per time frame.
- `add_atr14(df, *, price_col)` — Adds a lightweight ATR(14) column named 'atr14'.
- `ensure_regime_features(df, *, tf, price_col)` — One-shot: add EMAs + ATR columns appropriate for this TF.

### `regimes/flips.py`
**Functions**
- `sign_from_series(df, src_col, out_col)` — Make a {-1,0,+1} sign column from a numeric series.
- `detect_flips(df, sign_col, min_separation)` — Return indices where the sign changes, enforcing a minimum bar gap.
- `label_regimes_from_flips(n_rows, flip_idx, start_regime)` — Convert flip indices to piecewise-constant regime IDs: 0,1,2,...
- `attach_regimes(df, regime_ids, col)` — Attach regime IDs to a dataframe (length must match).
- `regime_stats(df, regime_col, ret_col)` — Per-regime summary: n_bars, start/end timestamps, duration, cumulative & average returns.

### `regimes/labels.py`
**Functions**
- `label_trend_basic(df, *, price_col, ema_fast, ema_mid, ema_slow, adx_col, adx_floor, confirm_bars)` — Up if price>slow and fast>mid for confirm_bars; Down if inverse; else Sideways.
- `_percentile_series(x)`
- `label_vol_bucket(df, *, atr_col, price_col, window, mode, low_cutoff, high_cutoff)`
- `label_liquidity_bucket(df, *, spread_col, slip_col, window)` — If spread/slippage columns exist, compare to rolling medians.
- `compose_regime_key(trend, vol, liq)`
- `label_layer_monthly(monthly, *, mode, price_col, ema_fast, ema_mid, ema_slow)`
- `label_layer_weekly(weekly, *, mode, price_col, ema_fast, ema_mid, ema_slow)`
- `label_layer_daily(daily, *, mode, price_col, ema_fast, ema_mid, ema_slow)`
- `label_layer_intraday(intraday, *, price_col, ema_fast, ema_mid, ema_slow)`

### `regimes/old_run_btc_pipeline.py`
**Functions**
- `_clean_headers(cols)` — Strip spaces, lower, collapse internal spaces -> single underscores.
- `_to_num(s)` — Coerce numeric fields (remove commas, turn '-'/'' to NaN).
- `_parse_epoch_series(x)` — Try seconds vs milliseconds automatically.
- `enrich(bars)`
- `_scal(s)`
- `check_boundary(dt_str)`

### `regimes/policy_loader.py`
**Functions**
- `_default_policy_yaml_path()` — Default expected location: <repo_root>/configs/regime_policies.yaml
- `load_policy_table(yaml_path)` — Load a policy overlay from YAML and merge it over DEFAULT_POLICY_TABLE.

### `regimes/proxies.py`
**Classes**
- `ProxyInputs`
- `ProxyOutcome`

**Functions**
- `_is_weekly_up_normal(weekly)`
- `infer_cycle_proxy(inp)` — If the asset lacks L0 history, use a broad market proxy to *tighten* net exposure caps.
- `infer_weekly_macro_proxy(inp)` — If child has <52 weekly bars, borrow the parent regime to *tighten* size.

### `regimes/regime_inspect.py`
**Functions**
- `_read_df(path)`
- `main()`

### `regimes/resolver.py`
**Classes**
- `TightenOnlyPolicy`

**Functions**
- `_match_policy(regime_key, table)`
- `apply_hysteresis(prev_key, new_key, *, min_change)` — Minimal form: if prev == new or min_change==0 -> accept.
- `_tighten(dst, src)`
- `resolve_policy_from_table(policy_table, *, L0, L1, L2, L3, L4, base)` — Combine layer regimes into a single tighten-only policy using the provided policy_table.
- `resolve_policy(*, L0, L1, L2, L3, L4, base)` — Back-compat wrapper that uses the in-code DEFAULT_POLICY_TABLE.

### `regimes/run_btc_pipeline.py`
**Functions**
- `run_btc_pipeline(csv_path, out_dir, ema_windows, resample, *, do_calendar, do_indicators, do_returns, do_volatility, do_ema, do_regimes, do_segments, config)` — Orchestrate the BTC pipeline end-to-end.

### `regimes/segments.py`
_(no top-level classes or functions)_

### `regimes/telemetry.py`
**Classes**
- `RegimeSnapshot`

**Functions**
- `append_snapshot(path, snap, extra)` — Append one row (creating the file with header if new). Extras (e.g., pnl) can be included.

## `ta_lab2/scripts`

### `scripts/__init__.py`
_(no top-level classes or functions)_

### `scripts/figure out.py`
**Functions**
- `get_all_asset_ids(db_url)` — Load all distinct asset ids from cmc_price_histories7 as strings.
- `main(db_url)` — Refresh cmc_ema_daily and ema_multi_tf for ALL assets in cmc_price_histories7,

### `scripts/open_ai_script.py`
**Functions**
- `load_stats_csv(path)`
- `ask_chatgpt_about_stats(csv_text, run_label)`

## `ta_lab2/scripts/bars`

### `scripts/bars/audit_price_bars_integrity.py`
**Classes**
- `TfSpec`

**Functions**
- `_log(msg)`
- `get_engine()`
- `parse_ids(engine, ids_arg, daily_table)`
- `table_exists(engine, full_name)`
- `get_columns(engine, full_name)`
- `best_ts_col(colset)`
- `_load_dim_timeframe(engine, dim_tf)`
- `tfs_for_family(df_tf, family)` — Mirrors your current conventions:
- `run_coverage(engine, ids, dim_tf, out_csv)`
- `audit_table_summary(engine, table, ids)` — Produces per-(table,id,tf) metrics, based on whatever columns exist.
- `run_audit(engine, ids, out_csv)`
- `load_tf_specs(engine, dim_tf)`
- `fetch_canonical_closes(engine, table, ids)`
- `spacing_eval(ts, spec)`
- `barseq_continuity_eval(bar_seq)` — Returns (n_gaps, max_gap) on sorted bar_seq values.
- `run_spacing(engine, ids, dim_tf, out_csv)`
- `get_tf_pairs(engine, table, ids, max_tfs_per_id)`
- `pick_sample_cols(colset)`
- `sample_group(engine, table, cols, id_, tf, per_group)`
- `run_samples(engine, ids, per_group, max_tfs_per_id, out_csv)`
- `main()`

### `scripts/bars/audit_price_bars_samples.py`
**Functions**
- `_log(msg)`
- `get_engine()`
- `parse_ids(engine, ids_arg, daily_table)`
- `table_exists(engine, full_name)`
- `get_columns(engine, full_name)`
- `get_tf_list(engine, table, ids, max_tfs)` — Returns distinct (id, tf) pairs to sample.
- `pick_cols(colset)` — Choose a readable, cross-table column subset.
- `best_ts_col(colset)`
- `sample_group(engine, table, cols, id_, tf, per_group)` — Return last N rows for a given (id, tf) group.
- `main()`

### `scripts/bars/audit_price_bars_tables.py`
**Functions**
- `_log(msg)`
- `get_engine()`
- `parse_ids(engine, ids_arg, daily_table)`
- `table_exists(engine, full_name)`
- `get_columns(engine, full_name)`
- `audit_table(engine, table, ids)` — Produces per-(table,id,tf) metrics. Uses whatever columns exist in the table.
- `main()`

### `scripts/bars/refresh_price_bars_multi_tf.py`
**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url)`
- `parse_ids(values, db_url)`
- `load_daily_min_max(db_url, ids)`
- `load_daily_prices_for_id(*, db_url, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `load_last_snapshot_info(db_url, bars_table, id_, tf)` — Returns the latest snapshot row for (id, tf), plus:
- `load_last_bar_snapshot_row(db_url, bars_table, id_, tf, bar_seq)` — Load the latest snapshot row for a specific bar_seq.
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_tf_list_from_dim_timeframe(*, db_url, include_non_canonical)` — Load the TF list for price_bars_multi_tf from public.dim_timeframe.
- `_make_day_time_open(ts)`
- `_has_missing_days(ts)`
- `_count_missing_days(ts)` — Count missing *interior* days based on >1-day gaps between observed timestamps.
- `build_snapshots_for_id(df_id, *, tf_days, tf_label)` — Full build for a single id + tf_days, emitting ONE ROW PER DAY per bar_seq (append-only snapshots).
- `build_all_snapshots(daily, tf_list)`
- `make_upsert_sql(bars_table)` — IMPORTANT: conflict target includes time_close to support append-only snapshots.
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tf_list, bars_table, state_table)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_anchor_iso.py`
**Classes**
- `AnchorSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `_validate_daily_required_cols(df, *, id_)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)`
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_, tfs)` — Latest snapshot row per tf for this id.
- `load_last_snapshot_row(db_url, bars_table, id_, tf)`
- `load_anchor_specs_from_dim_timeframe(db_url)` — Selection policy (matches the pasted script #1):
- `_last_day_of_month(d)`
- `_add_months(month_start, months)`
- `_week_start_iso_monday(d)`
- `_week_index_iso(d)`
- `_week_group_bounds_iso(d, n_weeks)`
- `_month_group_bounds_anchored(d, n_months)`
- `_year_group_bounds_anchored(d, n_years)`
- `anchor_window_for_day(d, spec)`
- `_months_diff(a, b)`
- `bar_seq_for_window_start(first_window_start, window_start, spec)`
- `_expected_days(window_start, window_end)`
- `_count_days_remaining(window_end, cur_day)`
- `_missing_days_stats(*, bar_start_eff, snapshot_day, idx_by_day)` — Returns:
- `_lookback_days_for_spec(spec)` — Conservative lookback window (in local calendar days) to guarantee we can recompute
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)`
- `_build_snapshots_full_history_for_id_spec(df_id, *, spec, tz, daily_min_day, fail_on_internal_gaps)`
- `_build_incremental_snapshots_for_id_spec(df_slice, *, spec, tz, daily_min_day, first_window_start, start_day, end_day, last_snapshot_row, fail_on_internal_gaps)`
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table, fail_on_internal_gaps)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_anchor_iso_pre-partial-end.py`
**Classes**
- `AnchorSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)`
- `load_last_bar_info_for_id_tfs(db_url, bars_table, id_, tfs)`
- `load_time_close_for_bar_seq(db_url, bars_table, id_, tf, bar_seq)`
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `delete_bars_for_id_tf_from_seq(db_url, bars_table, id_, tf, bar_seq_from)`
- `load_anchor_specs_from_dim_timeframe(db_url)` — Load ISO anchored timeframes (partial start/end allowed) from dim_timeframe.
- `_last_day_of_month(d)`
- `_month_start(d)`
- `_add_months(month_start, months)`
- `_week_start_iso_monday(d)`
- `_week_index_iso(d)`
- `_week_group_bounds_iso(d, n_weeks)`
- `_month_group_bounds_anchored(d, n_months)`
- `_year_group_bounds_anchored(d, n_years)`
- `_bounds_for_date(d, spec)`
- `_iter_anchor_windows_from(start_day, last_day, spec)` — Generate anchored windows starting from the window containing start_day.
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)`
- `_build_bars_from_windows(df_slice, *, spec, tz, windows, start_bar_seq, prev_close_for_first, fail_on_internal_gaps)` — Build bars for df_slice over provided windows. Bars are assigned sequential bar_seq
- `_build_full_history_for_id_spec(df_id, *, spec, tz, fail_on_internal_gaps)`
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table, fail_on_internal_gaps)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_anchor_us.py`
**Classes**
- `AnchorSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_, tfs)` — Batch-load latest snapshot row for a single id across multiple tfs.
- `load_last_snapshot_row(db_url, bars_table, id_, tf)` — Full latest snapshot row for a given (id, tf) (used for carry-forward).
- `load_anchor_specs_from_dim_timeframe(db_url)` — Load US anchored timeframes (partial bars allowed) from dim_timeframe.
- `_last_day_of_month(d)`
- `_add_months(month_start, months)`
- `_week_start_us_sunday(d)`
- `_week_index_us(d)`
- `_week_group_bounds_us(d, n_weeks)`
- `_month_group_bounds_anchored(d, n_months)`
- `_year_group_bounds_anchored(d, n_years)`
- `anchor_window_for_day(d, spec)`
- `_months_diff(a, b)`
- `bar_seq_for_window_start(first_window_start, window_start, spec)` — Deterministic 1-based bar_seq for a window, relative to the first produced anchored window.
- `_expected_days(window_start, window_end)`
- `_lookback_days_for_spec(spec)` — Conservative lookback window (in local calendar days) to guarantee we can recompute
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)`
- `_missing_days_stats(*, bar_start_eff, snapshot_day, idx_by_day, id_val, tf, win_start, win_end, fail_on_internal_gaps)` — Compute missing-day counts for expected range [bar_start_eff .. snapshot_day].
- `_count_days_remaining(win_start, win_end, snapshot_day)`
- `_build_snapshots_full_history_for_id_spec(df_id, *, spec, tz, daily_min_day, fail_on_internal_gaps)`
- `_build_incremental_snapshots_for_id_spec(df_slice, *, spec, tz, daily_min_day, first_window_start, start_day, end_day, last_snapshot_row, fail_on_internal_gaps)`
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table, fail_on_internal_gaps)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_anchor_us_pre-partial-end.py`
**Classes**
- `AnchorSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `load_last_bar_info_for_id_tfs(db_url, bars_table, id_, tfs)` — Batch-load last bar info for a single id across multiple tfs.
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `delete_bars_for_id_tf_from_seq(db_url, bars_table, id_, tf, bar_seq_min)` — Delete bars for (id, tf) with bar_seq >= bar_seq_min.
- `load_anchor_specs_from_dim_timeframe(db_url)` — Load US anchored (calendar_anchor) timeframes with partial bars allowed.
- `_last_day_of_month(d)`
- `_month_start(d)`
- `_add_months(month_start, months)`
- `_year_start(d)`
- `_week_start_us_sunday(d)`
- `_week_index_us(d)` — Global week index for the US week containing d, anchored to REF_SUNDAY.
- `_week_group_bounds_us(d, n_weeks)` — For a date d, return (group_start_sunday, group_end_saturday) for n_weeks block,
- `_month_group_bounds_anchored(d, n_months)` — Anchored month grouping inside calendar years:
- `_year_group_bounds_anchored(d, n_years)` — Anchored multi-year windows on calendar-year blocks.
- `anchor_window_for_day(d, spec)` — Return the anchored (window_start, window_end) for local date d given spec.
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)` — We assume one daily row per local calendar date. If duplicates exist,
- `_iter_anchor_windows_intersecting(first_day, last_day, spec)` — Generate anchored windows that intersect [first_day,last_day].
- `_build_bars_for_id_spec_full(df_id, *, spec, tz, fail_on_internal_gaps)` — Full rebuild for one id/spec across all available data.
- `_build_bars_for_id_spec_from_window_start(df_slice, *, spec, tz, fail_on_internal_gaps, window_start, last_day, base_bar_seq, boundary_prev_close)` — Build bars for one id/spec starting from a specific anchored window_start (inclusive),
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table, fail_on_internal_gaps)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_iso.py`
**Classes**
- `CalIsoSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_, tfs)` — Batch-load latest snapshot row for a single id across multiple tfs.
- `load_last_snapshot_row(db_url, bars_table, id_, tf)` — Full latest snapshot row (needed for incremental aggregate carry-forward).
- `load_cal_specs_from_dim_timeframe(db_url)` — Load calendar-aligned, FULL-PERIOD (non-anchor) ISO timeframes.
- `_last_day_of_month(d)`
- `_add_months(d, months)`
- `_month_start(d)`
- `_year_start(d)`
- `_week_start_monday(d)`
- `_compute_anchor_start(first_day, unit)` — First FULL period start AFTER the data begins (full-period policy).
- `_bar_end_for_start(bar_start, n, unit)`
- `_expected_days(bar_start, bar_end)`
- `_months_diff(a, b)` — months from a -> b (a and b assumed at first-of-month boundaries)
- `_bar_index_for_day(anchor_start, d, n, unit)` — 0-based bar index within this spec, anchored at anchor_start.
- `_bar_start_for_index(anchor_start, idx, n, unit)`
- `_missing_days_metrics(*, bar_start, snap_day, avail_dates, max_list)` — Compute missing-day diagnostics for expected local dates in [bar_start, snap_day].
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)`
- `_build_snapshots_full_history_for_id_spec(df_id, *, spec, tz)` — Full rebuild: emit one snapshot row per day from anchor_start onward.
- `_build_incremental_snapshots_for_id_spec(df_slice, *, spec, tz, anchor_start, start_day, end_day, last_snapshot_row)` — Incremental: emit snapshot rows for local days in [start_day, end_day], inclusive.
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_iso_pre-partial-end.py`
**Classes**
- `CalSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `load_last_bar_info_for_id_tfs(db_url, bars_table, id_, tfs)` — Batch-load last bar info for a single id across multiple tfs.
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `load_cal_specs_from_dim_timeframe(db_url)` — Load ISO-week + CAL-month/year, full-period-only timeframes from dim_timeframe.
- `_last_day_of_month(d)`
- `_add_months(d, months)`
- `_month_start(d)`
- `_year_start(d)`
- `_week_start_monday(d)`
- `_compute_anchor_start(first_day, unit)` — First FULL period start AFTER the data begins (full-period policy).
- `_bar_end_for_start(bar_start, n, unit)`
- `_expected_days(bar_start, bar_end)`
- `_advance_start(bar_start, n, unit)`
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)` — We assume one daily row per local calendar date. If duplicates exist,
- `_build_full_history_for_id_spec(df_id, *, spec, tz)` — Build bars from scratch for one id/spec (full history), full periods only.
- `_build_incremental_new_bars_for_id_spec(df_slice, *, spec, tz, next_bar_start, last_day, last_time_close, last_bar_seq)` — Build ONLY new full bars starting at next_bar_start (already aligned),
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_us.py`
**Classes**
- `CalSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_, tfs)` — Batch-load latest snapshot row for a single id across multiple tfs.
- `load_last_snapshot_row(db_url, bars_table, id_, tf)` — Full latest snapshot row (needed for incremental aggregate carry-forward).
- `load_cal_specs_from_dim_timeframe(db_url)` — Load calendar-aligned, FULL-PERIOD (non-anchor) US timeframes.
- `_last_day_of_month(d)`
- `_add_months(d, months)`
- `_month_start(d)`
- `_year_start(d)`
- `_week_start_sunday(d)`
- `_compute_anchor_start(first_day, unit)` — First FULL period start AFTER the data begins (full-period policy).
- `_bar_end_for_start(bar_start, n, unit)`
- `_expected_days(bar_start, bar_end)`
- `_months_diff(a, b)` — months from a -> b (a and b assumed at first-of-month boundaries)
- `_bar_index_for_day(anchor_start, d, n, unit)` — 0-based bar index within this spec, anchored at anchor_start.
- `_bar_start_for_index(anchor_start, idx, n, unit)`
- `_missing_days_metrics(*, bar_start, snap_day, avail_dates, max_list)` — Compute missing-day diagnostics for expected local dates in [bar_start, snap_day].
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)`
- `_build_snapshots_full_history_for_id_spec(df_id, *, spec, tz)` — Full rebuild: emit one snapshot row per day from anchor_start onward.
- `_build_incremental_snapshots_for_id_spec(df_slice, *, spec, tz, anchor_start, start_day, end_day, last_snapshot_row)` — Incremental: emit snapshot rows for local days in [start_day, end_day], inclusive.
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_cal_us_pre-partial-end.py`
**Classes**
- `CalSpec`

**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url, daily_table)`
- `parse_ids(values, db_url, daily_table)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_daily_min_max(db_url, daily_table, ids)`
- `load_daily_prices_for_id(*, db_url, daily_table, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `load_last_bar_info(db_url, bars_table, id_, tf)` — Return dict with last_bar_seq, last_time_close for existing bars, or None if none.
- `load_last_bar_info_for_id_tfs(db_url, bars_table, id_, tfs)` — Batch-load last bar info for a single id across multiple tfs.
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `load_cal_specs_from_dim_timeframe(db_url)` — Load calendar-aligned, full-period-only timeframes for _cal_us.
- `_last_day_of_month(d)`
- `_add_months(d, months)`
- `_month_start(d)`
- `_year_start(d)`
- `_week_start_sunday(d)`
- `_compute_anchor_start(first_day, unit)` — First FULL period start AFTER the data begins (full-period policy).
- `_bar_end_for_start(bar_start, n, unit)`
- `_expected_days(bar_start, bar_end)`
- `_advance_start(bar_start, n, unit)`
- `_make_day_time_open(ts)`
- `_assert_one_row_per_local_day(df, *, id_, tf, tz)` — We assume one daily row per local calendar date. If duplicates exist,
- `_build_full_history_for_id_spec(df_id, *, spec, tz)` — Build bars from scratch for one id/spec (full history), full periods only.
- `_build_incremental_new_bars_for_id_spec(df_slice, *, spec, tz, next_bar_start, last_day, last_time_close, last_bar_seq)` — Build ONLY new full bars starting at next_bar_start (already aligned),
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tz, daily_table, bars_table, state_table)`
- `main(argv)`

### `scripts/bars/refresh_price_bars_multi_tf_pre-partial-end.py`
**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url)`
- `parse_ids(values, db_url)`
- `load_daily_min_max(db_url, ids)`
- `load_daily_prices(ids, db_url)` — Load daily rows from cmc_price_histories7 (full history for ids).
- `load_daily_prices_for_id(*, db_url, id_, ts_start)` — Load daily rows for a single id, optionally from ts_start onward.
- `load_last_bar_info(db_url, bars_table, id_, tf)`
- `delete_bars_for_id_tf(db_url, bars_table, id_, tf)`
- `ensure_state_table(db_url, state_table)`
- `load_state(db_url, state_table, ids)`
- `upsert_state(db_url, state_table, rows)`
- `load_tf_list_from_dim_timeframe(*, db_url, include_non_canonical)` — Load the TF list for price_bars_multi_tf from public.dim_timeframe.
- `_make_day_time_open(ts)`
- `_enforce_bar_continuity(out)`
- `build_bars_for_id(df_id, tf_days, tf_label)` — Full build for a single id + tf_days. Drops partial trailing bars.
- `_build_incremental_new_bars_for_id(df_slice, *, tf_days, tf_label, last_bar_seq, last_time_close)` — Build only new COMPLETE tf_days bars after last_time_close, continuing bar_seq.
- `build_bars(daily, tf_list)` — Full build for all ids and all (tf_days, tf) in tf_list.
- `make_upsert_sql(bars_table)`
- `upsert_bars(df_bars, db_url, bars_table, batch_size)`
- `refresh_incremental(*, db_url, ids, tf_list, bars_table, state_table)`
- `main(argv)`

## `ta_lab2/scripts/bars/old`

### `scripts/bars/old/refresh_price_bars_multi_tf_hardcoded_tfs.py`
**Functions**
- `resolve_db_url(db_url)`
- `get_engine(db_url)`
- `load_all_ids(db_url)`
- `parse_ids(values, db_url)`
- `load_daily_prices(ids, db_url)` — Load daily rows from cmc_price_histories7.
- `_make_day_time_open(ts)` — Synthetic per-day open timestamp:
- `_enforce_bar_continuity(out)` — Enforce: for a single (id, tf) series ordered by bar_seq,
- `build_bars_for_id(df_id, tf_days, tf_label)` — Build tf_days-count bars for a single id.
- `build_bars(daily, tf_list)` — Build bars for all ids and all (tf_days, tf) in tf_list.
- `upsert_bars(df_bars, db_url, batch_size)`
- `main(argv)`

## `ta_lab2/scripts/emas`

### `scripts/emas/__init__.py`
_(no top-level classes or functions)_

### `scripts/emas/audit_ema_expected_coverage.py`
**Functions**
- `_log(msg)`
- `get_engine()`
- `parse_ids(engine, ids_arg, daily_table)`
- `load_periods(engine, periods_arg, lut_table)`
- `load_tfs(engine, family, dim_tf_table)` — Return TF list per family using NEW dim_timeframe semantics:
- `actual_combos(engine, ema_table, ids)`
- `main()`

### `scripts/emas/audit_ema_integrity.py`
**Classes**
- `TfSpec`

**Functions**
- `_log(msg)`
- `get_engine()`
- `parse_ids(engine, ids_arg, daily_table)`
- `load_periods(engine, periods_arg, lut_table)`
- `load_tfs(engine, family, dim_tf_table)` — Return TF list per family using current dim_timeframe semantics:
- `table_exists(engine, full_name)`
- `get_columns(engine, full_name)`
- `actual_combos(engine, ema_table, ids)`
- `run_coverage(engine, ids, periods, dim_tf, out_csv)`
- `audit_table(engine, table, ids)`
- `run_audit(engine, ids, out_csv)`
- `load_dim_timeframe_specs(engine, dim_tf)`
- `fetch_canonical_ts(engine, table, ids)`
- `spacing_eval_for_group(ts_series, spec)` — Returns:
- `run_spacing(engine, ids, dim_tf, out_csv)`
- `pick_sample_cols(colset)`
- `get_group_keys(engine, table, ids, max_groups_per_id)`
- `sample_group(engine, table, cols, id_, tf, period, per_group)`
- `run_samples(engine, ids, per_group, max_groups_per_id, out_csv)`
- `main()`

### `scripts/emas/audit_ema_samples.py`
- ⚠️ Parse error: `(unicode error) 'unicodeescape' codec can't decode bytes in position 335-336: truncated \UXXXXXXXX escape (audit_ema_samples.py, line 4)`

### `scripts/emas/audit_ema_tables.py`
**Functions**
- `_log(msg)`
- `get_engine()`
- `parse_ids(engine, ids_arg, daily_table)`
- `table_exists(engine, full_name)`
- `get_columns(engine, full_name)`
- `audit_table(engine, table, ids)`
- `main()`

### `scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py`
**Functions**
- `_in_ipython()`
- `_resolve_db_url()`
- `_load_ids(engine, schema, daily_table, ids_arg)`
- `_load_periods_from_lut(engine, *, schema, table)`
- `_get_table_columns(engine, schema, table)`
- `_pick_ts_column(cols)`
- `_require_output_schema(engine, schema, out_table)` — Returns (ts_col, roll_flag_col) after validating the output schema.
- `_ensure_state_table(engine, schema, table)` — Important: keep last_canonical_ts NULLABLE for compatibility with pre-existing tables
- `_load_state(engine, schema, table)`
- `_compute_dirty_start(state_df, *, selected_ids, default_start, verbose)` — CAL-style conservative dirty window:
- `_update_state_anchor(engine, schema, state_table, out_table)` — CAL_ANCHOR canonical closes are roll_bar = FALSE.
- `_parse_args(argv)`
- `main(argv)`

### `scripts/emas/refresh_ema_multi_tf_cal_from_bars.py`
**Functions**
- `_resolve_db_url(cli_db_url)`
- `_parse_ids(arg)`
- `_parse_int_list(arg)`
- `_load_all_ids(engine)`
- `_load_periods_from_lut(engine, schema, table)`
- `_ensure_state_table(engine, schema, table)`
- `_load_state(engine, schema, table)`
- `_update_state(engine, schema, table, out_table)` — After EMA write, update state table with latest canonical ts per (id, tf, period).
- `main()`

### `scripts/emas/refresh_ema_multi_tf_from_bars.py`
**Functions**
- `build_parser()`
- `_resolve_db_url(args_db_url)`
- `_resolve_ids(engine, ids_arg)`
- `_load_periods(engine, periods_arg)`
- `_load_tf_day_canonical(engine)`
- `main()`

### `scripts/emas/refresh_ema_multi_tf_v2.py`
**Functions**
- `_resolve_db_url(cli_db_url)` — Priority: --db-url, then TARGET_DB_URL env, then MARKETDATA_DB_URL env.
- `_parse_ids(ids_arg)`
- `_parse_int_list(arg)`
- `_load_periods_from_lut(engine)` — Load distinct EMA periods from public.ema_alpha_lookup.
- `build_parser()`
- `main()`

### `scripts/emas/run_all_ema_refreshes.py`
**Classes**
- `Step`

**Functions**
- `_require_env()`
- `_run_script(step)`
- `build_steps(args)`
- `parse_args()`
- `main()`

### `scripts/emas/sync_ema_multi_tf_u.py`
**Functions**
- `_log(msg)`
- `get_engine()`
- `split_schema_table(full_name)`
- `table_exists(engine, full_name)`
- `get_columns(engine, full_name)`
- `alignment_source_from_table(full_name)`
- `get_watermark(engine, alignment_source, prefer_ingested_at)` — Returns max watermark in _u for this alignment_source.
- `build_select_expr(cols, alignment_source, use_ingested_filter)` — Build (select_sql, where_sql) for INSERT ... SELECT.
- `insert_new_rows(engine, src_table, alignment_source, dry_run, use_ingested_filter)` — Inserts new rows from src_table into _u using watermark logic.
- `main()`

## `ta_lab2/scripts/emas/old`

### `scripts/emas/old/refresh_all_emas_view_only.py`
**Functions**
- `main()`

### `scripts/emas/old/refresh_cmc_ema_daily_only.py`
**Functions**
- `main(argv)`

### `scripts/emas/old/refresh_ema_multi_tf_cal_anchor_from_bars_old.py`
**Functions**
- `_in_ipython()`
- `_load_ids(eng, schema, daily_table, ids_arg)`
- `_parse_args(argv)`
- `main(argv)`

### `scripts/emas/old/refresh_ema_multi_tf_cal_anchor_only.py`
**Functions**
- `main(argv)`

### `scripts/emas/old/refresh_ema_multi_tf_cal_from_bars_old.py`
**Functions**
- `_resolve_db_url(cli_db_url)`
- `_parse_ids(arg)`
- `_parse_int_list(arg)`
- `_load_all_ids(engine)`
- `_ensure_state_table(engine, schema, table)`
- `_load_state(engine, schema, table)`
- `_update_state(engine, schema, table, out_table)` — After EMA write, update state table with latest canonical ts per (id, tf, period).
- `main()`

### `scripts/emas/old/refresh_ema_multi_tf_cal_only.py`
**Functions**
- `main(argv)` — Refresh ONLY ema_multi_tf_cal (calendar-aligned multi-TF EMAs).

### `scripts/emas/old/refresh_ema_multi_tf_cal_only_v2_old.py`
**Functions**
- `main(argv)`

### `scripts/emas/old/refresh_ema_multi_tf_only.py`
**Functions**
- `main(argv)`

### `scripts/emas/old/refresh_ema_multi_tf_v2_from_bars_old.py`
**Functions**
- `_resolve_db_url(cli_db_url)` — Priority: --db-url, then TARGET_DB_URL env.
- `_parse_ids(ids_arg)`
- `_parse_int_list(arg)`
- `build_parser()`
- `main()`

### `scripts/emas/old/refresh_ema_multi_tf_v2_only.py`
**Functions**
- `main(argv)`

### `scripts/emas/old/refresh_cmc_emas.py`
**Functions**
- `_get_engine(db_url)`
- `_ensure_refresh_state_table(engine)`
- `_load_all_ids(db_url)` — Load all asset ids from the database when the user passes --ids all.
- `_parse_ids(raw_ids)` — Parse the --ids argument.
- `_get_load_ts_bounds_for_id(conn, asset_id, *, start, end)` — Helper that returns (min_timeclose, max_timeclose) for cmc_price_histories7
- `_get_dirty_window_for_id(conn, asset_id, *, last_load_ts)` — Given an asset id and a last_load_ts watermark, return the earliest
- `_upsert_refresh_state(conn, asset_id, *, last_load_ts_daily, last_load_ts_multi, last_load_ts_cal)` — Upsert the refresh state for a given id. Only non-None fields are updated
- `_get_daily_bounds_for_id(conn, asset_id)` — Return (min_daily_ts, max_daily_ts) for this id from cmc_ema_daily.
- `_get_multi_tf_max_ts_for_id(conn, asset_id)` — Return the maximum ts in ema_multi_tf for this id (or None if empty).
- `_get_cal_multi_tf_max_ts_for_id(conn, asset_id)` — Return the maximum ts in ema_multi_tf_cal for this id (or None if empty).
- `_get_cal_anchor_multi_tf_max_ts_for_id(conn, asset_id)` — Return the maximum ts in ema_multi_tf_cal_anchor for this id
- `refresh(ids, start, end, *, db_url, update_daily, update_multi_tf, update_cal_multi_tf, update_cal_multi_tf_anchor, update_multi_tf_v2, refresh_all_emas_view, refresh_price_emas_view, refresh_price_emas_d1d2_view)` — Perform the EMA refresh workflow for the given asset ids.
- `_parse_args(argv)`

### `scripts/emas/old/refresh_cmc_emas_asOf_EOD_20251207.py`
**Functions**
- `_get_engine(db_url)`
- `_ensure_refresh_state_table(engine)`
- `_load_all_ids(db_url)` — Load all asset ids from the database when the user passes --ids all.
- `_parse_ids(raw_ids)` — Parse the --ids argument.
- `_get_load_ts_bounds_for_id(conn, asset_id, *, start, end)` — Helper that returns (min_timeclose, max_timeclose) for cmc_price_histories7
- `_get_dirty_window_for_id(conn, asset_id, *, last_load_ts)` — Given an asset id and a last_load_ts watermark, return the earliest
- `_upsert_refresh_state(conn, asset_id, *, last_load_ts_daily, last_load_ts_multi, last_load_ts_cal)` — Upsert the refresh state for a given id. Only non-None fields are updated
- `_get_daily_bounds_for_id(conn, asset_id)` — Return (min_daily_ts, max_daily_ts) for this id from cmc_ema_daily.
- `_get_multi_tf_max_ts_for_id(conn, asset_id)` — Return the maximum ts in ema_multi_tf for this id (or None if empty).
- `_get_cal_multi_tf_max_ts_for_id(conn, asset_id)` — Return the maximum ts in ema_multi_tf_cal for this id (or None if empty).
- `refresh(ids, start, end, *, db_url, update_daily, update_multi_tf, update_cal_multi_tf, update_multi_tf_v2, refresh_all_emas_view, refresh_price_emas_view, refresh_price_emas_d1d2_view)` — Perform the EMA refresh workflow for the given asset ids.
- `_parse_args(argv)`

### `scripts/emas/old/refresh_cmc_emas_old.py`
**Functions**
- `_get_engine(db_url)`
- `_load_all_ids(db_url)` — Load all asset ids from the database when the user passes --ids all.
- `_parse_ids(raw_ids)`
- `refresh(ids, start, end, *, db_url, update_daily, update_multi_tf, refresh_all_emas_view, refresh_price_emas_view, refresh_price_emas_d1d2_view)` — Perform the requested updates.
- `main(argv)`

### `scripts/emas/old/refresh_cmc_emas_old1.py`
**Functions**
- `_get_engine(db_url)`
- `_load_all_ids(db_url)` — Load all asset ids from the database when the user passes --ids all.
- `_parse_ids(raw_ids)`
- `refresh(ids, start, end, *, db_url, update_daily, update_multi_tf, refresh_all_emas_view, refresh_price_emas_view, refresh_price_emas_d1d2_view)` — Perform the requested updates.
- `main(argv)`

### `scripts/emas/old/refresh_cmc_emas_old2.py`
**Functions**
- `_get_engine(db_url)`
- `_ensure_refresh_state_table(engine)`
- `_load_all_ids(db_url)` — Load all asset ids from the database when the user passes --ids all.
- `_parse_ids(raw_ids)` — Parse the --ids argument.
- `_get_refresh_state_for_id(conn, asset_id)` — Return (last_load_ts_daily, last_load_ts_multi, last_load_ts_cal) for this id.
- `_get_changed_window(conn, asset_id, prev_load_ts)` — For a given id and previous load_ts watermark, find the earliest timeclose
- `_upsert_refresh_state(conn, asset_id, *, last_load_ts_daily, last_load_ts_multi, last_load_ts_cal)` — Upsert the refresh state for a given id. Only non-None fields are updated
- `_get_daily_bounds_for_id(conn, asset_id)` — Return (min_daily_ts, max_daily_ts) for this id from cmc_ema_daily.
- `_get_max_ema_ts_for_id(conn, table_name, asset_id)` — Return MAX(ts) from a given EMA table (ema_multi_tf or ema_multi_tf_cal)
- `_get_max_load_ts_for_id(conn, asset_id)` — Return MAX(load_ts) from cmc_price_histories7 for this id.
- `refresh(ids, start, end, *, db_url, update_daily, update_multi_tf, update_cal_multi_tf, refresh_all_emas_view, refresh_price_emas_view, refresh_price_emas_d1d2_view)` — Perform the requested updates.
- `main(argv)`

### `scripts/emas/old/refresh_price_with_emas_d1d2_view_only.py`
**Functions**
- `main()`

### `scripts/emas/old/refresh_price_with_emas_view_only.py`
**Functions**
- `main()`

### `scripts/emas/old/refresh_ema_multi_tf_stats_old.py`
**Functions**
- `get_engine(db_url)` — Return a SQLAlchemy engine.
- `run_all_tests(engine)` — Run all ema_multi_tf tests in a single transaction.
- `main(db_url)` — Main entrypoint for both CLI and programmatic use.

### `scripts/emas/old/run_ema_refresh_examples.py`
**Functions**
- `get_engine(db_url)` — Create an SQLAlchemy engine using TARGET_DB_URL by default.
- `get_all_ids(db_url)` — Return all distinct ids from cmc_price_histories7, sorted ascending.
- `_get_table_snapshot(table_name, ids, db_url)` — For a given table and list of ids, return a simple snapshot:
- `_summarize_table_changes(table_name, ids, before, after)` — Print a human-readable summary of what changed between two snapshots.
- `_snapshot_all_targets(ids, db_url)` — Take snapshots for all EMA targets we care about.
- `_summarize_all_targets(ids, before, after)` — Print summaries for all EMA targets based on BEFORE/AFTER snapshots.
- `_build_cli_args(ids, db_url)` — Build the CLI argument list to invoke refresh_cmc_emas as a module.
- `_refresh_insert_only_all_targets(ids, db_url)` — Call refresh_cmc_emas via CLI for the given ids and then print
- `example_incremental_all_ids_all_targets(db_url)` — Incremental insert-only (from the caller's perspective) for ALL ids

## `ta_lab2/scripts/emas/stats`

### `scripts/emas/stats/__init__.py`
_(no top-level classes or functions)_

## `ta_lab2/scripts/emas/stats/daily`

### `scripts/emas/stats/daily/__init__.py`
_(no top-level classes or functions)_

### `scripts/emas/stats/daily/refresh_ema_daily_stats.py`
**Functions**
- `get_engine(db_url)` — Create a SQLAlchemy engine using either the provided URL or TARGET_DB_URL.
- `run_all_tests(engine)` — Run all cmc_ema_daily tests in a single transaction.
- `main(db_url)` — Main entrypoint for both CLI and programmatic use.

### `scripts/emas/stats/daily/run_refresh_ema_daily_stats.py`
_(no top-level classes or functions)_

## `ta_lab2/scripts/emas/stats/multi_tf`

### `scripts/emas/stats/multi_tf/__init__.py`
_(no top-level classes or functions)_

### `scripts/emas/stats/multi_tf/refresh_ema_multi_tf_stats.py`
**Functions**
- `_setup_logging(level)`
- `get_engine(db_url)`
- `run(engine, full_refresh, log_level)`
- `main()`

## `ta_lab2/scripts/emas/stats/multi_tf/old`

### `scripts/emas/stats/multi_tf/old/refresh_ema_multi_tf_stats_old.py`
**Functions**
- `get_engine(db_url)` — Return a SQLAlchemy engine.
- `run_all_tests(engine)` — Run all ema_multi_tf tests in a single transaction.
- `main(db_url)` — Main entrypoint for both CLI and programmatic use.

### `scripts/emas/stats/multi_tf/old/run_refresh_ema_multi_tf_stats_old.py`
_(no top-level classes or functions)_

## `ta_lab2/scripts/emas/stats/multi_tf_cal`

### `scripts/emas/stats/multi_tf_cal/__init__.py`
_(no top-level classes or functions)_

### `scripts/emas/stats/multi_tf_cal/refresh_ema_multi_tf_cal_stats.py`
**Functions**
- `_setup_logging(level)`
- `get_engine(db_url)`
- `infer_expected_scheme(table)`
- `run(engine, tables, full_refresh, log_level)`
- `main(db_url, tables)`

## `ta_lab2/scripts/emas/stats/multi_tf_cal/old`

### `scripts/emas/stats/multi_tf_cal/old/refresh_ema_multi_tf_cal_stats_old.py`
**Functions**
- `get_engine(db_url)` — Return a SQLAlchemy engine.
- `run_all_tests(engine)` — Run all ema_multi_tf_cal tests in a single transaction.
- `main(db_url)` — Main entrypoint for both CLI and programmatic use.

### `scripts/emas/stats/multi_tf_cal/old/run_refresh_ema_multi_tf_cal_stats_old.py`
_(no top-level classes or functions)_

## `ta_lab2/scripts/emas/stats/multi_tf_cal_anchor`

### `scripts/emas/stats/multi_tf_cal_anchor/refresh_ema_multi_tf_cal_anchor_stats.py`
**Functions**
- `_setup_logging(level)`
- `get_engine(db_url)`
- `infer_expected_scheme(table)`
- `run(engine, tables, full_refresh, log_level)`
- `main(db_url, tables)`

## `ta_lab2/scripts/emas/stats/multi_tf_cal_anchor/old`

### `scripts/emas/stats/multi_tf_cal_anchor/old/refresh_ema_multi_tf_cal_anchor_stats_old.py`
**Functions**
- `_mask_url(url)` — Light masking for printing DB URLs.
- `_get_engine(db_url)` — Resolve DB URL and return a SQLAlchemy engine.
- `_ensure_stats_table(engine)` — Create the stats table/index if they don't exist yet.
- `_insert_daily_row_span(conn, ids)` — For each (id, tf, period) in the source table, compute:
- `_insert_roll_false_spacing(conn, ids)` — Check that roll = FALSE rows are spaced roughly tf_days apart
- `_insert_roll_false_count_vs_span(conn, ids)` — Check consistency between:
- `_insert_non_null_ema(conn, ids)` — Check that ema is non-null for each (id, tf, period).
- `_insert_non_decreasing_ts(conn, ids)` — Check that ts is non-decreasing within each (id, tf, period).
- `_insert_roll_boolean(conn, ids)` — Sanity check for the roll column: counts true/false/null per group.
- `refresh(ids, db_url)` — Refresh stats for the given asset ids from ema_multi_tf_cal_anchor.
- `_normalize_ids_arg(engine, ids_arg)` — Support:
- `main(argv)`

### `scripts/emas/stats/multi_tf_cal_anchor/old/run_refresh_ema_multi_tf_cal_anchor_stats_old.py`
**Functions**
- `main(argv)` — Entry point that just forwards args to the real stats script.

## `ta_lab2/scripts/emas/stats/multi_tf_v2`

### `scripts/emas/stats/multi_tf_v2/__init__.py`
_(no top-level classes or functions)_

### `scripts/emas/stats/multi_tf_v2/refresh_ema_multi_tf_v2_stats.py`
**Functions**
- `_setup_logging(level)`
- `get_engine(db_url)`
- `run(engine, full_refresh, log_level)`
- `main()`

## `ta_lab2/scripts/emas/stats/multi_tf_v2/old`

### `scripts/emas/stats/multi_tf_v2/old/refresh_ema_multi_tf_v2_stats_old.py`
**Functions**
- `_resolve_db_url(cli_db_url)` — Resolve DB URL from CLI arg or environment, mirroring other scripts.
- `_get_engine(cli_db_url)`
- `_load_all_ids(engine)` — Load all distinct asset ids from ema_multi_tf_v2.
- `_normalize_ids_arg(engine, ids_arg)` — Handle:
- `_delete_existing_for_ids(conn, ids)`
- `_insert_daily_row_span(conn, ids)` — For each (id, tf, period):
- `_insert_roll_false_spacing(conn, ids)` — For each (id, tf, period):
- `refresh(ids, db_url)` — Compute and upsert stats for the given ids.
- `_build_arg_parser()`
- `main(argv)`

### `scripts/emas/stats/multi_tf_v2/old/run_refresh_ema_multi_tf_v2_stats_old.py`
**Functions**
- `main(argv)` — Thin wrapper so you can run the v2 stats refresh easily from Spyder,

## `ta_lab2/scripts/etl`

### `scripts/etl/backfill_ema_diffs.py`
**Functions**
- `_resolve_group_cols(df, table_name)` — Figure out which grouping columns to use for this table.
- `_resolve_time_col(df, preferred, table_name)` — Pick an actual time column to use for sorting / joins.
- `backfill_table(engine, table_name, preferred_time_col)`
- `main()`

### `scripts/etl/update_cmc_history.py`
_(no top-level classes or functions)_

## `ta_lab2/scripts/pipeline`

### `scripts/pipeline/run_go_forward_daily_refresh.py`
**Classes**
- `Step`

**Functions**
- `_log(msg)`
- `_require_env()`
- `get_engine()`
- `ensure_state_table(engine)`
- `get_last_state(engine)`
- `set_last_state(engine, ts)`
- `get_daily_max_ts(engine)`
- `run_step(step)`
- `build_steps(repo_root, ids, periods)` — We pass only lightweight args:
- `main()`

## `ta_lab2/scripts/prices`

### `scripts/prices/__init__.py`
_(no top-level classes or functions)_

### `scripts/prices/refresh_price_histories7_stats.py`
**Functions**
- `get_engine(db_url)` — Return a SQLAlchemy engine.
- `run_all_tests(engine)` — Run all cmc_price_histories7 tests in a single transaction.
- `main(db_url)` — Main entrypoint for both CLI and programmatic use.

### `scripts/prices/run_refresh_price_histories7_stats.py`
**Functions**
- `main()` — Wrapper around refresh_price_histories7_stats.main() for Spyder.

## `ta_lab2/scripts/research`

## `ta_lab2/scripts/research/notebooks`

## `ta_lab2/scripts/research/queries`

### `scripts/research/queries/opt_cf_ema.py`
**Functions**
- `_norm_cols(df)`
- `load_df(p)`
- `ensure_ema(df, span)`
- `build_grid(fasts, slows, delta)`
- `main()`

### `scripts/research/queries/opt_cf_ema_refine.py`
**Functions**
- `_norm_cols(df)`
- `load_df(p)`
- `ensure_ema(df, span)`
- `refine_ranges(tops, f_pad, s_pad, f_min, f_max, s_min, s_max)`
- `build_grid(fasts, slows, delta)`
- `main()`

### `scripts/research/queries/opt_cf_ema_sensitivity.py`
**Functions**
- `_norm_cols(df)`
- `load_df(p)`
- `ensure_ema(df, span)`
- `build_grid(f, s, f_pad, s_pad, delta)`
- `main()`

### `scripts/research/queries/opt_cf_generic.py`
**Functions**
- `_norm_cols(df)`
- `load_df(path)`
- `main()`

### `scripts/research/queries/run_ema_50_100.py`
**Functions**
- `_normalize_cols(df)`
- `_find_ts_col(cols)`
- `_find_close_col(cols)`
- `load_price_df(csv_path)`
- `ensure_ema(df, span, out_col)`
- `main()`

### `scripts/research/queries/wf_validate_ema.py`
**Functions**
- `_norm_cols(df)`
- `load_df(path)`
- `ensure_ema(df, span)`
- `rolling_train_test_splits(start, end, train_days, test_days, step_days)` — Yield (TRAIN_i, TEST_i) Split pairs from [start, end].
- `main()`

## `ta_lab2/scripts/returns`

### `scripts/returns/audit_returns_bars_multi_tf_cal_anchor_iso_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `main()`

### `scripts/returns/audit_returns_bars_multi_tf_cal_anchor_us_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `main()`

### `scripts/returns/audit_returns_bars_multi_tf_cal_iso_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `main()`

### `scripts/returns/audit_returns_bars_multi_tf_cal_us_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `main()`

### `scripts/returns/audit_returns_bars_multi_tf_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `main()`

### `scripts/returns/audit_returns_d1_integrity.py`
**Classes**
- `AuditConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `main()`

### `scripts/returns/audit_returns_ema_multi_tf_cal_anchor_integrity.py`
**Classes**
- `SchemeSpec`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql, params)`
- `_write_csv(df, path)`
- `_today_yyyymmdd()`
- `_resolve_out_base(prefix)`
- `_schemes(scheme)`
- `_fail_or_warn(strict, msg)`
- `_audit_one(engine, spec, dim_tf, gap_mult, strict, out_dir, out_base)`
- `main()`

### `scripts/returns/audit_returns_ema_multi_tf_cal_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `_today_yyyymmdd()`
- `_resolve_out_name(out_arg, default_prefix)`
- `_fail_or_warn(strict, msg)`
- `expand_scheme(s)`
- `expand_series(s)`
- `_audit_one(engine, ema_table, ret_table, dim_tf, out_base, strict, gap_mult, label, series)`
- `main()`

### `scripts/returns/audit_returns_ema_multi_tf_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `_today_yyyymmdd()`
- `_resolve_out_name(out_arg, default_prefix)`
- `_fail_or_warn(strict, msg)`
- `main()`

### `scripts/returns/audit_returns_ema_multi_tf_u_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `_today_yyyymmdd()`
- `_resolve_out_name(out_arg, default_prefix)`
- `_fail_or_warn(strict, msg)`
- `main()`

### `scripts/returns/audit_returns_ema_multi_tf_v2_integrity.py`
**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_df(engine, sql)`
- `_write_csv(df, path)`
- `_today_yyyymmdd()`
- `_resolve_out_name(out_arg, default_prefix)` — If --out is empty, auto-generate a dated base name:
- `_fail_or_warn(strict, msg)`
- `main()`

### `scripts/returns/refresh_returns_bars_multi_tf.py`
**Classes**
- `RunnerConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_load_all_ids(engine, bars_table)`
- `_load_all_tfs(engine, bars_table)`
- `_load_pairs(engine, bars_table, ids, tfs)`
- `_ensure_state_rows(engine, state_table, pairs)`
- `_full_refresh(engine, out_table, state_table, pairs)`
- `_run_one_pair(engine, cfg, one_id, one_tf)`
- `main()`

### `scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_iso.py`
**Classes**
- `Key`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `ensure_tables(engine, out_table, state_table)`
- `drop_tables(engine, out_table, state_table)`
- `load_keys(engine, bars_table)`
- `get_last_time_close(engine, state_table, key)`
- `upsert_state(engine, state_table, key, last_time_close)`
- `process_key(engine, bars_table, out_table, state_table, key, start)`
- `main()`

### `scripts/returns/refresh_returns_bars_multi_tf_cal_anchor_us.py`
**Classes**
- `Key`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `ensure_tables(engine, out_table, state_table)`
- `drop_tables(engine, out_table, state_table)`
- `load_keys(engine, bars_table)`
- `get_last_time_close(engine, state_table, key)`
- `upsert_state(engine, state_table, key, last_time_close)`
- `process_key(engine, bars_table, out_table, state_table, key, start)`
- `main()`

### `scripts/returns/refresh_returns_bars_multi_tf_cal_iso.py`
**Classes**
- `Key`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `ensure_tables(engine, out_table, state_table)`
- `drop_tables(engine, out_table, state_table)`
- `load_keys(engine, bars_table)`
- `get_last_time_close(engine, state_table, key)`
- `upsert_state(engine, state_table, key, last_time_close)`
- `process_key(engine, bars_table, out_table, state_table, key, start)`
- `main()`

### `scripts/returns/refresh_returns_bars_multi_tf_cal_us.py`
- ⚠️ Parse error: `(unicode error) 'unicodeescape' codec can't decode bytes in position 875-876: truncated \UXXXXXXXX escape (refresh_returns_bars_multi_tf_cal_us.py, line 3)`

### `scripts/returns/refresh_cmc_returns_d1.py`
**Classes**
- `RunnerConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_load_all_ids(engine, daily_table)`
- `_ensure_state_rows(engine, state_table, ids)` — Ensure every id has a row in the state table, without overwriting last_time_close.
- `_full_refresh(engine, out_table, state_table, ids)`
- `_run_one_id(engine, cfg, one_id)` — Inserts new return rows for one id and advances the watermark.
- `main()`

### `scripts/returns/refresh_returns_ema_multi_tf.py`
**Classes**
- `RunnerConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `expand_roll_mode(mode)` — Expand roll-mode to concrete roll booleans.
- `_ensure_tables(engine, out_table, state_table)`
- `_parse_ids(ids_arg)`
- `_load_keys(engine, ema_table, ids, roll_mode)`
- `_ensure_state_rows(engine, state_table, keys)`
- `_full_refresh(engine, out_table, state_table, keys)`
- `_run_one_key(engine, cfg, key)`
- `main()`

### `scripts/returns/refresh_returns_ema_multi_tf_cal.py`
**Classes**
- `RunnerConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_parse_ids(ids_arg)`
- `expand_scheme(s)`
- `expand_series(s)`
- `expand_roll_mode(mode)`
- `_load_keys(engine, ema_table, ids, series, roll_mode)` — Returns keys as: (id, tf, period, series, roll)
- `_ensure_state_rows(engine, state_table, keys)`
- `_full_refresh(engine, ret_table, state_table, keys)`
- `_run_one_key(engine, ema_table, ret_table, state_table, start, key)`
- `main()`

### `scripts/returns/refresh_returns_ema_multi_tf_cal_anchor.py`
**Classes**
- `RunnerConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_parse_ids(ids_arg)`
- `expand_roll_mode(mode)`
- `expand_series_mode(mode)`
- `expand_scheme(scheme)`
- `_tables_for_scheme(scheme)`
- `_load_keys_for_one_table(engine, ema_table, ids, series_list, roll_mode)` — Resolve (id, tf, period, series, roll) keys from EMA source table.
- `_ensure_state_rows(engine, state_table, keys)` — Bulletproof / fast: INSERT ... SELECT FROM UNNEST ... ON CONFLICT DO NOTHING
- `_full_refresh(engine, ret_table, state_table, keys)`
- `_run_one_key(engine, ema_table, ret_table, state_table, start, key)` — Build returns for one (id, tf, period, series, roll).
- `main()`

### `scripts/returns/refresh_returns_ema_multi_tf_u.py`
**Classes**
- `RunnerConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `_parse_ids_arg(ids_arg)`
- `_expand_series(series)`
- `_expand_roll_mode(roll_mode)`
- `_load_keys(engine, ema_u_table, ids, series_list, rolls)` — Returns distinct key surface from EMA_U, properly mapping roll per series.
- `_ensure_state_rows(engine, state_table, keys)`
- `_run_one_key(engine, ema_u_table, out_table, state_table, start, key)`
- `main()`

### `scripts/returns/refresh_returns_ema_multi_tf_v2.py`
**Classes**
- `RunnerConfig`

**Functions**
- `_print(msg)`
- `_get_engine(db_url)`
- `expand_roll_mode(mode)` — Expand roll-mode to concrete roll booleans.
- `_ensure_tables(engine, out_table, state_table)`
- `_parse_ids(ids_arg)`
- `_load_keys(engine, ema_table, ids, roll_mode)`
- `_ensure_state_rows(engine, state_table, keys)` — Create state rows for all keys (idempotent). We still do this row-by-row because it's small
- `_read_state_for_keys(engine, state_table, ids)` — Correct pattern to read state. (You may not need this for the per-key CTE approach,
- `_full_refresh(engine, out_table, state_table, keys)`
- `_run_one_key(engine, cfg, key)` — Correct incremental watermark logic (EMA-specific):
- `_upsert_state_bulk_unnest(engine, state_table, rows)` — Option 2 (bulletproof): INSERT ... SELECT FROM UNNEST to upsert state in bulk.
- `main()`

## `ta_lab2/scripts/sandbox`

## `ta_lab2/signals`

### `signals/__init__.py`
**Functions**
- `attach_signals_from_config(df, strategy, **params)` — Back-compat helper.

### `signals/breakout_atr.py`
**Functions**
- `_rolling_high(s, n)`
- `_rolling_low(s, n)`
- `make_signals(df, lookback, atr_col, price_cols, confirm_close, exit_on_channel_crossback, use_trailing_atr_stop, trail_atr_mult, risk_pct, size_smoothing_ema, max_leverage)` — Breakout strategy:

### `signals/ema_trend.py`
**Functions**
- `make_signals(df, *, fast_ema, slow_ema, rsi_col, atr_col, use_rsi_filter, use_vol_filter, rsi_min_long, rsi_max_short, min_atr_pct, allow_shorts, cooldown_bars)` — EMA crossover adapter.

### `signals/generator.py`
**Functions**
- `generate_signals(df, *, close_col, fast_ema, slow_ema, rsi_col, atr_col, use_rsi_filter, use_vol_filter, rsi_min_long, rsi_max_short, min_atr_pct, allow_shorts, cooldown_bars)` — Compose primitive rules into a full signal dataframe.

### `signals/position_sizing.py`
**Functions**
- `clamp_size(size, max_abs)` — Clamp position size to +/- max_abs (e.g., leverage cap).
- `ema_smooth(series, span)` — Smooth a sizing series to reduce churn.
- `volatility_size_pct(price, atr, risk_pct, atr_mult, equity)` — Position sizing based on risk parity vs ATR:
- `target_dollar_position(equity, size_fraction)` — Convert a size fraction (relative to equity) to notional dollars.
- `fixed_fractional(price, fraction)` — Simple constant fraction sizing (e.g., 50% of equity).
- `inverse_volatility(vol, target, min_size, max_size, eps)` — Size inversely to a volatility proxy (e.g., ATR% or rolling stdev).

### `signals/registry.py`
**Functions**
- `get_strategy(name)` — Safe getter used by research scripts; keeps existing orchestrator behavior intact.
- `_ensure_close(df)`
- `_ensure_ema(df, span)`
- `_ensure_rsi(df, n)` — Minimal Wilder-style RSI (EMA smoothing) on 'close'.
- `_ensure_macd(df, fast, slow, signal)`
- `_ensure_atr(df, n)` — Minimal ATR (Wilder). Requires high/low/close. If missing, silently skip.
- `ensure_for(name, df, params)` — Compute required columns for a given strategy+params, if missing.
- `grid_for(name)` — Small default grids to kick off coarse scans.

### `signals/rsi_mean_revert.py`
**Functions**
- `make_signals(df, rsi_col, lower, upper, confirm_cross, allow_shorts, atr_col, risk_pct, atr_mult_stop, price_col, max_leverage)` — RSI mean-revert:

### `signals/rules.py`
**Functions**
- `ema_crossover_long(df, fast, slow)` — True when fast EMA crosses ABOVE slow EMA.
- `ema_crossover_short(df, fast, slow)` — True when fast EMA crosses BELOW slow EMA.
- `rsi_ok_long(df, rsi_col, min_long)` — Allow long entries only when RSI >= min_long.
- `rsi_ok_short(df, rsi_col, max_short)` — Allow short entries only when RSI <= max_short.
- `volatility_filter(df, atr_col, close_col, min_atr_pct)` — Require ATR/close >= threshold to avoid low-volatility conditions.

## `ta_lab2/time`

### `time/__init__.py`
_(no top-level classes or functions)_

### `time/dim_sessions.py`
**Classes**
- `SessionKey`
- `SessionMeta`
- `DimSessions`

**Functions**
- `_resolve_db_url(db_url)`

### `time/dim_timeframe.py`
**Classes**
- `TFMeta`
- `DimTimeframe` — In-memory view of dim_timeframe with some convenience accessors.

**Functions**
- `_get_dim(db_url)` — Lazy-load and cache DimTimeframe for this process using db_url.
- `get_tf_days(tf, db_url)` — Convenience wrapper to get tf_days_nominal for a timeframe.
- `get_alignment_type(tf, db_url)` — Convenience wrapper to get alignment_type for a timeframe.
- `list_tfs(db_url, alignment_type, canonical_only)` — Convenience wrapper to list timeframes in dim_timeframe, with filters.
- `get_tf_days_bounds(tf, db_url)` — Convenience wrapper to get (tf_days_min, tf_days_max) for a timeframe.
- `get_tf_days_bounds_or_nominal(tf, db_url)` — Convenience wrapper to get (min_days, max_days), falling back to nominal.
- `allows_partial(tf, db_url)` — Convenience wrapper to get (allow_partial_start, allow_partial_end).
- `get_calendar_scheme(tf, db_url)` — Convenience wrapper to get calendar_scheme.
- `realized_tf_days_ok(tf, tf_days, db_url)` — Convenience wrapper to check realized tf_days is within bounds for tf.

### `time/qa.py`
**Classes**
- `QAReason`
- `QAViolation`
- `QARunResult`

**Functions**
- `_make_engine(db_url)`
- `_count_by_reason(violations)`
- `_tf_days_bounds_violations(*, table_name, store, rows)`
- `_partial_policy_violations(*, table_name, store, rows_first_last)` — Enforce dim_timeframe allow_partial_start / allow_partial_end.
- `run_bars_qa(*, store, table_name, ids, tfs, start_ts, end_ts, engine, db_url, open_col, high_col, low_col, close_col, bar_seq_col, check_continuity, check_ohlc, check_bar_seq, check_tf_days_bounds, check_partial_policy)` — Unified QA runner for ANY bars table, with dim_timeframe-driven semantics.
- `summarize_qa(result, *, max_examples_per_reason)` — Produce a readable summary string for logs / CLI.

### `time/specs.py`
**Classes**
- `CalendarScheme` — Calendar convention for alignment/anchoring logic.
- `TimeframeFamily` — High-level timeframe semantics family.
- `PartialPolicy` — Table-level partial-bar policy.
- `TimeframeSpec` — Single-source-of-truth semantic spec for a timeframe row in dim_timeframe.
- `TableSpec` — Semantic spec for a specific bars table. This is what prevents drift.
- `TimeSpecStore` — In-memory store of TimeframeSpec + TableSpec.

**Functions**
- `default_bars_table_registry()` — Central, explicit registry. Keep this in sync with your design decision:
- `_make_engine(db_url)`
- `load_time_specs(*, engine, db_url)` — Load TimeframeSpec rows from public.dim_timeframe and return a TimeSpecStore.
- `require_specs_for_tfs(store, tfs)` — Hard-stop guard: ensure every tf exists in dim_timeframe.
- `assert_table_tf_invariants(store, table_name, tfs)` — Hard-stop guard: ensure tf list is valid for a given table spec.

## `ta_lab2/tools`

### `tools/__init__.py`
_(no top-level classes or functions)_

### `tools/dbtool.py`
**Classes**
- `DbConfig`

**Functions**
- `_normalize_db_url(url)` — Accept SQLAlchemy-style URLs and convert to psycopg/psycopg2-compatible URLs.
- `_find_repo_root(start)`
- `_load_env_file_if_present(repo_root)` — Loads db_config.env from repo root *only if* TARGET_DB_URL / MARKETDATA_DB_URL
- `_resolve_db_url()`
- `_normalize_sql(sql)`
- `_enforce_read_only(sql)`
- `_ensure_limit(sql, limit)` — Adds LIMIT if query appears to be SELECT/WITH and has no LIMIT.
- `_redact_url(url)`
- `_quote_ident(name)`
- `_validate_simple_ident(name, what)`
- `_validate_sql_fragment(fragment, what)` — Guardrails for user-supplied clause fragments (WHERE/GROUP/HAVING/ORDER/select list).
- `_connect_v3(cfg)`
- `_connect_v2(cfg)`
- `_apply_safety_session_settings(cur, cfg)`
- `_execute_sql(cfg, sql, params)`
- `schema_overview_sql()`
- `_render_snapshot_check_text(out)`
- `table_stats_sql()` — Fast table-level "shape" stats (no full scans):
- `col_stats_sql()` — Snapshot-only column ranking.
- `list_tables_sql(schema)`
- `describe_table_sql(schema, table)`
- `indexes_detail_sql(schema, table)`
- `constraints_sql(schema, table)`
- `keys_sql(schema, table)`
- `profile_table_queries(schema, table)`
- `explain_sql(sql)`
- `column_profile_sql(schema, table)` — Full column profile for interactive inspection (profile-cols command).
- `time_profile_sql(schema, table, ts_col, bucket, max_buckets)` — Returns:
- `dupes_sql(schema, table, key_cols, limit)`
- `agg_sql(schema, table, select_list, where, group_by, having, order_by, limit)` — Safe-ish single-table aggregation builder. You provide the select list and optional clauses.
- `_safe_int(value, default)`
- `_parse_snapshot_ts(value)`
- `_human_bytes(n)`
- `_snapshot_check_summary(snap, source, stale_days, min_rows, top_n, meta)`
- `_rows_to_dicts(out)` — Normalize _execute_sql output rows to list[dict] for both psycopg v3 (tuples)
- `_snapshot_db(cfg, repo_root)` — Build a schema snapshot across all non-system schemas.
- `_md_escape(s)`
- `_render_snapshot_md(snap)` — Render db_schema_snapshot.json into a compact, grep-friendly Markdown doc.
- `cmd_snapshot_diff(args)`
- `main(argv)`

### `tools/snapshot_diff.py`
**Classes**
- `NormTable`
- `NormSnapshot`

**Functions**
- `_human_bytes(n)`
- `_norm_rows(x)` — Normalize approx row counts.
- `_table_key(schema, table)`
- `load_snapshot(path)`
- `diff_snapshots(a, b, *, top_n)`
- `render_diff_md(diff, *, title)`

## `ta_lab2/utils`

### `utils/cache.py`
**Functions**
- `_ensure_joblib_available()` — Raise a clear error if joblib is not installed.
- `_key(name, params)`
- `disk_cache(name, compute_fn, **params)` — Simple disk-backed cache using joblib.

## `ta_lab2/viz`

### `viz/all_plots.py`
**Functions**
- `_pick_time_index(d)`
- `plot_ema_with_trend(df, price_col, ema_cols, trend_col, *, include_slopes, include_flips, n)`
- `plot_consolidated_emas_like(df, base_col, periods, *, include_slopes, include_flips, n)`
- `plot_realized_vol(df, *, windows, include_logret_stdev, n)`
