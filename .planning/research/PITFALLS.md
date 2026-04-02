# Domain Pitfalls: v1.3.0 Operational Activation & Research Expansion

**Domain:** Activating a built-but-idle quant trading system: paper trading go-live, scaling backtests from 2 to 460K+ runs, adding ML signal combination, graduating CTF features, and expanding FRED macro coverage
**Researched:** 2026-03-29
**Scope:** Pitfalls specific to _adding these capabilities to an existing system_, not building them from scratch. The infrastructure exists; the risk is in activation and integration.

---

## 1. Paper Trading Activation Pitfalls

### CRITICAL: dim_executor_config Is Empty — The Executor Will Silently Process Zero Strategies and Log "Success"

**What goes wrong:** The paper executor reads active strategies from `dim_executor_config WHERE is_active=TRUE`. If this table is empty, `PaperExecutor.run()` iterates over zero configs, logs "0 strategies processed", exits with status code 0, and the daily refresh treats it as a success. There is no alarm. The system appears to be paper trading when it is doing nothing.

**Why it happens:** The seed file (`configs/executor_config_seed.yaml`) exists and is ready, but `seed_executor_config.py` was never run. The executor was built in Phase 45 and has been idle since. There is no validation at daily pipeline startup that checks whether executor configs exist before the executor stage runs.

**Consequences:** Paper trading burn-in starts but zero orders are generated. The 1-week burn-in "passes" (no safety triggers fire, PnL is zero). v1.3.0 is tagged with zero actual paper trades. The backtest parity check (which requires fills to compare against replay) will have nothing to compare.

**Prevention:**
- Add a pre-flight check in `run_daily_refresh.py` (executor stage) that queries `dim_executor_config` and raises an error if `COUNT(*) WHERE is_active=TRUE = 0`:
  ```python
  # Before running executor stage:
  with engine.connect() as conn:
      n = conn.execute(text(
          "SELECT COUNT(*) FROM dim_executor_config WHERE is_active=TRUE"
      )).scalar()
  if n == 0:
      raise RuntimeError("dim_executor_config has no active strategies. Run seed_executor_config.py first.")
  ```
- Run `seed_executor_config.py` as Step 1 of activation, not as an afterthought.
- Verify the seed resolved `signal_id` correctly (the seed script skips configs where `signal_name` is not found in `dim_signals` with only a WARNING, not an error):
  ```sql
  SELECT config_name, signal_id, is_active FROM dim_executor_config;
  -- Expect: ema_trend_17_77_paper_v1 and ema_trend_21_50_paper_v1
  ```

**Warning signs:**
- `run_paper_executor.py` output: "Strategies processed: 0" with status "success"
- `executor_run_log` table has no rows after a full day's pipeline run
- `paper_orders` table is empty 24 hours after activation

**Phase:** Executor activation phase (first phase of paper trading). Must be the very first task.

---

### CRITICAL: Signals Not in Daily Refresh Mean the Executor Has Nothing to Read

**What goes wrong:** `run_daily_refresh.py --all` includes a `signals` stage (Step 14 in `STAGE_ORDER`), but only if `--signals` is in the invocation or `--all` is used. In practice, the signals stage may have been disabled or skipped during v1.2.0 development to speed up daily runs. If the `signals_ema_crossover` table has no recent rows (no signal generated for today), the executor reads zero unprocessed signals (watermark filter: `ts > last_watermark_ts AND executor_processed_at IS NULL`). It processes nothing, logs "0 signals", and exits cleanly.

**Why it happens:** `StaleSignalError` is only raised if `last_watermark_ts` is NOT None (skipped on first run per `signal_reader.py` line 127: `if last_watermark_ts is None: return`). On the first run after a gap, the stale guard is bypassed. The executor finds no rows with `executor_processed_at IS NULL` because signals are stale or the table is empty, and exits successfully.

**Consequences:** First week of paper trading generates no fills. Appears to work when checked at the pipeline level.

**Prevention:**
- Verify signal tables are populated before enabling the executor. Run:
  ```sql
  SELECT signal_id, MAX(ts) AS latest_ts, COUNT(*) AS total_rows
  FROM signals_ema_crossover
  GROUP BY signal_id;
  -- Expect: latest_ts within 26 hours (cadence_hours=26.0 in executor config)
  ```
- Run `refresh_signals_ema_crossover.py` manually first. Confirm rows exist with `executor_processed_at IS NULL`.
- Add signal freshness monitoring to the daily pipeline alert stage (Phase 87 `signal_validation_gate` already exists for this purpose — verify it's wired to signal tables, not just AMA signal tables).
- When enabling signals in `run_daily_refresh.py --all`, confirm the stage runs every day, not just on demand.

**Warning signs:**
- `signals_ema_crossover` table is empty or `MAX(ts)` is days old
- `executor_run_log.total_signals = 0` on first run (combined with `last_watermark_ts IS NULL` means first run bypassed stale check)
- Paper executor running but `fills` table accumulating no rows

**Phase:** Executor activation phase. Signal pipeline must be verified running before executor is enabled.

---

### MODERATE: First Run of Executor Processes ALL Backlogged Signals, Not Just Today's

**What goes wrong:** On the first activation run, `last_watermark_ts` is NULL (no prior run in `executor_run_log`). The `SignalReader.read_unprocessed_signals()` query omits the `ts > :watermark_ts` clause when `last_watermark_ts is None`. It reads ALL rows in `signals_ema_crossover` where `executor_processed_at IS NULL`. If the signal table has months of historical data (which it likely does, since signal refresh has been running), the executor will process hundreds or thousands of signals from the past.

**Why it matters:** Each historical signal generates a paper order and a simulated fill. Positions will be "filled" at historical prices, producing artificial P&L that has nothing to do with live paper trading. The `positions` table will show holdings as if the executor has been running for months.

**Consequences:** Drift monitor starts from a contaminated position state. Parity check comparison between live paper fills and backtest replay becomes meaningless because paper fills include historical signals.

**Prevention:**
- Before first activation, mark all existing signals as processed to establish a clean watermark:
  ```sql
  UPDATE signals_ema_crossover
  SET executor_processed_at = now()
  WHERE executor_processed_at IS NULL;
  -- Repeat for signals_rsi_mean_revert and signals_atr_breakout
  ```
- Then run the executor with `--dry-run` first to confirm it reads 0 signals (watermark established but nothing unprocessed).
- Document the activation date in `executor_run_log` or a separate activation note. The drift monitor's `paper_start_date` parameter must be set to this date, not earlier.
- Alternatively, use `--replay-historical` mode explicitly when wanting to backfill, and use the standard mode only for forward-looking paper trading.

**Warning signs:**
- First executor run processes > 100 signals (implies backlog is being consumed)
- `fills` table timestamps span months before the activation date
- `positions` table shows non-zero holdings on day 1 of paper trading

**Phase:** Executor activation phase. Signal table pruning is a prerequisite.

---

### MODERATE: Drift Monitor Requires `--paper-start` Date That Must Match Activation Date

**What goes wrong:** The drift monitor compares paper fills (from `fills`) against backtest replay starting from `paper_start_date`. If `paper_start_date` is set to a date BEFORE executor activation (or not set at all, using the default), the backtest replay will try to match against fills that don't exist for that period, producing spurious drift signals or failing with no data.

From `drift_monitor.py` docstring: "Orchestrates the full drift guard pipeline... [requires] paper_start_date."

**Consequences:** Drift pauses are triggered immediately on the first run because there is no paper data for the comparison period. Kill switch logic may fire. The daily pipeline pauses all trading on day 1.

**Prevention:**
- Track the exact date of executor activation and use it consistently as `paper_start_date` in all drift commands:
  ```bash
  python run_daily_refresh.py --all --paper-start 2026-MM-DD
  ```
- Store the activation date in a config file (or `dim_executor_config` metadata) so it is not passed manually and risk being wrong.
- On first drift run after activation, use `--dry-run` to verify what the monitor would compute before enabling live drift pauses.

**Phase:** Executor activation and drift activation phases. Activation date must be tracked.

---

### MODERATE: `target_vol` Sizing Mode Falls Back to `fixed_fraction` Silently When GARCH Vol Is Unavailable

**What goes wrong:** `PositionSizer` supports `target_vol` sizing mode that uses GARCH blended conditional vol. From the code: "Falls back to fixed_fraction when GARCH vol is unavailable or not configured." If GARCH has not been refreshed (Phase 81 GARCH stage may not run reliably on every day), `get_blended_vol()` returns None and the fallback fires silently. The executor uses `fixed_fraction` (10%) instead of the volatility-adjusted size. No error is raised.

**Consequences:** Position sizing is wrong on days when GARCH is stale. This is not immediately visible because the executor succeeds. Over time, positions are systematically mis-sized during high-vol regimes (when GARCH is most important).

**Prevention:**
- Log an explicit WARNING when the fallback fires in `position_sizer.py`. The current code does this — verify the WARNING appears in executor logs.
- Add a GARCH freshness check to the executor pre-flight, similar to the signal freshness check:
  ```sql
  SELECT asset_id, MAX(ts) as latest_garch
  FROM garch_results  -- or whichever table stores GARCH outputs
  GROUP BY asset_id
  HAVING MAX(ts) < NOW() - INTERVAL '26 hours';
  ```
- Treat `target_vol` fallbacks above a threshold frequency as a drift signal.

**Phase:** Executor activation. Verify GARCH pipeline runs before executor runs.

---

## 2. Backtest Scaling Pitfalls (2 to 460K+ Runs)

### CRITICAL: Multiple Testing Inflates Sharpe Ratios — 460K Runs Without DSR Correction Will Surface Hundreds of False Positives

**What goes wrong:** The Deflated Sharpe Ratio (DSR) corrects for the selection bias from running many strategies on the same dataset. The formula: DSR = PSR deflated by the expected maximum SR from N independent trials. With 460,000 runs, even a true Sharpe of 0 has a high probability of showing SR > 1.0 in at least some trials purely by chance.

The `psr.py` module implements both PSR and DSR. DSR requires `n_trials` (the total number of trials tested on this dataset). If `n_trials` is set to a small number (e.g., the number of strategies, not parameter combinations), the DSR is under-deflated and still shows false positives.

**Why it happens for this system:** The bakeoff stores `dsr` in `strategy_bakeoff_results` but the `_bakeoff_asset_worker()` code sets `dsr=float("nan")` in the PKF phase (line ~236: `pkf_result["dsr"] = float("nan")`). DSR is computed post-hoc. If the post-hoc computation uses `n_trials = len(strategies)` rather than `n_trials = total_parameter_combinations_tested`, the deflation is too conservative only for strategy count, not parameter count.

**Consequences:** Strategies with SR 1.0-1.5 that are pure noise pass the DSR gate and get deployed to paper trading. Their paper P&L will be near-zero or negative.

**Prevention:**
- For DSR computation, `n_trials` must equal the TOTAL number of parameter combinations tested across ALL strategies on this dataset, not just the number of strategies. With 460K runs across 99 assets and N strategies, n_trials per asset = (total runs / 99).
- Verify the DSR formula in `psr.py` is using the correct `n_trials`. Check: does it account for cost scenarios separately (12 scenarios per param set), or only unique (strategy, param) pairs?
- Set a DSR threshold commensurate with the inflation risk. With 460K runs, a DSR threshold of 0.95 (currently planned) is too liberal. Consider 0.99 for cross-sectional ML models where overfitting risk is highest.
- For the 460K run scale, add a separate "trials tracker" table that persists the total runs count per dataset, so DSR computation has access to the true N regardless of which code path triggers the computation.

**Warning signs:**
- `dsr` values clustered near `nan` in `strategy_bakeoff_results` (DSR was never computed)
- `n_trials` parameter hardcoded to a small constant in the DSR computation
- Top-ranked strategies by DSR showing very similar parameter values (overfitting signature: optimizer locked onto noise features of a specific parameter range)

**Sources:** Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio" — HIGH confidence (foundational paper, directly implemented in `psr.py`)

**Phase:** Bakeoff expansion phase. DSR formula and n_trials calculation must be reviewed before scaling up.

---

### CRITICAL: Storage Growth Is Nonlinear — 460K Runs at Current Schema Will Require 20-50 GB in `strategy_bakeoff_results`

**What goes wrong:** The current schema stores fold-level metrics as a JSONB blob per run (`fold_metrics` column in `strategy_bakeoff_results`). With 10 folds per run and 460K runs, that's 4.6M fold-metric objects stored in JSONB. JSONB storage in PostgreSQL is not compact — each JSON object has type tags, key names repeated per row, and alignment padding. A conservative estimate of 500 bytes per row gives 230 GB just for the results table.

The current DB is already at 177 GB. Adding 230 GB would exceed a typical local Windows development disk.

**Why it happens:** The fold metrics JSONB pattern was fine for the original 2 runs. At 460K it becomes a storage crisis.

**Consequences:** PostgreSQL disk-full error mid-bakeoff. The bakeoff uses `ON CONFLICT DO NOTHING` (overwrite=False by default), so partially completed runs cannot easily be resumed. Hours of compute lost.

**Prevention:**
- Before scaling, estimate the actual storage per run by running 1,000 runs and measuring:
  ```sql
  SELECT pg_size_pretty(pg_total_relation_size('strategy_bakeoff_results'));
  SELECT COUNT(*) FROM strategy_bakeoff_results;
  -- Per-row size = table_size / row_count
  ```
- Consider storing only aggregate fold stats (mean, std, worst) in the main table, and writing full fold details to a separate `strategy_bakeoff_fold_details` table only for top-N runs. This keeps the main table compact.
- Alternatively, batch-partition the 460K runs: run 10K at a time, export results to Parquet, truncate the table, run the next 10K. Aggregate from Parquet files at the end.
- Set `work_mem = 256MB` and `maintenance_work_mem = 1GB` in PostgreSQL config before the large run, to reduce JSONB index overhead during mass inserts.
- Monitor disk space in the daily pipeline: `SELECT pg_size_pretty(pg_database_size('marketdata'))`.

**Warning signs:**
- `strategy_bakeoff_results` row count growing unexpectedly fast
- Disk usage spiking during bakeoff runs
- PostgreSQL log showing "could not write to file" errors

**Phase:** Bakeoff planning phase. Storage architecture must be decided before running 460K runs.

---

### CRITICAL: `maxtasksperchild=1` on Windows Has a Known CPython Bug That Can Cause Pool Hang

**What goes wrong:** The MEMORY.md documents: "Workers: NullPool for multiprocessing, `maxtasksperchild=1` on Windows." The CPython bug tracker (issues #10332, #38799, #54541) documents that `maxtasksperchild` combined with `Pool.map_async` or pool closure can cause the pool to hang indefinitely on Windows when workers complete their tasks and the worker handler thread exits before all tasks are drained.

The bakeoff orchestrator uses `multiprocessing.Pool` for per-asset parallelism (`_bakeoff_asset_worker`). With 99 assets at `maxtasksperchild=1`, the pool creates and destroys 99 worker processes. The hang probability increases with pool size and task count.

**Consequences:** Bakeoff hangs at ~90% completion. The parent process appears running (no crash) but no progress is made. On Windows, `Ctrl+C` may not cleanly terminate multiprocessing pools (signal handling limitation). Manual kill of `python.exe` processes in Task Manager is required. All partially computed results must be verified.

**Prevention:**
- Use `maxtasksperchild=1` only when memory leaks are confirmed. For the bakeoff, try first without `maxtasksperchild` and monitor RSS growth per worker.
- If memory growth requires `maxtasksperchild`, use a `ProcessPoolExecutor` (concurrent.futures) instead of `multiprocessing.Pool` — it has fewer Windows-specific hang bugs in Python 3.12.
- Set an explicit `timeout` on `pool.apply_async().get(timeout=...)` calls so workers that hang are killed rather than blocking forever.
- Implement a watchdog: if no task has completed in 10 minutes, terminate the pool and retry from the last checkpoint.
- Keep the `overwrite=False` / `existing_keys` deduplication in the bakeoff orchestrator (already implemented) so re-running after a hang resumes from where it stopped.
- Use `--num-processes 4` (not maximum CPU count) to reduce the chance of hitting the Windows pool scaling bug.

**Warning signs:**
- All Python worker processes in Task Manager showing 0% CPU but still existing
- No new results appearing in `strategy_bakeoff_results` for 10+ minutes while bakeoff is "running"
- `pool.join()` never returning in the orchestrator process

**Sources:** CPython issue #10332 and #38799 — HIGH confidence (official bug reports, Windows-confirmed)

**Phase:** Bakeoff execution. Use conservative pool settings and implement a timeout watchdog before scaling.

---

### CRITICAL: AMA Feature Lookback Contamination at Fold Boundaries If AMA Is Re-computed Instead of Loaded From DB

**What goes wrong:** AMA indicators have long lookbacks (KAMA default: 10-bar efficiency ratio, then exponential smoothing with full history dependence). If an AMA value is re-computed from raw price data WITHIN a cross-validation fold, the first N bars of each fold have initialization bias — the AMA does not yet reflect the full history before the fold start. This makes early-fold signals artificially weak or strong compared to signals generated from pre-computed AMA values that were fit on the full history.

The existing `ama_composite.py` explicitly documents this pitfall in its module docstring: "AMA columns are loaded from the database by `load_strategy_data_with_ama()`. They do NOT re-compute AMA values from price. See 'Pitfall 6' of 82-RESEARCH.md for why this matters: local AMA recomputation introduces fold-boundary lookback contamination."

**Why it matters for the 460K run scale:** Any new strategy that bypasses `load_strategy_data_with_ama()` and re-computes AMA locally (e.g., in an expression engine experiment) will have subtly contaminated folds. This produces inflated OOS Sharpe ratios because early-fold bars (where AMA is still "warming up") have uncorrelated signals that look like valuable diversification.

**Consequences:** False OOS alpha. Strategies using locally re-computed AMA appear to have better OOS statistics than strategies using pre-computed DB values. In production, the AMA is always pre-computed, so live P&L is worse than backtest.

**Prevention:**
- Any new signal function that uses AMA must use the pre-computed values from `load_strategy_data_with_ama()`. Enforce this by making `ama_multi_tf_u` the ONLY source of AMA data in backtests.
- Add a validation assertion in `load_strategy_data_with_ama()`: if the returned DataFrame has AMA columns with NaN in the first 20 rows (which would indicate in-fold recomputation), raise a warning.
- For expression engine experiments that use AMA features, verify that the expression references column names from the pre-loaded DataFrame, not re-computes them from `close`.
- Document this as a permanent code review gate: "AMA must come from DB, never computed locally in backtests."

**Warning signs:**
- Signal function code contains `pd.EWM` or similar exponential smoothing applied to `close` price
- AMA columns in backtest DataFrames showing NaN in the first 10-20 rows
- OOS Sharpe significantly higher for AMA strategies than for non-AMA strategies of equivalent IC

**Phase:** Any phase adding new signal functions or expression engine experiments.

---

### MODERATE: PBO Analysis With 45 CPCV Combinations Requires Statistical Power — Fewer Than ~100 Trades Per Fold Invalidates the Result

**What goes wrong:** CPCV with C(10,2)=45 combinations produces a PBO estimate by ranking OOS performance across combinations. If a fold has fewer than ~50-100 trades, the fold-level Sharpe has huge variance (it is computed from too few observations). The PBO estimate becomes unreliable — you cannot distinguish skill from luck at low trade counts.

For AMA momentum signals with long holding periods (5-20 days) and conservative entry thresholds, a 330-bar fold (1 year of daily data) may generate only 10-20 trades. PBO from such folds is noise.

**Consequences:** PBO gate passes strategies with insufficient trade history. Paper trading reveals them to be pure noise.

**Prevention:**
- Add a minimum trade count gate: any (strategy, param, cost) combination with fewer than 50 total trades across ALL folds is automatically excluded from selection, regardless of Sharpe.
- Include `trade_count_total` in the `strategy_bakeoff_results` schema (already present) and filter on it in the strategy selection query.
- For swing trading strategies with ~10-day holding periods at daily data, the minimum fold size should be 200 bars (0.5 year). Adjust `BakeoffConfig.min_bars` accordingly.

**Phase:** Bakeoff phase. Add trade count gate alongside DSR and PBO gates.

---

### MODERATE: Crypto Backtest History Has a Bull Run Contamination Problem — 2019-2021 Data Inflates All Trend Metrics

**What goes wrong:** The ~3 years of price history in `price_bars_multi_tf` spans an unusual period: 2020-2021 crypto bull run (BTC +1000%), 2022 crypto bear market (BTC -75%), 2023-2024 partial recovery. AMA features are trend-following by nature (18/20 active features). Walk-forward folds that include the 2020-2021 bull run will show Sharpe ratios of 3-5+ for any trend-following strategy, even a random one with momentum bias.

The Sharpe 0.98 documented in system context with 80% max DD suggests the OOS metrics are already being pulled up by bull-run-era folds. Actual forward-looking Sharpe in a ranging or bear market may be 0.1-0.3.

**Consequences:** Strategy selection based on walk-forward metrics overcounts trend-following skill. Paper trading in a non-trending market will underperform the selected strategies' historical Sharpe by 3-5x.

**Prevention:**
- Analyze Sharpe distribution BY FOLD YEAR. Folds with endpoints in 2020-2021 should be treated as held-out "bull run" folds, not mixed into OOS selection.
- Add regime-conditional analysis: what is the OOS Sharpe for trend-following strategies IN RANGING regimes? This number is more predictive of near-term performance.
- Set a minimum number of bear-regime folds (L0 regime = "bear_high_vol" in regime labeling) required for strategy selection. If a strategy has zero bear-regime trades, it cannot be selected regardless of OOS Sharpe.
- Weight CPCV combinations by their regime diversity, not just their OOS Sharpe rank.

**Phase:** Strategy selection and paper trading activation phases. Add regime-conditional performance gates.

---

## 3. ML Signal Combination Pitfalls

### CRITICAL: Cross-Sectional ML on 99 Assets With N_Features > N_Training_Samples Will Overfit Severely

**What goes wrong:** For cross-sectional LightGBM (training on all 99 assets simultaneously), the training set is roughly: N_assets * N_bars * N_folds = 99 * 1800 * 0.9 = ~160,000 observations. With 131 active CTF features plus 20 AMA features = 151 input features, the feature-to-observation ratio is 1:1,000 — well within safe bounds for LightGBM. BUT if per-asset interaction terms are added (asset_id * feature), the effective feature space explodes to 99 * 151 = 14,949 features, putting the ratio at 1:10 — severe overfitting territory.

**Why it happens:** The decision to add per-asset customization depth (from 82-CONTEXT.md) may lead to adding asset-level interactions. LightGBM will find spurious patterns across assets in the training set that don't generalize.

**Consequences:** Cross-sectional model produces high IS Sharpe (2-3+) and near-zero OOS Sharpe. LightGBM's leaf-wise tree growth finds asset-specific noise patterns quickly when interactions are included.

**Prevention:**
- Use universal features only for the first cross-sectional model. NO per-asset interaction terms.
- If per-asset customization is needed, train separate per-asset models (99 models) rather than one model with asset interactions. Compare the two approaches explicitly in the bakeoff.
- Set `min_data_in_leaf >= 200` in LightGBM config to force each leaf to generalize across at least 200 observations.
- Enforce `num_leaves <= 31` (the existing default in `double_ensemble.py`) for cross-sectional training even if IS performance looks better with more leaves.
- Use CPCV PBO as the primary selection criterion for ML models, NOT IS Sharpe.

**Warning signs:**
- Cross-sectional LightGBM IS Sharpe > 2.0 (almost certainly overfit at that level)
- SHAP values showing `asset_id` as the top feature (the model learned asset-specific noise)
- OOS performance drops sharply when evaluated on assets NOT in training (held-out asset test)

**Phase:** ML signal combination phase. Feature set and LightGBM config must be reviewed before training.

---

### CRITICAL: Information Leakage Between Train and Test Folds Is Possible When Feature Computation Spans Fold Boundaries

**What goes wrong:** Rolling z-score features (e.g., AMA z-score over 252-day window) computed on the FULL dataset before splitting into folds contaminate training data with future information. The z-score at bar T uses the mean and std from bars T-252 to T — but if this is computed on the full history including the test fold, the mean/std for bars near the fold boundary incorporate test-fold data.

This is distinct from the AMA initialization problem (pitfall above): this is a normalization leakage. The signal may look "scaled" in training but is actually using the test period's distribution.

**Why it happens for this system:** The `ama_composite.py` z-score is computed at signal generation time, not at backtest time: "computes an IC-IR-weighted composite from the top-5 AMA columns, z-scores the composite over a rolling window." If the composite is z-scored AFTER loading the full history, leakage occurs.

**Consequences:** AMA momentum signal produces inflated IS and OOS Sharpe (the leakage makes the signal look cleaner). After deployment, the signal is z-scored only on available history, producing different thresholds and worse performance.

**Prevention:**
- Z-score features MUST be computed per-fold, not on the full dataset. The z-score window at the fold boundary must look ONLY backward into the training period.
- In `load_strategy_data_with_ama()`, do NOT pre-z-score AMA columns. Load raw AMA values and z-score within the signal function AFTER the fold split.
- Add an explicit test: for a test fold, verify that no z-score denominator (std) depends on bars that fall inside the test period. This can be checked by computing the rolling std at the first bar of the test fold using only training data and comparing it to the std computed on the full history.
- Document this as a permanent gate in code review: "z-score computation in signal functions must use only past data."

**Warning signs:**
- Z-scoring performed as a DataFrame-level preprocessing step before the CV loop
- Signal function using `df.rolling(252).zscore()` on the full loaded DataFrame
- Unrealistic signal consistency at fold start (signals are unnaturally smooth across the fold boundary)

**Phase:** Any phase adding ML or composite signal functions.

---

### MODERATE: DoubleEnsemble's Sliding-Window Reweighting Can Amplify Bull-Run Bias in Crypto Data

**What goes wrong:** `double_ensemble.py` uses recency weighting: "later windows receive higher weight so that the ensemble's output is biased toward recent market structure." If "recent" = 2023-2024 (crypto recovery), the model up-weights bull market pattern recognition. The up-weighting is by window recency, not by regime. In a bear market, the most-recent window has the highest weight but also the most different distribution from the bull market windows.

**Consequences:** DoubleEnsemble performs worse in bear/ranging regimes than a simple equal-weight ensemble, because the recency weighting concentrates the model on the most recent regime and ignores regime-invariant patterns.

**Prevention:**
- For crypto with regime shifts, consider regime-adaptive weighting (weight windows by regime similarity to current regime) rather than pure recency weighting.
- Compare DoubleEnsemble vs uniform-weight ensemble on the same walk-forward folds. Select the approach with higher DSR, not higher IS Sharpe.
- Cap the recency weight multiplier so the most-recent window does not receive more than 3x the weight of the oldest window.

**Phase:** ML signal combination phase. DoubleEnsemble should be treated as one of several ensemble approaches, not the default.

---

### MODERATE: `regime_router.py` Training Data Has Only ~3 Years of Regimes — Too Few Regime Transitions for Reliable Classifier

**What goes wrong:** The `regime_router.py` trains a classifier to route signals by market regime. The training data has approximately 3 years (1,100 bars) of daily data with regime labels from the L0-L2 labeling system. Crypto markets had roughly 2-3 major regime transitions (bull→bear→recovery) in this period. With this few transitions, the regime classifier learns to distinguish "2021" from "2022" (year effects) rather than "trending" from "ranging" (structural effects).

**Consequences:** Regime router overfits to the specific market events in the training data. In a new regime type (e.g., sideways consolidation without a bear crash), the classifier assigns wrong regime labels, routing signals through the wrong gate.

**Prevention:**
- Test the regime router on regimes held out from training. If the held-out period is 2024, the classifier should correctly identify 2024's regime transitions without having seen them.
- Require a minimum of 5 regime transitions per regime type in the training set before using the regime router. With only 3 years of crypto data, this threshold may not be met.
- As a fallback, use the deterministic L0 regime label (already computed in `regimes` table) rather than a learned classifier for routing. The L0 label (bull/bear/ranging) is mechanistic, not learned, and is more regime-stable.

**Phase:** ML signal combination phase. Regime router evaluation must include out-of-regime holdout testing.

---

## 4. CTF Feature Graduation Pitfalls

### CRITICAL: Adding 131 CTF Features to the Daily Pipeline Increases Feature Compute Time — Pipeline May Exceed Daily Window

**What goes wrong:** The current `run_daily_refresh.py` has `TIMEOUT_FEATURES = 1800` (30 minutes). The current feature pipeline (`run_all_feature_refreshes.py`) runs ~20 active AMA features for 99 assets. Adding 131 CTF features (all 99 assets, daily + weekly TF) multiplies feature computation by ~7x. If each feature requires a DB write and the current pipeline takes 20 minutes, the extended pipeline takes ~2.5 hours — exceeding the TIMEOUT_FEATURES by 5x.

**Why it matters:** `run_daily_refresh.py` uses `subprocess.Popen` with timeouts. If `TIMEOUT_FEATURES` is exceeded, the subprocess is killed, features are partially updated, and the downstream signal stage runs on stale or incomplete feature data. There is no rollback.

**Consequences:** Signals generated from partial features (some assets updated, some stale). The stale assets generate signals based on 2-day-old CTF features, while updated assets use fresh data. Inconsistent signal timing creates spurious cross-asset patterns in portfolio construction.

**Prevention:**
- Before graduating CTF features, benchmark: run CTF refresh for all 131 features on 5 assets and extrapolate runtime to 99 assets.
- Increase `TIMEOUT_FEATURES` if needed, and split feature computation into multiple parallel batches (features are independent per asset, so batch by asset range).
- Prefer incremental CTF refresh (watermark-based, only recompute new bars) over full-rebuild to keep daily runtime bounded.
- Monitor feature freshness: add a check that all 131 CTF features have `ts` within the last 26 hours before the signal stage runs.

**Warning signs:**
- Feature refresh subprocess being killed by timeout (returncode -9 on Linux / -1 on Windows signal)
- `features` table having different `MAX(ts)` values across assets after a refresh
- Signal stage generating fewer signals than expected (missing features for some assets)

**Phase:** CTF feature graduation phase. Runtime benchmarking is a prerequisite.

---

### MODERATE: CTF Features Derived From External Data (HL, FRED) Will Silently Degrade When Sync Fails

**What goes wrong:** CTF features that use Hyperliquid open interest, funding rates, or FRED macro data depend on the VM sync pipelines (`sync_hl_from_vm.py`, `sync_fred_from_vm.py`). If the Singapore VM is unreachable (SSH timeout, VM restart), the HL data is stale. CTF features that use HL data silently compute with old values, producing signals that are 1-3 days behind on funding/OI regime.

The daily pipeline already has VM sync as Step 1 (`sync_vms` stage). But the pipeline continues even if sync fails partially (there is no hard stop for stale VM data downstream).

**Consequences:** Funding-rate-based signals degrade silently during VM outages. Paper trading may generate fills based on stale HL data without any alert.

**Prevention:**
- Add a data freshness gate for CTF features that use external sources: before the feature stage, verify that `hyperliquid.hl_funding_rates MAX(ts)` and `fred.series_values MAX(updated_at)` are within tolerance (e.g., 30 hours for daily data).
- The existing Phase 87 `signal_validation_gate` should be extended to check external data freshness, not just signal table freshness.
- Log a WARNING (or send a Telegram alert) when feature computation uses stale external data, even if the feature compute itself succeeds.

**Phase:** CTF graduation and live pipeline phases. External data freshness checks must be in place.

---

## 5. FRED Macro Expansion Pitfalls

### MODERATE: Adding New FRED Series Mid-Pipeline Requires Backfilling — Partial History Creates Spurious Regime Change Signals

**What goes wrong:** When a new FRED series is added to the macro pipeline (e.g., expanding from 39 to 50 series), the new series starts with only recent data in the local DB (VM sync only pulls forward from the most recent date). If the macro regime classifier was trained on all 39 series and now receives 50 series with 11 of them having only 3 months of history, the classifier either errors or produces undefined behavior for the new series during the historical period.

More subtly: the regime classifier computes rolling correlation or z-score features over a window (e.g., 12 months). New series with only 3 months of data will have NaN values for the first 9 months of the window, causing the regime to be labeled as "no data" rather than the correct label.

**Consequences:** Macro regime labels flip incorrectly for the backfill period, potentially triggering macro gates that flatten positions on the first refresh after adding new series.

**Prevention:**
- Before activating new FRED series in the macro pipeline, backfill their history on the VM via the FRED API (historical downloads), sync to local, and verify they have at least 2 full years of history before including them in the regime classifier training.
- After adding new series, retrain the macro regime classifier from scratch on the full extended dataset. Do NOT incrementally add new series to a trained classifier — retrain.
- Run the macro regime comparison (existing `compare_migration.py` pattern) to verify regime labels are stable before and after the addition.

**Phase:** FRED macro expansion phase. Series backfill must precede pipeline integration.

---

### MINOR: FRED Data Is Published With Revisions — Historical Values Can Change, Causing Regime Label Flips

**What goes wrong:** FRED publishes revised values for many series (e.g., GDP, employment data is revised as new data comes in). The `sync_fred_from_vm.py` script syncs incremental new rows but may not overwrite previously synced rows that have since been revised. This means the local DB may have stale historical values for revised series.

**Consequences:** Macro regime labels computed in Q1 2026 may differ from labels computed in Q4 2025 for the same historical period (due to data revisions). This creates time-inconsistency in the training data — the classifier learned on Q4 2025 labels but is now evaluated on Q1 2026 labels for the same period.

**Prevention:**
- Use the `--full` resync mode periodically (monthly) to ensure historical FRED values are up to date:
  ```bash
  python -m ta_lab2.scripts.etl.sync_fred_from_vm --full
  ```
- Add a revision detection log: compare `series_values.value` for historical dates between the current sync and the previous full sync. Log any revisions larger than 5%.
- Accept that point-in-time (PIT) backtest accuracy for macro-integrated strategies is inherently limited without a PIT data store. For paper trading purposes, this is acceptable.

**Phase:** FRED macro expansion and ongoing maintenance.

---

## 6. Cross-Cutting Pitfalls (All v1.3.0 Phases)

### CRITICAL: The 177 GB Database Is Already at Risk of Disk Pressure During Simultaneous 460K Backtest and CTF Feature Addition

**What goes wrong:** If the 460K bakeoff run and CTF feature graduation happen in the same week, the DB may receive simultaneous pressure from:
- `strategy_bakeoff_results`: +20-50 GB (estimated above)
- `features` table with 131 new CTF features: +~5-10 GB
- `strategy_bakeoff_results` JSONB indexes: +10-20 GB
- PostgreSQL WAL during mass inserts: temporary +5 GB

Total potential addition: 40-80 GB in one week, bringing the DB from 177 GB to 220-260 GB. On a local Windows development machine with a 500 GB SSD (typical), this leaves only 240-280 GB free, which is fine. But on a 256 GB SSD, it risks running out of space.

**Prevention:**
- Check available disk before starting any large operation:
  ```sql
  SELECT pg_size_pretty(pg_database_size('marketdata')) AS current_db_size;
  ```
  Also check OS-level disk space (Windows Explorer or `df -h` in WSL).
- Stage the operations: complete CTF graduation first, verify disk usage, then run the 460K bakeoff.
- Set PostgreSQL's `temp_file_limit` to prevent runaway temp file growth during sorts.

**Phase:** All phases with large data operations.

---

### MODERATE: Windows Task Scheduler Is Unreliable for Daily Pipeline — Manual Cron Is Fragile

**What goes wrong:** The daily pipeline (`run_daily_refresh.py --all`) must run every day for paper trading to generate fills. On Windows, Task Scheduler is the standard cron alternative but has known reliability issues: scheduled tasks can fail silently when the machine sleeps/resumes, when the user is logged out, or when a previous task run is still active (leading to overlapping runs).

The paper executor's stale signal guard (`StaleSignalError`) will fire after 26 hours. If the daily pipeline is delayed by more than 26 hours (skipped day + 2 hours), the executor raises `StaleSignalError` and skips execution for that run. No fills are generated. The stale guard works as designed but the gap in paper trading history makes parity analysis harder.

**Consequences:** Paper trading has gaps. Parity check correlation degrades because fills are missing for some dates.

**Prevention:**
- Document the exact Task Scheduler configuration (trigger, conditions, settings) in the runbook. Include "Run task as soon as possible after a scheduled start is missed" checkbox status.
- Add a pipeline execution log that records success/failure per day. If two days in a row fail, send a Telegram alert.
- The existing `executor_run_log` table serves this purpose — add a daily monitoring query that checks for gaps:
  ```sql
  SELECT date_trunc('day', run_at) as day, COUNT(*) as runs
  FROM executor_run_log
  WHERE run_at > NOW() - INTERVAL '7 days'
  GROUP BY 1 ORDER BY 1;
  -- Any missing days = pipeline scheduling failure
  ```

**Phase:** Paper trading activation and ongoing operations.

---

### MINOR: Signal Pipeline Produces "Successful" Signals on Assets With Stale Bars — Signals Are Behind By 1-2 Days

**What goes wrong:** The signal generator (`refresh_signals_ema_crossover.py`) reads from `features` and `ema_multi_tf_u`. If bar refresh for some assets fails (e.g., a CMC API timeout for a specific asset), that asset's last bar is 1-2 days old. The signal generator does NOT check bar freshness — it computes a signal from whatever data is in the table. The signal timestamp (`ts`) will be 1-2 days old, but `executor_processed_at IS NULL` still. The executor reads it as an "unprocessed" signal and acts on it.

**Consequences:** Paper fills at stale timestamps. Position appears to have been entered 2 days ago. Parity check alignment fails because the fill timestamp doesn't match backtest expectations.

**Prevention:**
- Add a bar freshness check to the signal generation stage: skip assets where `MAX(ts)` in `price_bars_multi_tf` is more than 48 hours old.
- The existing Phase 87 `signal_validation_gate` is designed for this — verify it checks bar freshness per asset, not just signal count.

**Phase:** Paper trading and signal pipeline activation.

---

## Phase-Specific Warnings Summary

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|---|---|---|---|
| Executor activation | `dim_executor_config` empty — executor silently does nothing | Critical | Pre-flight check: `COUNT(*) WHERE is_active=TRUE > 0` |
| Executor activation | Signal tables empty or stale — executor reads zero signals | Critical | Verify `signals_ema_crossover` has rows with `executor_processed_at IS NULL` before enabling |
| Executor activation | First run processes all historical backlogged signals | Moderate | Mark all historical signals as processed before first run |
| Executor activation | Drift monitor `paper_start_date` mismatch | Moderate | Track activation date, pass it consistently to drift commands |
| Executor activation | `target_vol` sizing silently falls back to `fixed_fraction` | Moderate | Verify GARCH pipeline runs before executor stage |
| Bakeoff scaling | DSR under-deflated with 460K trials | Critical | Verify `n_trials` = total parameter combos, not strategy count |
| Bakeoff scaling | `strategy_bakeoff_results` storage: 20-50 GB at 460K runs | Critical | Estimate storage per run before scaling; split fold_metrics to separate table |
| Bakeoff scaling | Windows multiprocessing pool hang with `maxtasksperchild=1` | Critical | Use `ProcessPoolExecutor` + task timeout watchdog; keep `overwrite=False` for restart capability |
| Bakeoff scaling | AMA fold-boundary lookback contamination in new signal functions | Critical | All AMA features must come from DB (pre-computed), never re-computed within fold |
| Bakeoff scaling | PBO invalid when fewer than 50 trades per fold | Moderate | Add minimum trade count gate alongside DSR threshold |
| Bakeoff scaling | Bull run contamination inflates all trend-following metrics | Moderate | Analyze Sharpe by fold year; require bear-regime trades for selection |
| ML combination | Cross-sectional LightGBM with per-asset interactions overfits | Critical | Universal features only; no asset-specific interactions |
| ML combination | Z-score leakage across fold boundaries | Critical | Z-score computed per-fold, not on full history |
| ML combination | DoubleEnsemble recency weighting amplifies regime bias | Moderate | Compare vs equal-weight ensemble; cap recency multiplier |
| ML combination | Regime router trained on too few regime transitions | Moderate | Fallback to deterministic L0 regime label if classifier fails holdout test |
| CTF graduation | Feature compute timeout: 131 features may exceed 30-minute window | Critical | Benchmark runtime for 5 assets before graduating all 131 |
| CTF graduation | External data (HL, FRED) silently stale in CTF features | Moderate | Add external data freshness gate before feature stage |
| FRED expansion | New series with partial history creates spurious regime changes | Moderate | Backfill 2+ years before integrating into classifier |
| All phases | Disk pressure from simultaneous 460K bakeoff + CTF features | Critical | Stage operations; check disk space before each large run |
| All phases | Windows Task Scheduler drops daily pipeline runs silently | Moderate | Monitor `executor_run_log` for daily gaps; Telegram alert |
| All phases | Signals generated from assets with stale bars | Minor | Bar freshness check in signal validation gate |

---

## Sources

- Direct codebase inspection — HIGH confidence. Examined:
  - `src/ta_lab2/executor/paper_executor.py` (execution flow, 10-step docstring, dim_executor_config dependency)
  - `src/ta_lab2/executor/signal_reader.py` (watermark pattern, stale guard first-run bypass on line 127)
  - `src/ta_lab2/executor/position_sizer.py` (target_vol fallback behavior documented in module docstring)
  - `src/ta_lab2/scripts/executor/seed_executor_config.py` (ON CONFLICT DO NOTHING, signal_name resolution with WARNING-not-error)
  - `src/ta_lab2/scripts/run_daily_refresh.py` (STAGE_ORDER, TIMEOUT_FEATURES=1800, TIMEOUT_EXECUTOR=300, signals stage position)
  - `src/ta_lab2/backtests/bakeoff_orchestrator.py` (dsr=float("nan") in PKF phase, BakeoffAssetTask, multiprocessing pool pattern)
  - `src/ta_lab2/backtests/cv.py` (PurgedKFoldSplitter, CPCVSplitter, fold structure)
  - `src/ta_lab2/backtests/psr.py` (DSR implementation, n_trials parameter)
  - `src/ta_lab2/ml/double_ensemble.py` (recency weighting, sliding window, _DEFAULT_PARAMS with num_leaves=20)
  - `src/ta_lab2/signals/ama_composite.py` (explicit fold-boundary lookback warning, pre-computed AMA requirement)
  - `src/ta_lab2/drift/drift_monitor.py` (paper_start_date requirement, backtest replay comparison)
  - `configs/executor_config_seed.yaml` (dim_executor_config EMPTY state confirmed by file existence without DB confirmation)
  - `.planning/phases/82-signal-refinement-walk-forward-bakeoff/82-CONTEXT.md` (AMA dominance 18/20, cross-sectional ML scope)
  - `.planning/phases/88-integration-testing-go-live/88-CONTEXT.md` (burn-in protocol, parity check tolerance)
  - `.memory/MEMORY.md` (NullPool + maxtasksperchild Windows pattern, DB size 177 GB)

- [CPython Issue #10332: Multiprocessing maxtasksperchild results in hang](https://bugs.python.org/issue10332) — HIGH confidence (official CPython bug tracker, Windows-confirmed)
- [CPython Issue #38799: Race condition in multiprocessing.Pool with maxtasksperchild=1](https://bugs.python.org/issue38799) — HIGH confidence (official CPython bug tracker)
- [Bailey & Lopez de Prado: The Deflated Sharpe Ratio (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) — HIGH confidence (primary academic source, directly implemented in psr.py)
- [Bailey et al: The Probability of Backtest Overfitting (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) — HIGH confidence (primary academic source, CPCV/PBO basis for existing cv.py)
- [LightGBM Parameters Tuning Documentation](https://lightgbm.readthedocs.io/en/latest/Parameters-Tuning.html) — HIGH confidence (official LightGBM docs on min_data_in_leaf and num_leaves overfitting controls)
- [Balaena Quant Insights: Best Backtesting Practices for CTA in Crypto](https://medium.com/balaena-quant-insights/best-backtesting-practices-for-cta-trading-in-cryptocurrency-e79677cb6375) — MEDIUM confidence (practitioner article on regime/bull-run contamination in crypto backtests)
- [Bailey et al: Backtest Overfitting and Statistical Testing (PDF)](https://www.davidhbailey.com/dhbpapers/overfit-tools-at.pdf) — HIGH confidence (foundational paper, "no more than 45 variations per 5 years of daily data" guideline)
