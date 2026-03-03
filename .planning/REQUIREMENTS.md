# Requirements: v1.0.1 Macro Regime Infrastructure

**Defined:** 2026-03-02
**Core Value:** Wire FRED macro data into the regime/risk pipeline so trading decisions are conditioned on macroeconomic state, not just per-asset price action.

## v1.0.1 Requirements

### FRED Data Pipeline (FRED)

- [ ] **FRED-01**: `fred_macro_features` table exists in marketdata with PK (date), storing daily-aligned macro values for all 39 FRED series plus derived series
- [ ] **FRED-02**: Mixed-frequency series (monthly, weekly) are forward-filled to daily cadence with `source_freq` provenance column and `limit` guards (45d monthly, 10d weekly)
- [ ] **FRED-03**: Net liquidity proxy computed daily as `WALCL - WTREGEN - RRPONTSYD` with weekly inputs forward-filled; WTREGEN (TGA) added to VM collection if not present
- [ ] **FRED-04**: Rate spread features computed: `US_JP_RATE_SPREAD` (DFF - ffill(IRSTCI01JPM156N)), `US_ECB_RATE_SPREAD` (DFF - ECBDFR), `US_JP_10Y_SPREAD` (DGS10 - ffill(IRLTLT01JPM156N))
- [ ] **FRED-05**: Yield curve features: `T10Y2Y` level stored directly, `YC_SLOPE_CHANGE_5D` computed as 5-day delta
- [ ] **FRED-06**: VIX regime computed from VIXCLS with thresholds: calm (<15), elevated (15-25), crisis (>25)
- [ ] **FRED-07**: Dollar strength features: DTWEXBGS level, 5d change, 20d change
- [x] **FRED-08**: Credit stress features: BAMLH0A0HYM2 level, 5d change, 30d rolling z-score
- [x] **FRED-09**: Financial conditions: NFCI level, 4-week direction (rising/falling)
- [x] **FRED-10**: M2 money supply: YoY percent change of M2SL, forward-filled to daily
- [x] **FRED-11**: Carry trade features: DEXJPUS level, 5d pct change, 20d rolling vol, daily move z-score
- [x] **FRED-12**: Net liquidity 365d rolling z-score plus dual-window (30d vs 150d moving average) trend detection
- [x] **FRED-13**: Fed regime classification: `single-target`/`target-range`/`zero-bound` from DFEDTARU/DFEDTARL structure plus `hiking`/`holding`/`cutting` from DFF 90d trajectory
- [x] **FRED-14**: Carry momentum indicator: `(dexjpus_1d_change / dexjpus_20d_vol)` with elevated threshold at 2.0 when carry spread is positive
- [x] **FRED-15**: CPI surprise proxy: `CPIAUCSL_mom - CPIAUCSL_mom.rolling(3).mean()` as deviation from 3-month trend
- [x] **FRED-16**: TARGET_MID `(DFEDTARU + DFEDTARL) / 2` and TARGET_SPREAD `DFEDTARU - DFEDTARL` computed daily
- [x] **FRED-17**: Macro feature refresh wired into `run_daily_refresh.py` after FRED sync, before regime computation

### Macro Regime Classification (MREG)

- [ ] **MREG-01**: `cmc_macro_regimes` table with PK (date) storing composite regime key and per-dimension labels (monetary_policy, liquidity, risk_appetite, carry)
- [ ] **MREG-02**: Monetary policy dimension: `hiking` (DFF 90d change > 0.25%), `cutting` (< -0.25%), `holding` (else) — from DFF trajectory
- [ ] **MREG-03**: Liquidity dimension: `expanding`/`neutral`/`contracting` from net liquidity 30d change direction, with `strongly_expanding`/`strongly_contracting` at z-score > 1
- [ ] **MREG-04**: Risk appetite dimension: `risk_off` (VIX > 25 OR HY_OAS z-score > 1.5 OR NFCI > 0.5), `risk_on` (VIX < 15 AND HY_OAS z < -0.5 AND NFCI < -0.5), `neutral` (else)
- [ ] **MREG-05**: Carry dimension: `unwind` (DEXJPUS daily > 2 sigma AND spread narrowing), `stress` (DEXJPUS 5d vol > 1.5 sigma), `stable` (else)
- [ ] **MREG-06**: Composite macro regime key in same pattern as per-asset: `Cutting-Expanding-RiskOn-Stable`
- [ ] **MREG-07**: Hysteresis applied via existing `HysteresisTracker` with `min_bars_hold` appropriate for macro stickiness (≥5 bars)
- [ ] **MREG-08**: YAML-configurable thresholds for all regime dimension boundaries (not hardcoded)
- [ ] **MREG-09**: Macro regime refresh runs daily after macro feature computation, before signal generation
- [x] **MREG-10**: HMM secondary classifier (2-3 state GaussianHMM on all available FRED macro features, covariance_type="diag" default) as optional confirmation signal alongside rule-based labels
- [x] **MREG-11**: Macro-crypto lead-lag analysis using existing `lead_lag_max_corr()` pattern to quantify macro feature predictive power at lags [-60..+60] days
- [x] **MREG-12**: Regime transition probability matrix from historical macro regime sequences

### Macro-Asset Integration (MINT)

- [x] **MINT-01**: Macro regime feeds into resolver's L4 slot via `resolve_policy_from_table(L4=macro_regime_key)`
- [x] **MINT-02**: Tighten-only semantics preserved — macro `size_mult` ≤ 1.0 for ALL entries, enforced by assertion
- [x] **MINT-03**: Macro regime policy entries added to DEFAULT_POLICY_TABLE with substring matching for partial patterns (e.g., `-RiskOff-Unwind` matches any monetary+liquidity combo)
- [x] **MINT-04**: YAML policy overlay supported via existing `policy_loader.py` for macro regime entries
- [x] **MINT-05**: `refresh_cmc_regimes.py` loads latest macro regime and passes as L4 to resolver for each asset
- [x] **MINT-06**: Executor logs L4 macro regime alongside L0-L2 per-asset regime for every trade decision
- [x] **MINT-07**: Adaptive gross_cap from macro regime (e.g., risk-off caps gross exposure at 50-60%)

### Cross-Asset Aggregation (XAGG)

- [x] **XAGG-01**: BTC/ETH 30d rolling correlation exposed as a queryable feature in `fred_macro_features` (already computed for tail risk; make it a stored column)
- [x] **XAGG-02**: Cross-asset correlation matrix: 30d rolling average pairwise correlation across top assets with high-correlation flag (>0.7 = macro-driven market)
- [x] **XAGG-03**: Aggregate funding rate signal: average funding rate across tracked BTC/ETH perp pairs with z-score vs 30d/90d history
- [x] **XAGG-04**: Crypto-macro correlation regime: rolling 60d correlation of BTC returns vs VIX, DXY, HY OAS with anomaly detection when correlations flip sign

### Event Risk Gates (GATE)

- [ ] **GATE-01**: `dim_macro_events` table seeded with FOMC meeting dates, CPI release dates, and NFP dates for 2026-2027
- [ ] **GATE-02**: FOMC event gate: size_mult reduction (e.g., 0.5) applied ±24h around FOMC meetings via risk engine
- [ ] **GATE-03**: VIX spike gate: VIX > 30 triggers REDUCE state, VIX > 40 triggers FLATTEN state in `flatten_trigger.py`
- [ ] **GATE-04**: Carry unwind velocity gate: DEXJPUS daily z-score > 2.0 with positive rate spread triggers REDUCE; z-score > 3.0 triggers FLATTEN
- [ ] **GATE-05**: Data freshness gate: WARN if fred_macro_features max(ingested_at) > 48h; disable macro regime if > 96h (fall back to per-asset only)
- [ ] **GATE-06**: Credit stress gate: BAMLH0A0HYM2 5d z-score > 1.5 applies size_mult 0.7; > 2.5 applies size_mult 0.4
- [ ] **GATE-07**: CPI release day gate: size_mult reduction ±24h around CPI releases (lighter than FOMC)
- [ ] **GATE-08**: NFP release day gate: size_mult 0.75 on first Friday of each month
- [ ] **GATE-09**: Composite macro stress score (0-100): weighted sum of VIX percentile, HY OAS z-score, carry velocity z-score, NFCI level with tiered response (calm/elevated/stressed/crisis)

### Observability & Monitoring (OBSV)

- [ ] **OBSV-01**: Macro regime display in Streamlit dashboard: current regime, per-dimension labels, color-coded by risk level
- [ ] **OBSV-02**: Telegram alert on macro regime transition (especially to risk-off or carry unwind)
- [ ] **OBSV-03**: FRED data freshness display in pipeline monitor alongside crypto data freshness (traffic-light pattern)
- [ ] **OBSV-04**: Macro regime as drift attribution source in DriftMonitor: flag when macro regime differs between paper and backtest periods
- [ ] **OBSV-05**: Macro regime timeline chart: Plotly visualization with regime labels as colored bands overlaid on portfolio PnL
- [ ] **OBSV-06**: FRED data quality dashboard tab: coverage, freshness, gap detection for all 39 series

## Future Requirements (deferred to post-v1.0.1)

### Advanced ML
- **ML-01**: Blended global liquidity proxy (Fed + ECB + BOJ weighted composite) — needs careful normalization
- **ML-02**: Macro regime in backtest replay — requires full historical FRED labels over backtest periods
- **ML-03**: ETF flow proxy — requires external data source not yet integrated
- **ML-04**: On-chain metrics — requires Glassnode/CryptoQuant subscription

### Data Sources
- **DATA-01**: Real consensus forecast data (Bloomberg/Refinitiv) — paid subscription, contradicts free-tier-first
- **DATA-02**: Real-time VIX websocket feed — requires CBOE data subscription
- **DATA-03**: BTC dominance metric — needs TradingView or CoinGecko integration
- **DATA-04**: Japan CPI — FRED series stopped Jun 2021; needs BOJ/OECD direct source

## Out of Scope

| Feature | Reason |
|---------|--------|
| HMM as primary regime classifier | Model risk on top of model risk; rule-based must work first. HMM is included as optional secondary only. |
| Intraday macro regime updates | FRED data is daily at best; intraday updates create false precision |
| PCA/GMM on all 39 FRED series | Overfit to training period, unstable components, uninterpretable |
| Asset-specific macro sensitivity weights | Unstable, requires frequent recalibration; single macro regime for all assets |
| Real-time FOMC decision scraping | Fragile; next-day FRED update + crypto-native tail risk covers the gap |
| Predictive macro event models | React to state, not predict; prediction introduces compounding model risk |
| Blocking all trades during macro events | Too aggressive; reduce exposure instead via size_mult |
| Social sentiment NLP | Noisy, expensive; funding rates serve as sentiment proxy |
| Backfilling macro into historical cmc_features | Schema migration nightmare; keep macro in separate table, join on date |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FRED-01 | Phase 65 | Complete |
| FRED-02 | Phase 65 | Complete |
| FRED-03 | Phase 65 | Complete |
| FRED-04 | Phase 65 | Complete |
| FRED-05 | Phase 65 | Complete |
| FRED-06 | Phase 65 | Complete |
| FRED-07 | Phase 65 | Complete |
| FRED-08 | Phase 66 | Complete |
| FRED-09 | Phase 66 | Complete |
| FRED-10 | Phase 66 | Complete |
| FRED-11 | Phase 66 | Complete |
| FRED-12 | Phase 66 | Complete |
| FRED-13 | Phase 66 | Complete |
| FRED-14 | Phase 66 | Complete |
| FRED-15 | Phase 66 | Complete |
| FRED-16 | Phase 66 | Complete |
| FRED-17 | Phase 66 | Complete |
| MREG-01 | Phase 67 | Complete |
| MREG-02 | Phase 67 | Complete |
| MREG-03 | Phase 67 | Complete |
| MREG-04 | Phase 67 | Complete |
| MREG-05 | Phase 67 | Complete |
| MREG-06 | Phase 67 | Complete |
| MREG-07 | Phase 67 | Complete |
| MREG-08 | Phase 67 | Complete |
| MREG-09 | Phase 67 | Complete |
| MREG-10 | Phase 68 | Complete |
| MREG-11 | Phase 68 | Complete |
| MREG-12 | Phase 68 | Complete |
| MINT-01 | Phase 69 | Complete |
| MINT-02 | Phase 69 | Complete |
| MINT-03 | Phase 69 | Complete |
| MINT-04 | Phase 69 | Complete |
| MINT-05 | Phase 69 | Complete |
| MINT-06 | Phase 69 | Complete |
| MINT-07 | Phase 69 | Complete |
| XAGG-01 | Phase 70 | Complete |
| XAGG-02 | Phase 70 | Complete |
| XAGG-03 | Phase 70 | Complete |
| XAGG-04 | Phase 70 | Complete |
| GATE-01 | Phase 71 | Pending |
| GATE-02 | Phase 71 | Pending |
| GATE-03 | Phase 71 | Pending |
| GATE-04 | Phase 71 | Pending |
| GATE-05 | Phase 71 | Pending |
| GATE-06 | Phase 71 | Pending |
| GATE-07 | Phase 71 | Pending |
| GATE-08 | Phase 71 | Pending |
| GATE-09 | Phase 71 | Pending |
| OBSV-01 | Phase 72 | Pending |
| OBSV-02 | Phase 72 | Pending |
| OBSV-03 | Phase 72 | Pending |
| OBSV-04 | Phase 72 | Pending |
| OBSV-05 | Phase 72 | Pending |
| OBSV-06 | Phase 72 | Pending |

**Coverage:**
- v1.0.1 requirements: 55 total
- Mapped to phases: 55/55
- Unmapped: 0

---
*Requirements defined: 2026-03-02*
*Last updated: 2026-03-02 (traceability updated after roadmap creation)*
