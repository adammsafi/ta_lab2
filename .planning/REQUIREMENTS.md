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

- [ ] **BT-01**: Resume-safe mass backtest orchestrator (`run_mass_backtest.py`) with state table tracking `(strategy, asset, params_hash, tf, cost)` completion status
- [ ] **BT-02**: `backtest_trades` table partitioned by strategy_name before scaling (pre-emptive for 20-40M rows)
- [ ] **BT-03**: Trade-level results populated for all existing bakeoff strategies (13 strategies x top assets x 16 costs = ~113K runs) in `backtest_runs`/`backtest_trades`
- [ ] **BT-04**: `backtest_metrics.mc_sharpe_lo/hi/median` populated via `monte_carlo_trades()` for every run (1,000 bootstrap samples each)
- [ ] **BT-05**: CTF threshold signals registered in `signals/registry.py`, backtested across top IC-scoring CTF features (~230K runs)
- [ ] **BT-06**: Expanded parameter grids for 6 core signals (full factorial EMA periods, RSI windows, ATR lookbacks)
- [ ] **BT-07**: Strategy leaderboard dashboard page with MC confidence bands, feature-to-signal lineage, and PBO heatmap

### CTF Research Expansion

- [ ] **CTF-01**: Top 15-20 CTF features materialized as columns in `features` table via ETL bridge (`refresh_ctf_promoted.py`), registered in `feature_selection.yaml`
- [ ] **CTF-02**: Asset-specific feature selection tier in `dim_feature_selection` for features with strong per-asset IC but failing cross-asset consensus
- [ ] **CTF-03**: Cross-asset CTF composite signals computed (market-wide sentiment, relative-value, leader-follower aggregates)
- [ ] **CTF-04**: Lead-lag IC matrix analyzing whether Asset A's CTF features predict Asset B's returns (Granger causality via CTF)

### Macro Expansion

- [ ] **MACRO-01**: SP500, NASDAQ Composite, and DJIA added to FRED macro feature layer (`fred_reader.py` SERIES_TO_LOAD) with derived features (returns, vol, drawdown, MA ratios)
- [ ] **MACRO-02**: Rolling BTC-SPX and BTC-NASDAQ correlation computed in `cross_asset.py`, equity vol regime vs VIX cross-validation, risk-on/risk-off divergence signals

### ML Signal Combination

- [ ] **ML-01**: LGBMRanker cross-sectional rank predictor trained on CTF+AMA features, predicting relative asset performance, with purged CV validation
- [ ] **ML-02**: SHAP TreeExplainer interaction analysis identifying top feature pairs, results feeding into feature selection refinement
- [ ] **ML-03**: XGBoost meta-label confidence filter trained on `triple_barrier_labels`, filtering low-confidence trades before executor with configurable threshold

### Tech Debt Cleanup

- [ ] **DEBT-01**: `blend_vol_simple()` orphaned export in `garch_blend.py` removed or wired to caller
- [ ] **DEBT-02**: Phase 82 `VERIFICATION.md` created from existing 6 summaries
- [ ] **DEBT-03**: Phase 92 `VERIFICATION.md` updated to reflect manually-closed gaps
- [ ] **DEBT-04**: `dim_ctf_feature_selection` downstream consumer status documented (by design — research table, consumers added via CTF-01)

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
| OPS-01 | — | Pending |
| OPS-02 | — | Pending |
| OPS-03 | — | Pending |
| OPS-04 | — | Pending |
| OPS-05 | — | Pending |
| OPS-06 | — | Pending |
| BT-01 | — | Pending |
| BT-02 | — | Pending |
| BT-03 | — | Pending |
| BT-04 | — | Pending |
| BT-05 | — | Pending |
| BT-06 | — | Pending |
| BT-07 | — | Pending |
| CTF-01 | — | Pending |
| CTF-02 | — | Pending |
| CTF-03 | — | Pending |
| CTF-04 | — | Pending |
| MACRO-01 | — | Pending |
| MACRO-02 | — | Pending |
| ML-01 | — | Pending |
| ML-02 | — | Pending |
| ML-03 | — | Pending |
| DEBT-01 | — | Pending |
| DEBT-02 | — | Pending |
| DEBT-03 | — | Pending |
| DEBT-04 | — | Pending |

**Coverage:**
- v1.3.0 requirements: 26 total
- Mapped to phases: 0
- Unmapped: 26 (pending roadmap creation)

---
*Requirements defined: 2026-03-29*
*Last updated: 2026-03-29 after initial definition*
