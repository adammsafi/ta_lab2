# New 12Wk Plan Table

*Converted from: new_12wk_plan_table.xlsx*

## Easy Wins (before 12_1)

<!-- Complex formatting may not be preserved -->

| ID | Name | Category | Description | Output / Artifact | Status |
| --- | --- | --- | --- | --- | --- |
| EW1 | Cutoff & trust ranges doc | Data / Docs | Run simple MAX(ts) and row-count queries for cmc_price_histories7, cmc_ema_daily, cmc_ema_multi_tf, cmc_ema_multi_tf_cal. Capture trusted-through dates in a doc. | docs/cutoff_dates.md | Done |
| EW2 | “Refresh EMAs” quickstart | Docs | Add a short section to README showing example commands to refresh daily EMAs, multi-TF EMAs, and calendar-aligned multi-TF EMAs. | Updated README.md section | Done |
| EW3 | Stub EMA refresh process doc | Docs | Create a skeleton process document describing inputs, basic steps to refresh EMAs, and a TODO for troubleshooting/flowchart later. | docs/ema_refresh_process.md | Done |
| EW4 | Minimal GitHub hygiene | PM / Infra | Create one GitHub Project and ~6 issues mapped to 12-week themes. Mark the EMA incremental work as complete in at least one issue. | GitHub Project + initial issues | Done |

## 12-Week Plan

<!-- Complex formatting may not be preserved -->

| Week | Date Range | Focus / Theme | Code (Main Tasks) | Ops / Infra (Main Tasks) | Docs (Main Tasks) | Acceptance Criteria |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Dec 1–7 | Lock in EMA stack & state | Finalize schemas/semantics for cmc_ema_daily, cmc_ema_multi_tf, cmc_ema_multi_tf_cal. Add 2–3 tests around row-count vs tf_days + roll/d1/d2 behavior. | Create simple price+EMA view (e.g. cmc_price_with_emas). | Flesh out docs/ema_refresh_process.md with incremental vs --start, stats overview. | Can explain EMA tables + refresh process in 2–3 minutes and demonstrate with one run + stats. |
| 2 | Dec 8–14 | Returns & volatility v1 | Implement cmc_returns_daily (1D, 2D, 5D, 10D returns) and basic realized volatility (could be separate table or same). | Create scripts/returns/refresh_cmc_returns.py with same incremental pattern as EMAs. | docs/returns_notes.md covering formulas, lookbacks, and quirks. | Single SQL query returns BTC close + 1D and 5D returns for any date range. |
| 3 | Dec 15–21 | Core TA indicators (RSI, MACD, BB, ADX) | Implement cmc_ta_daily table with RSI(14), MACD, Bollinger Bands(20,2σ), ADX(14). Reuse EMA engine where sensible. | scripts/ta/refresh_cmc_ta_daily.py with incremental logic. | Extend README with “Daily Indicators” section listing indicators and default params. | One query returns close, ema_20, rsi_14, macd, bb_up, bb_dn, adx for BTC for a month. |
| 4 | Dec 22–28 | Unified daily feature pipeline | Build cmc_daily_features (view or materialized) joining EMAs, returns, TA by id, ts. Add build_daily_features(ids, start, end=None) Python wrapper. | One CLI/script that runs “all daily features” for a given id set and date window. | Short architecture note/diagram for “daily features” in /docs. | Single CLI call (or function) builds a feature-complete daily dataset ready for backtests. |
| 5 | Dec 29–Jan 4 | Scheduling & environment sanity | Light adjustments only if needed to make refreshes idempotent and config-driven. | Add config file (YAML/TOML) for default ids, trusted-through, DB aliases. Set up daily scheduler (cron/Task Scheduler) for ingest + refresh. | docs/scheduling.md describing job timing, commands, and log locations. | EMAs and features update automatically overnight on at least one environment without manual intervention. |
| 6 | Jan 5–11 | Observability & quality checks | Create ta_lab2.stats module: row-count vs tf_days, max gap checks, NaN/inf checks, etc. | Make stats runnable as a daily/weekly job; write results into cmc_stats or similar table. | docs/stats_and_quality_checks.md describing each test and what FAIL/WARN/PASS mean. | After nightly job, you can quickly answer “Is the data healthy?” by inspecting one stats table/report. |
| 7 | Jan 12–18 | First simple signals & flip logic | Implement first-pass signals: e.g. EMA crossovers, RSI OB/OS, price vs bands. Optionally revive “flip segments” logic on top of EMAs/returns. | Populate cmc_signals_daily table from daily features. | docs/signals_v1.md describing signals, parameters, example queries/charts. | Can query “all dates where BTC flipped from downtrend to uptrend” according to at least one defined rule. |
| 8 | Jan 19–25 | Backtest skeleton | Implement minimal backtest runner: take feature view + signals, output trades, PnL, basic metrics (CAGR, max DD, Sharpe). | Save backtest results to a table or versioned CSVs in backtests/. | docs/backtest_v1.md describing assumptions (fees/slippage handling, etc.). | Able to run a simple strategy (e.g. “long when price > 100D EMA”) and see a performance summary. |
| 9 | Jan 26–Feb 1 | Testing & CI | Increase automated tests around EMA/multi-TF logic, daily feature calculations, and signals. | Set up GitHub Actions (or similar) to run tests (and optionally formatting/linting) on push/PR. | README section: “How to run tests & CI” with examples. | Every push triggers tests automatically and failures are visible in CI. |
| 10 | Feb 2–8 | Packaging & CLI polish | Clean up CLI into ta_lab2.cli.main with subcommands: pipeline, refresh-emas, refresh-daily-features, run-backtest. Tighten pyproject.toml. | Test installation on a fresh environment (new venv or small cloud instance). | Update README “Installation & CLI” usage examples. | On a clean machine you can: clone → install → run a CLI command end-to-end without extra manual setup. |
| 11 | Feb 9–15 | Documentation sprint | Only small refactors; main focus on doc polish and consistency. | Ensure notebooks/examples run with current code where applicable. | Cohesive docs set: overview, data model, EMA/multi-TF, daily features, signals, backtests, plus 1–2 example notebooks. | A future analyst “you” could onboard from the docs alone and reproduce core workflows. |
| 12 | Feb 16–22 | v0.3.x (or v0.4.0) internal release | Tag stable version with current schemas, working EMA + features + signals + tests. | Snapshot DB schema and/or export key tables (or migrations) for reproducibility. | Update CHANGELOG and a short “State of ta_lab2” note (what’s done, what’s next). | Clearly tagged, reproducible project state you can build the next development cycle on (new strategies, more assets, etc.). |
