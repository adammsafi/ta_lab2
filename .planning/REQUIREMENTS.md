# Requirements: v0.9.0 Research & Experimentation

**Defined:** 2026-02-23
**Core Value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Milestone Goal:** Enable a full research cycle — compute new indicators, evaluate with IC, stress test with CV, visualize results in an interactive dashboard, and build a rolling descriptive statistics + cross-asset correlation layer

---

## v0.9.0 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Adaptive Moving Averages

- [ ] **AMA-01**: KAMA (Kaufman Adaptive MA) computed correctly with Efficiency Ratio, stored in `cmc_ama_multi_tf` with `(id, ts, tf, indicator, params_hash)` PK, multi-TF across all timeframes
- [ ] **AMA-02**: DEMA (Double EMA) and TEMA (Triple EMA) computed as compositional EMAs, same table and PK pattern as KAMA
- [ ] **AMA-03**: HMA (Hull MA) computed using proper WMA (not EWM), same table and PK pattern
- [ ] **AMA-04**: All AMAs have derivative columns (d1, d2, d1_roll, d2_roll), min-obs warmup guard, and _u unified table sync
- [ ] **AMA-05**: Z-scores computed on AMA returns (_zscore_30, _zscore_90, _zscore_365) via existing refresh_returns_zscore.py pattern
- [ ] **AMA-06**: KAMA Efficiency Ratio stored as standalone column — usable as an IC candidate independently
- [ ] **AMA-07**: AMAs wired into `run_daily_refresh.py` as a stage (parallel to or after EMAs)

### Information Coefficient Evaluation

- [x] **IC-01**: Spearman (rank) IC computed per feature, per forward-return horizon [1, 2, 3, 5, 10, 20, 60 bars]
- [x] **IC-02**: Rolling IC time series (63-bar window) with IC-IR (mean IC / std IC) summary statistic
- [x] **IC-03**: IC decay table showing predictive power decay across horizons — critical for setting holding period
- [x] **IC-04**: `train_start` and `train_end` as required parameters on all IC functions — prevents future-information leakage into feature selection
- [x] **IC-05**: IC by regime — splits IC computation by regime label (trend_state, vol_state) from cmc_regimes
- [x] **IC-06**: IC significance testing — t-stat and p-value on rolling IC to flag statistically non-zero signals
- [x] **IC-07**: Feature turnover — rank autocorrelation measuring signal stability across time
- [x] **IC-08**: `cmc_ic_results` DB table for persisting IC evaluation results (on-demand, not daily refresh)

### Probabilistic Sharpe Ratio

- [x] **PSR-01**: Alembic migration renaming existing `psr` column to `psr_legacy` for all pre-migration rows in `cmc_backtest_metrics`
- [x] **PSR-02**: Full Lopez de Prado PSR formula replacing `psr_placeholder()` — uses sample size n, skewness, kurtosis via scipy
- [x] **PSR-03**: Minimum sample guard (return NaN when n < 30, warn when n < 100) and configurable benchmark SR* parameter
- [x] **PSR-04**: DSR (Deflated Sharpe Ratio) for multiple-testing correction — deflates best-of-N Sharpe from parameter sweeps
- [x] **PSR-05**: MinTRL (Minimum Track Record Length) — inverse of PSR, reports how many bars needed to trust a given Sharpe estimate

### Cross-Validation

- [x] **CV-01**: `PurgedKFoldSplitter` class with `t1_series` (label end timestamps) as required input, compatible with sklearn `BaseCrossValidator`
- [x] **CV-02**: Embargo gap parameterized by label duration in bars, with post-construction fold validation assertions
- [x] **CV-03**: CPCV (Combinatorial Purged Cross-Validation) — enables PBO (Probability of Backtest Overfitting) analysis

### Feature Experimentation Framework

- [ ] **FEAT-01**: YAML-based feature registry with lifecycle states: experimental / promoted / deprecated
- [ ] **FEAT-02**: Compute experimental features on demand from existing base data — no DB persistence until promotion
- [ ] **FEAT-03**: `ExperimentRunner` wiring IC evaluation for systematic feature scoring with results persisted to `cmc_feature_experiments`
- [ ] **FEAT-04**: Benjamini-Hochberg correction as hard gate in promotion logic — prevents noise features from being promoted
- [ ] **FEAT-05**: `dim_feature_registry` and `cmc_feature_experiments` tables via Alembic migration

### Streamlit Dashboard

- [ ] **DASH-01**: Pipeline Monitor (Mode B) — run status, data freshness, stats runner PASS/FAIL, alert history from existing tables
- [ ] **DASH-02**: Research Explorer (Mode A) — IC score table, equity curves, regime timeline, feature comparison
- [ ] **DASH-03**: All DB queries wrapped in `@st.cache_data(ttl=300)` with NullPool engine — no query hammering
- [ ] **DASH-04**: Windows-compatible config (`.streamlit/config.toml` with `fileWatcherType = "poll"`)

### Jupyter Notebooks

- [ ] **NOTE-01**: 3-5 focused notebooks covering IC evaluation, AMA exploration, purged K-fold demo, feature experimentation, regime overlay backtest
- [ ] **NOTE-02**: Each notebook passes "Restart and Run All" cleanly, parameterized with ASSET_ID / TF / START_DATE at top
- [ ] **NOTE-03**: Polished enough to share — clear narrative, good visuals, no raw cell output dumps

### Asset Descriptive Statistics

- [ ] **DESC-01**: Rolling mean return and std dev per asset/TF across trailing windows (30, 60, 90, 252 bars), stored as full time series in `cmc_asset_stats` with PK `(id, ts, tf)`
- [ ] **DESC-02**: Rolling Sharpe ratio, skewness (scipy), and kurtosis (scipy) per asset/TF/window stored alongside mean and std dev
- [ ] **DESC-03**: Rolling max drawdown per window — worst peak-to-trough decline within the trailing window ending at each bar
- [ ] **DESC-04**: All stats tracked as time series (one row per bar per asset/TF), not just latest snapshot — enables regime-conditioned analysis and historical comparison
- [ ] **DESC-05**: `cmc_asset_stats` table created via Alembic migration, wired into `run_daily_refresh.py --all` with `--desc-stats` standalone flag

### Cross-Asset Correlation

- [ ] **CORR-01**: Pairwise rolling Pearson return correlation between all asset pairs per TF, across trailing windows (60, 90, 252 bars)
- [ ] **CORR-02**: Correlation tracked over time as rolling time series with PK `(id_a, id_b, ts, tf, window)` — enables detecting correlation regime shifts (e.g., risk-off spikes)
- [ ] **CORR-03**: `cmc_cross_asset_corr` table created via Alembic migration, wired into `run_daily_refresh.py --all` with `--desc-stats` flag

## v1.0+ Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Analytics

- **ADV-01**: Quantile returns analysis — cross-sectional asset ranking (requires universe-level architecture change)
- **ADV-02**: KAMA crossover signal generator — compute and evaluate AMA values first; add signal after IC validates them
- **ADV-03**: PBO (Probability of Backtest Overfitting) via CPCV — CPCV ships in v0.9.0; PBO analysis layer is separate
- **ADV-04**: Automated Alembic migration on feature promotion — build registry first, promotion path second

### Infrastructure

- **INFR-01**: mypy strict blocking — requires annotating enough of the library layer
- **INFR-02**: Mike-based versioned docs with gh-pages — defer until external consumers exist
- **INFR-03**: Calendar alignment variants for AMAs — build multi_tf first, add calendar variants if IC shows value

## Out of Scope

| Feature | Reason |
|---------|--------|
| TA-Lib for adaptive MAs | Requires C binary install on Windows, breaks CI reproducibility |
| mlfinlab for purged CV | Discontinued on PyPI; known bug in PurgedKFold (issue #295) |
| alphalens-reloaded for IC | Adds seaborn + statsmodels as hard deps for 80 lines of scipy math |
| skfolio for CPCV | Pulls cvxpy-base + clarabel solver; one class not worth the dep weight |
| Real-time streaming dashboard | v0.9.0 is research/batch; live streaming is a different architecture |
| Cross-sectional IC (quantile analysis) | Platform is per-asset time series; cross-asset ranking requires v1.0+ architecture |
| AMA signal generators | Compute first, evaluate with IC, then consider signals in v1.0+ |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| AMA-01 | Phase 35 | Complete |
| AMA-02 | Phase 35 | Complete |
| AMA-03 | Phase 35 | Complete |
| AMA-04 | Phase 35 | Complete |
| AMA-05 | Phase 35 | Complete |
| AMA-06 | Phase 35 | Complete |
| AMA-07 | Phase 35 | Complete |
| IC-01 | Phase 37 | Complete |
| IC-02 | Phase 37 | Complete |
| IC-03 | Phase 37 | Complete |
| IC-04 | Phase 37 | Complete |
| IC-05 | Phase 37 | Complete |
| IC-06 | Phase 37 | Complete |
| IC-07 | Phase 37 | Complete |
| IC-08 | Phase 37 | Complete |
| PSR-01 | Phase 36 | Complete |
| PSR-02 | Phase 36 | Complete |
| PSR-03 | Phase 36 | Complete |
| PSR-04 | Phase 36 | Complete |
| PSR-05 | Phase 36 | Complete |
| CV-01 | Phase 36 | Complete |
| CV-02 | Phase 36 | Complete |
| CV-03 | Phase 36 | Complete |
| FEAT-01 | Phase 38 | Pending |
| FEAT-02 | Phase 38 | Pending |
| FEAT-03 | Phase 38 | Pending |
| FEAT-04 | Phase 38 | Pending |
| FEAT-05 | Phase 38 | Pending |
| DASH-01 | Phase 39 | Pending |
| DASH-02 | Phase 39 | Pending |
| DASH-03 | Phase 39 | Pending |
| DASH-04 | Phase 39 | Pending |
| NOTE-01 | Phase 40 | Pending |
| NOTE-02 | Phase 40 | Pending |
| NOTE-03 | Phase 40 | Pending |
| DESC-01 | Phase 41 | Pending |
| DESC-02 | Phase 41 | Pending |
| DESC-03 | Phase 41 | Pending |
| DESC-04 | Phase 41 | Pending |
| DESC-05 | Phase 41 | Pending |
| CORR-01 | Phase 41 | Pending |
| CORR-02 | Phase 41 | Pending |
| CORR-03 | Phase 41 | Pending |

**Coverage:**
- v0.9.0 requirements: 43 total
- Mapped to phases: 43/43
- Unmapped: 0

---
*Requirements defined: 2026-02-23*
*Last updated: 2026-02-23 — IC-01..08 marked Complete (Phase 37 verified)*
