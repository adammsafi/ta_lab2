# ta_lab2 – File & Symbol Map
_Generated: 2025-11-13T15:36:47_

### `__init__.py`
**Functions**
- `add_rolling_vol_from_returns_batch(df, *, price_col, modes, windows, annualize, direction)` — Fallback shim: delegates to the project implementation if present,

### `cli.py`
**Functions**
- `_read_df(path)` — Minimal CSV reader for regime-inspect.
- `_default_policy_yaml()` — Default overlay location matches your repo layout:
- `cmd_pipeline(args)` — Original behavior: load YAML config and run the BTC pipeline.
- `_ensure_feats_if_possible(df, tf)`
- `cmd_regime_inspect(args)` — Print multi-TF regime labels and the resolved policy.
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
- `write_parquet(df, path, partition_cols)`
- `read_parquet(path)`

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
- `save_table(df, out_path)`
- `equity_plot(equity, title, out_path)`
- `leaderboard(results, group_cols)` — Rank parameter sets inside each split by MAR, then Sharpe, then CAGR.

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
- `sweep_grid(df, signal_func, param_grid, splits, cost, price_col, freq_per_year)` — Run many parameter sets across many splits; return a tidy table.

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
- `compute_ema(s, window, *, adjust, min_periods, name, **kwargs)` — Series EMA with a Pandas-backed implementation.
- `_flip_for_direction(obj, direction)` — If data are newest-first, flip to chronological for diff/EMA, and tell caller
- `_maybe_round(s, round_places)`
- `_ensure_list(x)`
- `add_ema_columns(df, base_price_cols, ema_windows, *, direction, overwrite, round_places, adjust, min_periods, price_cols, ema_periods, **kwargs)` — For each `col` in base_price_cols and each `w` in ema_windows, add:
- `add_ema_d1(df, base_price_cols, ema_windows, *, direction, overwrite, round_places, price_cols, ema_periods, **kwargs)` — First difference of EMA:
- `add_ema_d2(df, base_price_cols, ema_windows, *, direction, overwrite, round_places, price_cols, ema_periods, **kwargs)` — Second difference of EMA:
- `add_ema(df, col, windows, prefix)` — Legacy wrapper: adds EMA columns for one price column.
- `prepare_ema_helpers(df, base_price_cols, ema_windows, *, direction, scale, overwrite, round_places, price_cols, periods, **kwargs)` — Ensure first/second EMA diffs exist, then add scaled helper columns for each

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
- `_normalize(df)`
- `_normalize_freq(freq)` — Map deprecated aliases to current ones for resample():
- `_season_from_month(m)` — Meteorological seasons derived from month number:
- `resample_one(df, freq, agg, align_to)` — Resample a daily (or finer) dataframe with OHLCV into a target frequency.
- `resample_many(df, freqs, agg, outdir, overwrite)` — Build multiple timeframe views and (optionally) persist as parquet/csv.
- `add_season_label(df, column)` — Ensure a 'season' column exists (DJF/MAM/JJA/SON). Will attempt to use
- `seasonal_summary(df, price_col, ret_kind)` — Aggregate returns by season across years.

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

## `ta_lab2/research`

## `ta_lab2/research/notebooks`

## `ta_lab2/research/queries`

### `research/queries/opt_cf_ema.py`
**Functions**
- `_norm_cols(df)`
- `load_df(p)`
- `ensure_ema(df, span)`
- `build_grid(fasts, slows, delta)`
- `main()`

### `research/queries/opt_cf_ema_refine.py`
**Functions**
- `_norm_cols(df)`
- `load_df(p)`
- `ensure_ema(df, span)`
- `refine_ranges(tops, f_pad, s_pad, f_min, f_max, s_min, s_max)`
- `build_grid(fasts, slows, delta)`
- `main()`

### `research/queries/opt_cf_ema_sensitivity.py`
**Functions**
- `_norm_cols(df)`
- `load_df(p)`
- `ensure_ema(df, span)`
- `build_grid(f, s, f_pad, s_pad, delta)`
- `main()`

### `research/queries/opt_cf_generic.py`
**Functions**
- `_norm_cols(df)`
- `load_df(path)`
- `main()`

### `research/queries/run_ema_50_100.py`
**Functions**
- `_normalize_cols(df)`
- `_find_ts_col(cols)`
- `_find_close_col(cols)`
- `load_price_df(csv_path)`
- `ensure_ema(df, span, out_col)`
- `main()`

### `research/queries/wf_validate_ema.py`
**Functions**
- `_norm_cols(df)`
- `load_df(path)`
- `ensure_ema(df, span)`
- `rolling_train_test_splits(start, end, train_days, test_days, step_days)` — Yield (TRAIN_i, TEST_i) Split pairs from [start, end].
- `main()`

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

## `ta_lab2/utils`

### `utils/cache.py`
**Functions**
- `_key(name, params)`
- `disk_cache(name, compute_fn, **params)`

## `ta_lab2/viz`

### `viz/all_plots.py`
**Functions**
- `_pick_time_index(d)`
- `plot_ema_with_trend(df, price_col, ema_cols, trend_col, *, include_slopes, include_flips, n)`
- `plot_consolidated_emas_like(df, base_col, periods, *, include_slopes, include_flips, n)`
- `plot_realized_vol(df, *, windows, include_logret_stdev, n)`
