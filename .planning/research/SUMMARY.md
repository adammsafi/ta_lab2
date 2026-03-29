# Project Research Summary

**Project:** ta_lab2 v1.3.0 — Operational Activation & Research Expansion
**Domain:** Quant trading platform activation: paper executor go-live, backtest scaling (2 to 460K+ runs), ML signal combination, CTF feature graduation, FRED macro expansion
**Researched:** 2026-03-29
**Confidence:** HIGH (all four research files grounded in direct codebase inspection + verified external sources)

---

## Executive Summary

v1.3.0 is not a build-from-scratch milestone — it is an activation milestone. The platform's
infrastructure (executor, signal generators, BL portfolio, GARCH, CTF, FRED pipeline, regime
labels, drift monitor) is fully implemented and has been sitting idle since v1.2.0. The central
challenge is wiring together components that were built in separate phases and never connected
end-to-end in production. The executor is silent because `dim_executor_config` is unseeded, not
because any code is missing. CTF features are orphaned because `feature_selection.yaml` was never
updated. Monte Carlo Sharpe columns are all NULL because `monte_carlo_trades()` was never called
in batch. In every case the fix is configuration or a one-way ETL connection, not new
infrastructure.

The recommended approach is to activate in strict dependency order: (1) operational activation
(days 1-3, zero new code — only seeding and scheduling), (2) FRED macro expansion (days 3-5,
self-contained, additive), (3) CTF graduation and backtest scaling infrastructure in parallel
(days 5-10, both independent of each other), then (4) ML signal combination last (days 10-15,
depends on CTF features being available in the `features` table and backtest infrastructure to
validate ML signals before paper deployment). Two new libraries are required: `shap>=0.51.0` and
`xgboost>=3.2.0`, both as optional extras in a new `[ml]` group. Everything else is already
installed.

The key risks are not technical — they are operational. An empty `dim_executor_config` produces a
silent false-success that makes the system appear to be paper trading when it is doing nothing.
First executor activation with unprocessed historical signals will replay months of fills at
historical prices, contaminating the burn-in baseline. At 460K backtest runs, DSR under-deflation
(using strategy count as `n_trials` instead of total parameter combinations) will surface hundreds
of false-positive strategies. Disk pressure from simultaneous bakeoff and CTF feature addition can
bring a 177 GB database to disk-full in a single week. Every critical risk has a documented
prevention strategy; none are architectural surprises.

---

## Key Findings

### Recommended Stack

The existing stack covers 100% of v1.3.0 requirements except two targeted additions. Python 3.12,
PostgreSQL 14+, SQLAlchemy 2.0, pandas 3.0, numpy 2.4, vectorbt 0.28.1, LightGBM 4.6.0 (including
`LGBMRanker`), scikit-learn 1.7, scipy 1.15, joblib 1.5, schedule 1.2.2, fredapi 0.5.2, and the
existing multiprocessing patterns all cover every v1.3.0 requirement without upgrades.

**New additions (optional extras group `[ml]`):**

- **`shap>=0.51.0`**: SHAP feature importance for `LGBMRanker` and `XGBClassifier`. v0.51.0
  (released 2026-03-04) adds pandas 3.0 compatibility. `TreeExplainer` works natively with
  LightGBM 4.6.0. Complements the existing `feature_importance.py` (MDA/SFI) — not a replacement.
- **`xgboost>=3.2.0`**: XGBoost meta-label filter. v3.2.0 (released 2026-02-10) has full Windows
  wheels. Enables genuine A/B comparison against the existing `MetaLabeler` (RandomForest). SHAP
  integrates natively via the same `TreeExplainer` interface.

**Explicit non-additions (verified and rejected):**

- APScheduler v4.0 is alpha-only; Windows Task Scheduler + existing `schedule 1.2.2` is correct.
- Ray/Dask/Celery/Prefect: single-machine platform, `multiprocessing.Pool + NullPool` is sufficient.
- `LGBMRanker`: already in LightGBM 4.6.0 — no upgrade needed.
- `yfinance` as primary FRED source: creates dual-source provenance; `fredapi` covers SP500/NASDAQ.
- Russell 2000 via FRED: FTSE Russell removed all 36 series from FRED in October 2019 — not available.

**FRED equity index data notes:**
`SP500` and `DJIA` are limited to 10 years of daily history by S&P licensing. `NASDAQCOM`
(full history from 1971) and `NASDAQ100` (full history from 1986) have no restriction. The
`forward_fill.py` ffill limits for all four series were pre-wired at lines 71-74 — they just
need to be verified and activated.

See `.planning/research/STACK.md` for full decision rationale per library.

---

### Expected Features

All five capability areas have well-defined table-stakes features, differentiators, and explicit
anti-features. See `.planning/research/FEATURES.md` for full per-area feature trees with
dependency graphs and MVP recommendations.

**Must have (table stakes) — Operational Activation:**
- `dim_executor_config` seeded and active for all 3 signal types (EMA crossover, RSI mean revert, ATR breakout)
- Automated daily schedule via Windows Task Scheduler running `run_daily_refresh.py --all`
- Signal freshness guard calibrated: `cadence_hours=36` in executor config (12-hour buffer over 24h cadence)
- Historical signal backlog marked `executor_processed_at = now()` before first executor run
- Parity checker (`parity_checker.py`) scheduled weekly after 4-week burn-in

**Must have — Backtest Scaling:**
- Resume-safe `backtest_run_state` DB table (tracks `pending/running/complete/failed` per params_hash)
- `backtest_trades` partitioned by `strategy_name` before reaching 20M+ rows
- Monte Carlo wired into every run: `monte_carlo_trades()` populates `mc_sharpe_lo/hi/median`
- `run_mass_backtest.py` with `NullPool + maxtasksperchild` and per-asset chunking
- Early stopping: prune combos at fold-1 Sharpe < -0.5 before running all folds

**Must have — ML Signal Combination:**
- Cross-sectional rank targets: `groupby('ts')['forward_ret_5d'].rank(pct=True)` normalized to [-1,1]
- All ML training through existing `PurgedKFoldSplitter` — never `sklearn.model_selection.KFold`
- `signals_ml_composite` DB table registered in `SIGNAL_TABLE_MAP` for executor consumption
- SHAP feature selection replacing slow MDA permutation loop for model training feature selection

**Must have — CTF Graduation:**
- Top 10-20 CTF features materialized into `features` table as new columns (Alembic migration first)
- Sequencing enforced: migration to add columns, then refresh to populate data, then registry update
- IC staleness monitor extended to cover promoted CTF features

**Must have — FRED Equity Indices:**
- GCP VM backfill to 2+ years of history for SP500/NASDAQCOM/DJIA before pipeline activation
- Derived features: 1d/5d/20d returns, 20d realized vol, drawdown, MA ratios (50d/200d)
- Rolling BTC-SPX and BTC-NASDAQ correlations in `cross_asset.py`
- Alembic migration for approximately 28 new columns in `fred.fred_macro_features`

**Should have (differentiators):**
- Multi-strategy operator dashboard page (all active strategies, positions, last run status in one view)
- Strategy leaderboard ranked by Monte Carlo-adjusted Sharpe (50th percentile) with PBO scores
- Equity drawdown dimension added to L4 macro regime classifier (SPX < -10% = bear market flag)
- Automated burn-in report appended to dashboard weekly

**Defer to v1.4+:**
- VM-based mass backtest execution on Oracle Singapore VM (build after local multiprocessing is proven)
- Per-asset CTF feature routing (`asset_id` column in `dim_feature_selection`) — high complexity
- Cross-asset CTF composite features (market-wide RSI slope) — depends on 150 HL assets with CTF
- Online learning / real-time model adaptation — daily batch retraining is sufficient
- Live exchange order placement — requires 4+ weeks paper burn-in with parity correlation >= 0.90

**Anti-features (do not build):**
- AMA signals as persistent DB tables before mass backtest validation — premature promotion
- Per-asset interaction terms in cross-sectional LightGBM — catastrophic overfitting at this scale
- Graduating all 131 CTF features simultaneously — near-singular BL covariance matrix
- Real-time equity index feeds — FRED daily closes are sufficient for macro context

---

### Architecture Approach

v1.3.0 architecture is integration, not construction. The `run_daily_refresh.py` pipeline already
has every stage slot defined (sync_vms, bars, emas, amas, macro_features, regimes, features, garch,
signals, signal_validation_gate, ic_staleness_check, calibrate_stops, portfolio, executor,
drift_monitor, pipeline_alerts, stats). The gaps are in the data flowing through existing stages,
not the stage machinery itself.

**New components required (6 total):**

1. `scripts/analysis/run_mass_backtest.py` — parallel orchestrator with resume-safe DB state
   table, `NullPool + maxtasksperchild`, calls bakeoff_orchestrator with `persist_trades=True`
2. `signals/ctf_threshold.py` — generic CTF feature threshold signal (long/short when z-score
   crosses configurable threshold); registered in `signals/registry.py`
3. `signals/ml_composite.py` — loads serialized `DoubleEnsemble` model, writes daily scores to
   `signals_ml_composite` table; runs at inference time during signals stage only
4. `signals_ml_composite` DB table — Alembic migration; schema matches other `signals_*` tables
5. `scripts/analysis/promote_ctf_features.py` — selects top 15 CTF features from
   `dim_ctf_feature_selection`, updates `feature_selection.yaml` and `dim_feature_selection`
6. `scripts/features/refresh_ctf_promoted.py` — queries `ctf` table, upserts values into
   `features` table columns (scoped DELETE + INSERT per batch, following existing pattern)

**Existing components requiring small modifications (8 total):**

| Component | Change |
|-----------|--------|
| `executor/signal_reader.py` | Add `ml_composite` entry to `SIGNAL_TABLE_MAP` |
| `configs/executor_config_seed.yaml` | Add AMA and ML strategy entries |
| `backtests/bakeoff_orchestrator.py` | Add `persist_trades=True` path routing through `vbt_runner.py` |
| `macro/fred_reader.py` | Add 4 equity index series IDs to `SERIES_TO_LOAD` |
| `macro/feature_computer.py` | Add equity index `_RENAME_MAP` entries + derived feature functions |
| `macro/cross_asset.py` | Add BTC-SPX and BTC-NASDAQ rolling 30d correlations |
| `scripts/features/run_all_feature_refreshes.py` | Add `refresh_ctf_promoted` step |
| `configs/feature_selection.yaml` | Add top CTF features after promotion |

**Three critical integration connectors (the "last mile" for each capability area):**
- `dim_executor_config` to `PaperExecutor._load_active_configs()`: one seed run closes this gap
- `feature_selection.yaml` to four consumers (bakeoff, portfolio, IC staleness, regime routing):
  updating the YAML automatically propagates to all four consumers via `parse_active_features()`
- `ctf` table to `features` table: `refresh_ctf_promoted.py` is the missing ETL bridge

**Architecture constraints to enforce:**
- Do NOT create a parallel scheduler or orchestrator — `run_daily_refresh.py` stage slots are the
  correct integration point for all new capabilities
- Do NOT add CTF columns to `_u` tables — promoted CTF features belong in `features` table only
- Do NOT use file-based state for mass backtest — PostgreSQL is the checkpoint store
- Do NOT run `DoubleEnsemble` training in the daily pipeline — training is a weekly offline job;
  only inference (predict from serialized model, write to DB) runs daily

See `.planning/research/ARCHITECTURE.md` for full integration point analysis, component boundary
table, and annotated 6-step build order with day estimates.

---

### Critical Pitfalls

Full pitfall catalog (20 items across 6 categories) is in `.planning/research/PITFALLS.md`. Top 7
for roadmap planning:

1. **`dim_executor_config` empty causes executor to silently succeed with zero fills** — Add a
   pre-flight check that queries `COUNT(*) WHERE is_active=TRUE` and raises a hard error if zero.
   Run `seed_executor_config.py` as the absolute first task of activation. Verify with:
   `SELECT config_name, signal_id, is_active FROM dim_executor_config;`

2. **First executor run replays all historical backlogged signals** — Before activation, mark ALL
   existing rows in `signals_ema_crossover`, `signals_rsi_mean_revert`, and `signals_atr_breakout`
   as `executor_processed_at = now()`. Track the exact activation date and set `paper_start_date`
   to this date consistently in all drift monitor calls.

3. **DSR under-deflation at 460K runs** — `n_trials` in `psr.py` must equal TOTAL parameter
   combinations tested, not just the strategy count. With 460K runs across 99 assets, per-asset
   `n_trials` is approximately 4,600. Verify the formula before scaling. Current code sets
   `dsr = float("nan")` in the PKF phase and computes DSR post-hoc; confirm the post-hoc
   `n_trials` input is correct.

4. **Storage explosion: `strategy_bakeoff_results` JSONB at 460K rows** — Estimated 20-50 GB
   from fold metrics JSONB alone, added to an already 177 GB database. Estimate actual per-row
   storage from 1,000 runs before scaling. Consider storing fold details only for top-N strategies;
   keep aggregate stats for all runs. Stage CTF graduation and bakeoff in separate weeks to avoid
   simultaneous 40-80 GB disk addition.

5. **Windows `multiprocessing.Pool` hang with `maxtasksperchild=1`** — CPython bugs #10332 and
   #38799 confirm pool hang on Windows when workers complete and the handler thread exits before
   all tasks drain. Use `ProcessPoolExecutor` (concurrent.futures) instead of `Pool` for
   `run_mass_backtest.py`. Implement a 10-minute task timeout watchdog. Keep `overwrite=False`
   for restart safety.

6. **Cross-sectional LightGBM with per-asset interaction terms causes catastrophic overfitting**
   — Universal features only for the cross-sectional model. No `asset_id * feature` interactions.
   Set `min_data_in_leaf >= 200` and `num_leaves <= 31`. In-sample Sharpe above 2.0 is a
   diagnostic signal for overfitting; investigate SHAP values for `asset_id` dominance.

7. **CTF feature compute timeout: 131 features likely exceed the 30-minute `TIMEOUT_FEATURES`**
   — Benchmark CTF refresh runtime on 5 assets and extrapolate to 99 before graduating all
   features. Graduate only top 10-20 features in v1.3.0; split into parallel asset batches if
   needed; use incremental watermark refresh, not full rebuild.

---

## Implications for Roadmap

Based on combined research, the natural phase structure follows a strict dependency order. Each
phase closes a specific gap that unblocks the next, and the ordering reflects hard data
dependencies, not convenience groupings.

---

### Phase 1: Executor Activation and Daily Scheduling

**Rationale:** The highest-value, lowest-effort action in v1.3.0. Zero new code required.
Validates the entire end-to-end pipeline (signals to executor to fills to drift) immediately
and starts the burn-in clock. Must come first because burn-in time is the rate-limiting
resource — every day before activation is a day of paper trading data that cannot be recovered.

**Delivers:** First paper fills in `fills` table; `executor_run_log.status = 'success'`;
Windows Task Scheduler running `run_daily_refresh.py --all` daily; `executor_run_log`
monitored for daily gaps.

**Addresses:** OA-TS-1 through OA-TS-6

**Critical pitfall to avoid:** Empty `dim_executor_config` (silent no-op) and historical
backlog replay (contaminated burn-in baseline). Pre-flight check and signal table pruning
are mandatory prerequisites.

**Research flag:** Pure configuration task. No additional research needed.

---

### Phase 2: FRED Macro Expansion

**Rationale:** Self-contained and fully independent of all other v1.3.0 work. Changes touch
only `fred_reader.py`, `feature_computer.py`, `cross_asset.py`, and one Alembic migration.
Delivers immediate value in the next daily refresh cycle. Can overlap with Phase 1 completion
since they touch entirely different files.

**Delivers:** 28 new equity index feature columns in `fred.fred_macro_features`; rolling
BTC-SPX and BTC-NASDAQ correlations in `cross_asset_agg`.

**Addresses:** FE-TS-1 through FE-TS-5

**Critical dependency:** GCP VM must have SP500/NASDAQCOM/DJIA series in `fred.series_values`
with 2+ years of history before activating in the pipeline. Verify first; backfill on the VM
if needed before writing any pipeline code.

**Research flag:** Well-documented FRED API and existing feature compute pattern. No additional
research needed.

---

### Phase 3: CTF Feature Graduation

**Rationale:** Unlocks better Black-Litterman views (CTF features in `signal_scores`) and
feeds CTF signals into the backtest scaling work in Phase 4. The sequencing constraint within
this phase is hard: Alembic migration adds columns BEFORE the refresh script runs, which runs
BEFORE the registry is updated, which runs BEFORE signal generators are tested. Violating this
order causes "column not found" errors in production.

**Delivers:** Top 15 CTF features (IC-IR >= 1.0, pass_rate >= 0.5) materialized in `features`
table; `feature_selection.yaml` updated with CTF entries; IC staleness monitor covers CTF
features; BL portfolio `signal_scores` includes CTF feature values.

**Addresses:** CTF-TS-1 through CTF-TS-4

**Build before:** Backtest scaling and ML signal combination (both consume promoted CTF features)

**Critical pitfall to avoid:** Graduating all 131 features at once (runtime timeout, BL
near-singular covariance). Benchmark on 5 assets before committing to full graduation.

**Research flag:** Incremental CTF refresh pattern for `refresh_ctf_promoted.py` needs design.
The `ctf` table has 73.9M rows; watermark-based refresh must be spelled out before
implementation. Recommend flagging for `/gsd:research-phase`.

---

### Phase 4: Backtest Scaling Infrastructure

**Rationale:** Can start in parallel with Phase 3 since the core orchestrator (state table and
multiprocessing workers) has zero dependency on CTF graduation. CTF threshold signals are added
to the bakeoff in a second pass after Phase 3 completes. Building the infrastructure first
establishes the foundation for validating all strategies including CTF signals before any
paper deployment.

**Delivers:** `run_mass_backtest.py` with resume-safe DB state table; `backtest_trades`
partitioned by `strategy_name`; `mc_sharpe_lo/hi/median` populated for all runs; early
stopping at fold-1 Sharpe < -0.5; initial backfill for 13 existing strategies across 99 assets.

**Addresses:** BS-TS-1 through BS-TS-6

**Critical pitfall to avoid:** JSONB storage explosion (estimate from 1,000 runs first) and
Windows `Pool` hang (use `ProcessPoolExecutor` with timeout watchdog). Do not run the 460K
bakeoff the same week as CTF graduation — stage disk operations separately.

**Research flag:** Two design decisions need resolution before coding: (a) JSONB vs separate
`strategy_bakeoff_fold_details` table for storage architecture; (b) `ProcessPoolExecutor` vs
`multiprocessing.Pool` behavior on Windows 3.12 — test with a small batch before committing.
Recommend flagging for `/gsd:research-phase`.

---

### Phase 5: ML Signal Combination

**Rationale:** Last because it depends on CTF features being in the `features` table (Phase 3)
for model training inputs, and on backtest infrastructure (Phase 4) to validate ML signals
before paper deployment. `DoubleEnsemble` training (hours-long, weekly offline job) must be
separated from daily inference (milliseconds, runs during signals stage). ML signals must be
backtested through `run_mass_backtest.py` and pass the same gates as EMA strategies before
being added to executor config.

**Delivers:** `signals_ml_composite` table populated daily by `signals/ml_composite.py`; SHAP
feature importance for model training selection; XGBoost meta-labeler for EMA crossover signal
filtering; `ml_composite` registered in `SIGNAL_TABLE_MAP`.

**Addresses:** ML-TS-1 through ML-TS-5

**Critical pitfall to avoid:** In-sample overfitting from per-asset interactions; z-score
leakage across fold boundaries. Both are silent and inflate Sharpe to unrealistic levels.

**Research flag:** Model serialization and loading pattern for `DoubleEnsemble` (pickle vs
joblib vs DB artifact store) is undefined. The storage location and versioning strategy must
be decided before the signals stage can load the model. Recommend flagging for `/gsd:research-phase`.

---

### Phase 6: Tech Debt Cleanup

**Rationale:** Final phase with no runtime impact. Closes documentation gaps identified in
the v1.2.0 milestone audit. Decoupled from all other phases.

**Delivers:** Phase 82 `VERIFICATION.md` created from existing summaries; Phase 92
`VERIFICATION.md` updated to reflect closed gaps; `blend_vol_simple()` marked internal in
`garch_blend.py`.

**Research flag:** No research needed — documentation only.

---

### Phase Ordering Rationale

- **Phase 1 must be first:** Burn-in time is the rate-limiting resource. Every day before
  activation is a day of paper trading data that cannot be recovered. Paper fills also give
  the drift monitor real data to compare against.
- **Phase 2 can overlap with Phase 1 completion:** Entirely different files, no conflicts.
  Complete Phase 1 configuration before starting Phase 2 code changes.
- **Phase 3 before Phase 5 (hard dependency):** ML models are trained on the `features` table;
  CTF columns must exist there before training begins.
- **Phase 4 parallel with Phase 3:** The mass backtest orchestrator core has no CTF dependency.
  CTF threshold signals are added to the bakeoff in a second pass after Phase 3 completes.
- **Phase 4 before Phase 5 (validation gate):** ML signals must be backtested before executor
  deployment. Without Phase 4 infrastructure, ML signal quality cannot be verified.
- **Disk staging rule:** Do not run Phase 4 (460K bakeoff) the same week as Phase 3 CTF
  graduation. Simultaneous disk additions of 40-80 GB risk pressure on the 177 GB database.

---

### Research Flags

**Phases needing deeper research during planning (recommend `/gsd:research-phase`):**

- **Phase 3 (CTF Graduation):** Incremental CTF refresh pattern. The `ctf` table has 73.9M rows;
  naive full-rebuild on daily refresh is too slow. The watermark-based incremental write pattern
  (matching existing feature refresher) needs design before `refresh_ctf_promoted.py` is coded.
- **Phase 4 (Backtest Scaling):** Two architecture decisions — (a) JSONB vs dedicated
  `strategy_bakeoff_fold_details` table for storage; (b) `ProcessPoolExecutor` vs `Pool` on
  Windows 3.12. Both should be tested with 1,000 runs before the full 460K run is attempted.
- **Phase 5 (ML Signal Combination):** `DoubleEnsemble` model serialization and daily loading
  pattern. The trained model must be accessible to the signals stage at daily refresh time.
  The storage location, file format, and version management strategy are currently undefined.

**Phases with standard patterns (skip `/gsd:research-phase`):**

- **Phase 1 (Executor Activation):** Pure configuration. Seed script exists; Task Scheduler
  setup is documented. No research needed.
- **Phase 2 (FRED Expansion):** Follows the exact existing FRED feature compute pattern.
  Series IDs verified on FRED. Derived feature pattern (pct_change, rolling std) is identical
  to existing FRED features.
- **Phase 6 (Tech Debt):** Documentation updates only.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library versions verified from PyPI (shap v0.51.0, xgboost v3.2.0 released dates confirmed). Existing stack confirmed from `.venv` and `.venv311` pip list. FRED series IDs verified at fred.stlouisfed.org including Russell 2000 removal confirmed. |
| Features | HIGH | Primary source is direct codebase analysis of executor, signal reader, bakeoff orchestrator, ML modules, and CTF pipeline. Feature trees grounded in actual code paths. Web research used only to confirm standard industry conventions (cross-sectional ranking, MC bootstrap, crypto-equity correlation patterns). |
| Architecture | HIGH | All integration points confirmed from source code with line number references. Component boundaries verified from actual imports and DB schema. Build order is dependency-driven from real code dependencies, not estimated. |
| Pitfalls | HIGH | Critical pitfalls backed by direct code inspection (executor silent no-op, backlog replay, DSR n_trials bug in bakeoff_orchestrator). Windows multiprocessing hang backed by official CPython bug reports (#10332, #38799). DSR/PBO pitfalls backed by Bailey and Lopez de Prado primary academic papers directly implemented in psr.py. |

**Overall confidence:** HIGH

The research is unusually high-confidence because the primary source for all four dimensions is
the codebase itself, not external documentation. The platform is mature (290+ scripts, 90+ tables,
~115K lines) and the v1.3.0 scope is well-defined by existing todos and milestone audit artifacts.
The main uncertainties are estimations (CTF refresh runtime, 460K bakeoff wall-clock time) that
require small-batch benchmarking before full execution.

---

### Gaps to Address

- **Mass backtest runtime estimate:** 460K runs at approximately 30 seconds each gives roughly
  159 CPU-days at single-process. With 8 workers, approximately 20 days wall time. This estimate
  needs validation against actual `bakeoff_orchestrator` timing. Run 1,000 combinations first
  and measure before committing to the full run design.
- **CTF refresh runtime:** 131 features across 99 assets at unknown per-feature compute time.
  Benchmark on 5 assets before designing the incremental refresh pattern. If per-asset time
  exceeds 5 minutes, incremental watermark refresh is mandatory, not optional.
- **GCP VM equity series status:** SP500/NASDAQCOM/DJIA must be confirmed present in
  `fred.series_values` with 2+ year history before Phase 2 begins. This is a data availability
  check, not a code question, and should be the first action of Phase 2.
- **`dim_signals` signal name verification:** Phase 1 depends on `ema_17_77_long` and
  `ema_21_50_long` existing in `dim_signals`. If signal refresh never registered these names,
  `seed_executor_config.py` will skip them with a WARNING (not an error). Verify:
  `SELECT signal_name FROM dim_signals WHERE signal_name LIKE 'ema_%';`
- **DoubleEnsemble training data sufficiency:** The cross-sectional model needs approximately
  160K observations (99 assets times 1,800 bars times 0.9 train ratio). Confirm this is
  sufficient for `LGBMRanker` with `num_leaves=31` before committing to the cross-asset vs
  per-asset architecture decision.

---

## Sources

### Primary (HIGH confidence — direct codebase inspection)

- `src/ta_lab2/executor/paper_executor.py` — execution flow, dim_executor_config dependency
- `src/ta_lab2/executor/signal_reader.py` — SIGNAL_TABLE_MAP, watermark pattern, stale guard first-run bypass on line 127
- `src/ta_lab2/scripts/run_daily_refresh.py` — STAGE_ORDER, TIMEOUT_FEATURES=1800, all stage subprocess wrappers
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` — dsr=float("nan") in PKF phase, parse_active_features()
- `src/ta_lab2/backtests/psr.py` — DSR implementation, n_trials parameter
- `src/ta_lab2/ml/double_ensemble.py` — recency weighting, sliding window, _DEFAULT_PARAMS num_leaves=20
- `src/ta_lab2/signals/ama_composite.py` — AMA pre-computation requirement, bakeoff-only design confirmed
- `src/ta_lab2/analysis/monte_carlo.py` — monte_carlo_trades() confirmed implemented; confirmed never called in batch
- `src/ta_lab2/macro/fred_reader.py` — SERIES_TO_LOAD (18 series), forward_fill.py equity series pre-wired lines 71-74
- `src/ta_lab2/macro/cross_asset.py` — reads fred.fred_macro_features; existing correlation infrastructure
- `src/ta_lab2/portfolio/black_litterman.py` — signal_scores DataFrame interface
- `configs/feature_selection.yaml` — 20 active AMA features; CTF absent confirmed
- `.planning/todos/pending/2026-03-28-ctf-production-integration.md`
- `.planning/todos/pending/2026-03-29-massive-backtest-monte-carlo-expansion.md`
- `.planning/todos/pending/2026-03-28-fred-equity-indices-macro-pipeline.md`
- `.memory/MEMORY.md` — NullPool + maxtasksperchild Windows pattern, DB size 177 GB

### Primary (HIGH confidence — verified external sources)

- [shap on PyPI](https://pypi.org/project/shap/) — v0.51.0 released 2026-03-04, pandas 3.0 compatibility confirmed
- [xgboost on PyPI](https://pypi.org/project/xgboost/) — v3.2.0 released 2026-02-10, Windows wheels confirmed
- [LightGBM LGBMRanker docs](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRanker.html) — stable in 4.6.0
- [FRED SP500 series](https://fred.stlouisfed.org/series/SP500) — 10-year daily window, licensing limitation confirmed
- [FRED NASDAQCOM](https://fred.stlouisfed.org/series/NASDAQCOM) — full history from 1971-02-05
- [FRED Russell 2000 removal](https://fred.stlouisfed.org/series/RU2000VTR) — confirmed removed October 2019
- [CPython issue #10332](https://bugs.python.org/issue10332) — maxtasksperchild Pool hang on Windows, confirmed
- [CPython issue #38799](https://bugs.python.org/issue38799) — race condition in Pool with maxtasksperchild=1
- [Bailey and Lopez de Prado: The Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) — n_trials formula, directly implemented in psr.py
- [Bailey et al: Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) — CPCV/PBO, basis for cv.py

### Secondary (MEDIUM confidence — practitioner literature)

- [Balaena Quant Insights: CTA backtesting in crypto](https://medium.com/balaena-quant-insights/best-backtesting-practices-for-cta-trading-in-cryptocurrency-e79677cb6375) — bull run contamination in crypto backtest data
- [LightGBM Parameters Tuning](https://lightgbm.readthedocs.io/en/latest/Parameters-Tuning.html) — min_data_in_leaf >= 200 for cross-sectional generalization

---
*Research completed: 2026-03-29*
*Ready for roadmap: yes*
