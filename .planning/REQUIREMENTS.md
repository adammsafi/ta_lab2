# Requirements: ta_lab2 v1.3.0

**Defined:** 2026-03-29
**Core Value:** Make the built infrastructure actually run — activate paper trading, scale backtests, graduate research features, and add ML signal combination.

## v1.3.0 Requirements

### Operational Activation

- [ ] **OPS-01**: `dim_executor_config` seeded with 3+ active strategies from bakeoff winners, `cadence_hours` configured (36h to buffer late runs)
- [ ] **OPS-02**: `run_daily_refresh.py --all` includes signal generation step that populates `signals_*` tables; historical signals marked as processed to prevent replay
- [ ] **OPS-03**: Paper executor runs daily via Windows Task Scheduler, produces fills in `orders`/`fills` tables, with stale-signal guard active
- [ ] **OPS-04**: Black-Litterman portfolio construction uses real IC-weighted signal scores (not uniform 1.0), generates position recommendations in `portfolio_allocations`
- [ ] **OPS-05**: Backtest-to-live parity tracked — live Sharpe / backtest Sharpe ratio logged per strategy
- [ ] **OPS-06**: PnL attribution report separates alpha component from long-crypto bias (beta-adjusted returns)

### Backtest Expansion

- [x] **BT-01**: Resume-safe mass backtest orchestrator (`run_mass_backtest.py`) with state table tracking `(strategy, asset, params_hash, tf, cost)` completion status
- [x] **BT-02**: `backtest_trades` table partitioned by strategy_name before scaling (pre-emptive for 20-40M rows)
- [x] **BT-03**: Trade-level results populated for all existing bakeoff strategies (13 strategies x top assets x 16 costs = ~113K runs) in `backtest_runs`/`backtest_trades`
- [x] **BT-04**: `backtest_metrics.mc_sharpe_lo/hi/median` populated via `monte_carlo_trades()` for every run (1,000 bootstrap samples each)
- [x] **BT-05**: CTF threshold signals registered in `signals/registry.py`, backtested across top IC-scoring CTF features (~230K runs)
- [x] **BT-06**: Expanded parameter grids for 6 core signals (full factorial EMA periods, RSI windows, ATR lookbacks)
- [x] **BT-07**: Strategy leaderboard dashboard page with MC confidence bands, feature-to-signal lineage, and PBO heatmap

### CTF Research Expansion

- [x] **CTF-01**: Top 15-20 CTF features materialized as columns in `features` table via ETL bridge (`refresh_ctf_promoted.py`), registered in `feature_selection.yaml`
- [x] **CTF-02**: Asset-specific feature selection tier in `dim_feature_selection` for features with strong per-asset IC but failing cross-asset consensus
- [x] **CTF-03**: Cross-asset CTF composite signals computed (market-wide sentiment, relative-value, leader-follower aggregates)
- [x] **CTF-04**: Lead-lag IC matrix analyzing whether Asset A's CTF features predict Asset B's returns (Granger causality via CTF)

### Macro Expansion

- [x] **MACRO-01**: SP500, NASDAQ Composite, and DJIA added to FRED macro feature layer (`fred_reader.py` SERIES_TO_LOAD) with derived features (returns, vol, drawdown, MA ratios)
- [x] **MACRO-02**: Rolling BTC-SPX and BTC-NASDAQ correlation computed in `cross_asset.py`, equity vol regime vs VIX cross-validation, risk-on/risk-off divergence signals

### ML Signal Combination

- [ ] **ML-01**: LGBMRanker cross-sectional rank predictor trained on CTF+AMA features, predicting relative asset performance, with purged CV validation
- [ ] **ML-02**: SHAP TreeExplainer interaction analysis identifying top feature pairs, results feeding into feature selection refinement
- [ ] **ML-03**: XGBoost meta-label confidence filter trained on `triple_barrier_labels`, filtering low-confidence trades before executor with configurable threshold

### Pipeline Operations Dashboard

- [ ] **DASH-01**: `pipeline_stage_log` table with per-stage start/end/status/rows written during every `--all` run
- [ ] **DASH-02**: Streamlit active run monitor page with real-time stage progress bars, auto-refresh 90s
- [ ] **DASH-03**: Run history panel showing last 10 runs with per-stage timing breakdown
- [ ] **DASH-04**: Trigger panel with "Run Full Refresh", "Run From Stage", and quick-action buttons
- [ ] **DASH-05**: Kill button that stops pipeline between stages via file-based kill switch

### Pipeline Batch Performance

- [ ] **PERF-01**: EMA returns batch — replace 2M per-key queries with per-ID batch SQL using PARTITION BY (tf, period, venue_id)
- [ ] **PERF-02**: EMA fast-path — use recursive `ema_new = close * alpha + ema_prev * (1-alpha)` for recent watermarks instead of full recompute
- [ ] **PERF-03**: AMA returns batch — per-ID batch SQL instead of per-(alignment_source, id) loop
- [ ] **PERF-04**: Bar returns batch — per-ID batch SQL instead of per-(id, tf, venue) loop
- [ ] **PERF-05**: Full incremental `--all` pipeline completes in < 2 hours (currently 5-6 hours)

### Feature Skip-Unchanged

- [ ] **FEAT-01**: `feature_refresh_state` table created (alembic migration) with PK (id, tf, alignment_source)
- [ ] **FEAT-02**: Feature refresh skips assets with no new bar data (daily refresh processes ~10 assets, not 492)
- [ ] **FEAT-03**: `--full-rebuild` bypasses skip logic; log shows "Skipping N unchanged assets"

### Feature Parallel Sub-Phases

- [ ] **FEAT-04**: Independent feature sub-phases grouped into parallel waves (vol+ta+cycle+micro in Wave 1)
- [ ] **FEAT-05**: Total feature full-recompute time < 70 min (currently ~100 min)

### Feature Polars Migration

- [ ] **FEAT-06**: All 8 feature sub-phases have polars implementations with `--use-polars` / `--use-pandas` flags
- [ ] **FEAT-07**: IC-IR regression < 1% for test assets (id=1, 1027, 5426) on every sub-phase migration
- [ ] **FEAT-08**: Zero signal flips on test assets after full migration (signal count and direction match)
- [ ] **FEAT-09**: Backtest Sharpe regression < 5% for bakeoff strategies after migration
- [ ] **FEAT-10**: Feature full-recompute time < 30 min with polars

### Tech Debt Cleanup

- [x] **DEBT-01**: `blend_vol_simple()` orphaned export in `garch_blend.py` removed or wired to caller
- [x] **DEBT-02**: Phase 82 `VERIFICATION.md` created from existing 6 summaries
- [x] **DEBT-03**: Phase 92 `VERIFICATION.md` updated to reflect manually-closed gaps
- [x] **DEBT-04**: `dim_ctf_feature_selection` downstream consumer status documented (by design — research table, consumers added via CTF-01)

## Future Requirements (v1.4.0+)

### Hardening (after paper trading proves positive PnL)
- Tighten DD gates from live experience
- Cost-aware strategy routing (HL perps cheaper than Kraken spot)
- Signal combination / ensemble weighting from live IC
- Transformer-based temporal modeling (requires GPU budget)

### Scale (after 3-6 months paper trading data)
- Additional data sources, more strategies
- Equities expansion (only with proven crypto alpha)
- Order flow / L2 book data
- Funding rate arbitrage (different strategy class)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Live trading with real capital | Paper trading only until live Sharpe within 70% of backtest |
| Russell 2000 via FRED | Removed from FRED October 2019; supplement via yfinance if needed later |
| Transformer/deep learning models | Deferred until P1-P3 ML proven profitable + GPU budget |
| Order flow / L2 book data | Premature per strategic review — paper trading not running yet |
| Funding rate arbitrage | Different strategy class (delta-neutral), doesn't use existing signal infra |
| Cloud deployment | Local/VM only for v1 |
| Real-time / streaming execution | Daily-batch system; intraday deferred |
| APScheduler v4.0 | Alpha-only; Windows Task Scheduler + `schedule 1.2.2` sufficient |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| OPS-01 | Phase 96 | Complete |
| OPS-02 | Phase 96 | Complete |
| OPS-03 | Phase 96 | Complete |
| OPS-04 | Phase 96 | Complete |
| OPS-05 | Phase 96 | Complete |
| OPS-06 | Phase 96 | Complete |
| BT-01 | Phase 99 | Complete |
| BT-02 | Phase 99 | Complete |
| BT-03 | Phase 99 | Complete |
| BT-04 | Phase 99 | Complete |
| BT-05 | Phase 99 | Complete |
| BT-06 | Phase 99 | Complete |
| BT-07 | Phase 99 | Complete |
| CTF-01 | Phase 98 | Complete |
| CTF-02 | Phase 98 | Complete |
| CTF-03 | Phase 98 | Complete |
| CTF-04 | Phase 98 | Complete |
| MACRO-01 | Phase 97 | Complete |
| MACRO-02 | Phase 97 | Complete |
| ML-01 | Phase 100 | Complete |
| ML-02 | Phase 100 | Complete |
| ML-03 | Phase 100 | Complete |
| DEBT-01 | Phase 101 | Complete |
| DEBT-02 | Phase 101 | Complete |
| DEBT-03 | Phase 101 | Complete |
| DEBT-04 | Phase 101 | Complete |
| DASH-01 | Phase 107 | Complete |
| DASH-02 | Phase 107 | Complete |
| DASH-03 | Phase 107 | Complete |
| DASH-04 | Phase 107 | Complete |
| DASH-05 | Phase 107 | Complete |
| PERF-01 | Phase 108 | Complete |
| PERF-02 | Phase 108 | Complete |
| PERF-03 | Phase 108 | Complete |
| PERF-04 | Phase 108 | Complete |
| PERF-05 | Phase 108 | Complete |
| FEAT-01 | Phase 109 | Pending |
| FEAT-02 | Phase 109 | Pending |
| FEAT-03 | Phase 109 | Pending |
| FEAT-04 | Phase 110 | Pending |
| FEAT-05 | Phase 110 | Pending |
| FEAT-06 | Phase 111 | Pending |
| FEAT-07 | Phase 111 | Pending |
| FEAT-08 | Phase 111 | Pending |
| FEAT-09 | Phase 111 | Pending |
| FEAT-10 | Phase 111 | Pending |

**Coverage:**
- v1.3.0 requirements: 46 total (26 original + 5 DASH + 5 PERF + 10 FEAT)
- Mapped to phases: 46
- Unmapped: 0

---
*Requirements defined: 2026-03-29*
*Last updated: 2026-03-29 — traceability mapped after roadmap creation*
