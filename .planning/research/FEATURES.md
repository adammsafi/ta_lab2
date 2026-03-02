# Feature Landscape: v1.0.1 Macro Regime Infrastructure

**Domain:** Macro regime features for systematic crypto trading
**Researched:** 2026-03-01
**Scope:** FRED-based macro features, regime classification, cross-asset aggregation, event risk gates
**Builds on:** Existing L0-L3 per-asset regimes, 5-gate RiskEngine, 39-series FRED plan (VM-STRATEGY.md)

---

## Context: What Already Exists

This milestone adds a macro regime layer to an existing per-asset regime system. The bar
for "table stakes" is measured against what systematic crypto trading platforms need to
properly condition on macroeconomic data, adjusted for what ta_lab2 already has.

| Area | Already Built | Gap for v1.0.1 |
|------|--------------|----------------|
| Per-asset regimes | L0 (monthly), L1 (weekly), L2 (daily), L3 (intraday) with trend/vol/liq components | No macro overlay -- regimes are purely price-derived |
| Policy resolver | Tighten-only semantics across L0-L4, YAML-overridable policy table | L3/L4 slots exist in resolver but are unused; no macro input flows through them |
| Risk engine | Kill switch, circuit breaker, position/portfolio cap, tail risk (vol spike + correlation breakdown), margin gate | No macro event risk (FOMC, carry unwind, VIX spike); tail risk uses only crypto-native signals |
| FRED infrastructure | FredProvider (1,766 LOC, deferred), VM collecting 3 series, freddata_local FDW bridge | 36 of 39 series not yet collecting; no sync to marketdata; no derived series computed |
| Feature store | 112-column cmc_features (bar-level, per-asset); dim_feature_registry | No macro columns; features are entirely crypto price/volume derived |
| Drift monitor | 6-source attribution, daily comparison, tiered response | No macro drift source; model drift from regime change is undetected |
| Flatten trigger | Vol spike (2-sigma/3-sigma), extreme return (>15%), API halt, correlation breakdown | No macro triggers (FOMC proximity, carry unwind velocity, credit stress) |

---

## Feature Area 1: Raw FRED Series Ingestion and Derived Features

These are the base macro features that all downstream regime classification and risk gates
consume. Without clean, aligned, daily-frequency macro data in the marketdata database,
nothing else in the milestone can function.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| `fred_macro_daily` table in marketdata | All macro features need a single source table; querying across 3 databases is untenable | Medium | Schema: (series_id, date, value, source_freq, ingested_at). PK: (series_id, date). Forward-fill monthly/weekly to daily rows. |
| Forward-fill alignment for mixed-frequency series | Monthly series (CPIAUCSL, UNRATE) and weekly series (WALCL, NFCI) must be usable alongside daily series without NaN gaps | Low | `ffill()` with `limit=45` for monthly, `limit=10` for weekly. Store `source_freq` column so consumers know the provenance. |
| Net liquidity proxy: `WALCL - TGA - RRP` | The single most-correlated macro feature to BTC price. Standard formula across TradingView, DurdenBTC, and institutional research. TGA (WTREGEN) must be added to the FRED pull list if not already there. | Low | Derived daily. Note: WALCL is weekly (Wed), RRPONTSYD is daily. Forward-fill WALCL to daily cadence before subtraction. TGA (WTREGEN) is also weekly -- same treatment. |
| Rate spread features: `US_JP_RATE_SPREAD`, `US_ECB_RATE_SPREAD` | Carry trade incentive is the differential between funding rates. These are already planned in VM-STRATEGY.md. | Low | `DFF - ffill(IRSTCI01JPM156N)` and `DFF - ECBDFR`. Japan rates are monthly; forward-fill before subtraction. |
| Yield curve features: `T10Y2Y` level + `YC_SLOPE_CHANGE_5D` | Yield curve inversion is a consensus recession signal. 5-day momentum of the slope detects steepening/flattening velocity. | Low | `T10Y2Y` is already a FRED series (direct). Momentum: `T10Y2Y - T10Y2Y.shift(5)`. |
| VIX level and regime: `VIXCLS` + `VIX_REGIME` | VIX is the standard cross-asset fear gauge. Crypto-VIX correlation tightened significantly in 2024-2025 with BTC/QQQ 30d correlation at 0.70-0.77. | Low | Thresholds: calm (<15), elevated (15-25), crisis (>25). These are consensus thresholds from multiple sources. |
| Dollar strength: `DTWEXBGS` level + change | Strong dollar = weak BTC is one of the most persistent macro correlations in crypto. | Low | Use 5d and 20d changes alongside level. |
| Credit stress: `BAMLH0A0HYM2` level + change | HY OAS widening is a reliable risk-off signal. Inverse correlation with S&P 500 (and by extension crypto) is well-documented. | Low | Use level, 5d change, and z-score (30d rolling). Widening > 1 std dev above 30d mean = stress signal. |
| Financial conditions: `NFCI` level + direction | NFCI is a 105-measure composite from the Chicago Fed. Positive = tight, negative = loose. Loose conditions historically supportive of crypto. | Low | Weekly frequency; forward-fill to daily. Track direction (is NFCI rising or falling over past 4 weeks). |
| M2 money supply growth: `M2SL` YoY change | Long-horizon BTC correlation. Research suggests 1% rise in liquidity corresponds to approximately 5% rise in crypto, with a 6-week lag. | Low | Monthly; compute YoY pct change, forward-fill to daily. Useful as long-horizon regime context, not a timing signal. |
| Carry trade features: `DEXJPUS` level + velocity | DEXJPUS is the real-time carry unwind alarm. The Aug 2024 carry unwind triggered 20% BTC/ETH losses. Estimated carry trade size: up to $14T vs $3T crypto market cap. | Medium | Track: level, 5d pct change, 20d rolling vol of changes, z-score of daily move. Rapid JPY strengthening (large negative change in DEXJPUS) = unwind signal. |
| Sync automation from VM to marketdata | Without automated sync, FRED data goes stale and all downstream features break silently | High | SSH tunnel, materialized view refresh in freddata_local, INSERT...ON CONFLICT into fred_macro_daily. Must run as a cron/scheduled task. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Net liquidity z-score (365d rolling) | Normalizes net liquidity into a regime-interpretable signal. Used by DurdenBTC and institutional macro trackers. 30d vs 150d trend comparison detects regime shifts. | Medium | Z-score = (current - mean_365d) / std_365d. Dual-window (30d vs 150d moving average) for trend regime detection. |
| CPI surprise proxy | The macro event that moves crypto most is CPI surprise (actual - consensus). Without consensus data, proxy with deviation from 3-month trend. | Medium | `cpi_surprise_proxy = CPIAUCSL_mom - CPIAUCSL_mom.rolling(3).mean()`. Imperfect but captures the concept. Real consensus data (Bloomberg, Refinitiv) requires paid subscription -- defer. |
| Fed regime classification | `single-target` / `target-range` / `zero-bound` from DFEDTARU/DFEDTARL structure, plus `hiking` / `holding` / `cutting` from DFF trajectory. Already prototyped in fedtools2 ETL. | Medium | Rule-based: TARGET_SPREAD > 0 AND DFF is rising = target-range + hiking. Combine with rate momentum (DFF 30d change sign). |
| Carry momentum indicator | Beyond rate differential level: rate of change of DEXJPUS relative to its own vol. A 2-sigma daily JPY move when carry spread is wide = high unwind probability. | Medium | `carry_momentum = (dexjpus_1d_change / dexjpus_20d_vol)`. When this exceeds 2.0 and carry spread is positive, carry unwind risk is elevated. |
| Blended global liquidity proxy | Combine Fed (WALCL-TGA-RRP), ECB (via ECBDFR direction), and BOJ (via DEXJPUS direction) into a single global liquidity score. Institutional research increasingly uses global, not just US, liquidity. | High | Weighted composite: US weight 0.6, EUR weight 0.2, JPY weight 0.2. Requires careful normalization. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real-time intraday FRED data | FRED updates once per day (most series). Building infrastructure for sub-daily macro data creates false precision. | Accept daily granularity for FRED data. For intraday macro sensitivity, use crypto-native vol and correlation features (already built in L2/L3 regimes). |
| Consensus forecast data (Bloomberg/Refinitiv) | Paid subscription required. Consensus data is extremely valuable but adding a paid dependency contradicts the project's free-tier-first economics. | Use trend-deviation proxies for surprise estimation. Defer consensus data to a future milestone if/when paid data becomes justified. |
| Japan CPI from FRED | FRED's Japan CPI series stopped in June 2021 (confirmed in VM-STRATEGY.md). Building around stale data creates a maintenance trap. | Skip Japan CPI. BOJ rate and DEXJPUS are sufficient carry trade signals. If Japan CPI becomes needed, source directly from BOJ/OECD later. |
| Recomputing all macro features on every refresh | Some FRED series update weekly or monthly. Recomputing daily wastes cycles and can introduce spurious micro-changes from float rounding. | Track `source_last_updated` per series. Only recompute derived features when an upstream input actually changes. |
| Backfilling derived series into historical cmc_features rows | cmc_features has 112 columns and millions of rows. Adding macro columns retroactively is a schema migration nightmare. | Keep macro features in a separate `fred_macro_daily` table. Join on date when needed for IC evaluation, ML training, or regime classification. Do NOT add columns to cmc_features. |

### Feature Dependencies

```
VM FRED collection (39 series)
  -> SSH tunnel + sync to freddata_local
  -> Materialized views in freddata_local
  -> INSERT...ON CONFLICT into fred_macro_daily (marketdata DB)
  -> Forward-fill mixed-frequency to daily
  -> Compute derived series (net liquidity, rate spreads, etc.)

fred_macro_daily (new table in marketdata)
  -> Consumed by macro regime classifier (Feature Area 2)
  -> Consumed by risk event gates (Feature Area 5)
  -> Consumed by IC evaluation (existing analysis/ic_eval.py)
  -> Consumed by drift monitor as new drift source (Feature Area 4)
```

---

## Feature Area 2: Macro Regime Classification

Classify the current macroeconomic environment into regimes that the policy resolver
can consume. The key design question: rule-based thresholds vs HMM vs clustering.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Rule-based macro regime labels | Start with deterministic, auditable thresholds. HMM/clustering are model risk on top of model risk. The existing per-asset regime system is rule-based and this consistency matters for debugging. | Medium | Regime dimensions: monetary_policy (hiking/holding/cutting), liquidity (expanding/neutral/contracting), risk_appetite (risk-on/neutral/risk-off), carry (stable/stress/unwind). Each dimension classified by simple threshold rules on FRED features. |
| Composite macro regime string | Same pattern as per-asset regimes: `Up-Normal-Normal` becomes `Cutting-Expanding-RiskOn-Stable` for macro. Existing `compose_regime_key()` pattern reused. | Low | 4-dimensional string key. Each dimension is a discrete label. Store in `cmc_macro_regimes` table with PK (date). |
| Monetary policy dimension | Classifies Fed rate trajectory. Most fundamental macro regime dimension for crypto. Rate cuts are structurally bullish for risk assets. | Low | `hiking` if DFF 90d change > 0.25%; `cutting` if DFF 90d change < -0.25%; `holding` otherwise. Thresholds calibrated from historical rate cycles. |
| Liquidity dimension | Fed net liquidity (WALCL-TGA-RRP) direction. The single most important macro driver for crypto. Expanding net liquidity is the strongest macro tailwind. | Low | `expanding` if net_liquidity 30d change > 0; `contracting` if < 0. Add magnitude: `strongly_expanding` if z-score > 1, `strongly_contracting` if z-score < -1. |
| Risk appetite dimension | Cross-asset risk-on/risk-off signal combining VIX, credit stress (HY OAS), and financial conditions (NFCI). | Medium | `risk_off` if VIX > 25 OR HY_OAS z-score > 1.5 OR NFCI > 0.5; `risk_on` if VIX < 15 AND HY_OAS z-score < -0.5 AND NFCI < -0.5; `neutral` otherwise. Threshold-based, same pattern as VIX_REGIME. |
| Carry dimension | Carry trade stability assessment from JPY features. The Aug 2024 unwind demonstrated that this dimension alone can drive 20% drawdowns. | Medium | `unwind` if DEXJPUS daily move > 2 sigma AND US_JP_RATE_SPREAD is narrowing; `stress` if DEXJPUS 5d vol > 1.5 sigma; `stable` otherwise. |
| Hysteresis on macro regime transitions | Macro data is noisy. Without hysteresis, VIX crossing 25 and back to 24.8 flips regime twice in two days. | Low | Reuse existing `HysteresisTracker` from `regimes/hysteresis.py`. Set `min_bars_hold=5` for macro (longer than per-asset default of 3 because macro regimes should be stickier). |
| Storage in `cmc_macro_regimes` table | Macro regime state needs to be queryable alongside per-asset regimes for policy resolution and IC evaluation. | Medium | Schema: (date, regime_key, monetary_policy, liquidity, risk_appetite, carry, computed_at). Single row per date. Daily granularity matches FRED update cadence. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| HMM regime detection as secondary classifier | After rule-based labels are working, fit a 2-3 state HMM on net liquidity + VIX + HY OAS to detect regimes the rules miss. HMMs are the standard academic approach and capture nonlinear state transitions. | High | Use hmmlearn library (GaussianHMM, 2-3 states). Train on 5+ years of data. Compare HMM labels vs rule-based labels -- where they disagree is informative. Do NOT replace rules with HMM; use HMM as a confirmation/divergence signal. |
| Macro-crypto lead-lag analysis | Quantify whether macro regime changes lead or lag crypto regime changes. Research suggests a 6-week lag between liquidity and BTC. | Medium | Reuse existing `lead_lag_max_corr()` from `regimes/comovement.py`. Test macro features against BTC returns at lags [-20, -10, -5, 0, 5, 10, 20] days. |
| Regime transition probability matrix | From historical macro regime sequences, compute transition probabilities. "When we are in risk-off, what is the probability of transitioning to risk-on in the next 5/10/20 days?" | Medium | Simple counting from historical labels. Value: informs position sizing -- if P(risk_off -> risk_on) within 5d is >40%, current risk-off may be transient. |
| IC evaluation of macro features by per-asset regime | "Do macro features have more predictive power during trending markets vs sideways?" Answers whether macro conditioning improves per-asset signals. | Medium | Join fred_macro_daily with cmc_features and cmc_regimes on date. Group IC by L1 regime label. Reuses existing IC infrastructure from v0.9.0. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| HMM as primary regime classifier | HMM states are unlabeled, non-deterministic, and change with retraining. Debugging "why did the system go risk-off?" is nearly impossible with HMM alone. | Rule-based primary, HMM as optional secondary/confirmation signal. |
| Intraday macro regime updates | FRED data is daily (at best). Updating macro regime intraday creates an illusion of responsiveness when the underlying data hasn't changed. | Daily macro regime update, aligned with FRED data refresh. For intraday macro-like responses, use VIX if available from a live feed (out of scope for FRED integration). |
| Regime classification from PCA of all 39 FRED series | PCA on 39 macro series is overfit to the training period. The principal components are unstable and uninterpretable. | Use domain-knowledge-driven dimensions (monetary policy, liquidity, risk appetite, carry). Each dimension uses 2-4 specific series, not a statistical cocktail of all 39. |
| Gaussian Mixture Models as regime classifier | GMM assumes Gaussian regime distributions. Macro regime transitions are abrupt (rate hikes, carry unwinds), not smooth Gaussian clusters. | Rule-based with hysteresis for abrupt transitions. HMM (which models transitions explicitly) is a better probabilistic alternative if one is needed. |

### Feature Dependencies

```
fred_macro_daily (Feature Area 1)
  -> Macro regime classifier reads derived features
  -> Computes 4-dimensional regime labels
  -> Writes to cmc_macro_regimes table

regimes/hysteresis.py (existing)
  -> HysteresisTracker reused for macro regime stickiness
  -> min_bars_hold=5 for macro (vs 3 for per-asset)

regimes/labels.py pattern (existing)
  -> Macro labeler functions follow same pattern as label_trend_basic(), label_vol_bucket()
  -> Each dimension is a function: label_monetary_policy(), label_liquidity(), etc.
```

---

## Feature Area 3: Macro-Asset Regime Integration

How macro regimes interact with per-asset regimes in the policy resolver. This is the
architectural core of the milestone: connecting macro state to trading decisions.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Macro regime feeds into L3 or L4 slot in policy resolver | The resolver already accepts L3 and L4 (currently unused). Macro regime should populate one of these slots so existing tighten-only semantics apply automatically. | Medium | Recommendation: Use L4 for macro. L3 is reserved for intraday per-asset regimes (already defined in labels.py as `label_layer_intraday`). L4 is a clean slot for macro overlay. |
| Tighten-only semantics preserved | Macro regime must only be able to tighten risk, never loosen it. If per-asset says risk-off, macro saying risk-on should NOT increase exposure. This is the fundamental design invariant of the resolver. | Low | Already enforced by `_tighten()` in resolver.py. Macro feeds through the same path. No code change needed for the tighten logic itself. |
| Macro regime policy entries in DEFAULT_POLICY_TABLE | The resolver does substring matching on regime keys. Macro regime keys need policy entries that map to size_mult, stop_mult, orders, etc. | Medium | Add entries like: `"Cutting-Expanding-RiskOn-Stable": {"size_mult": 1.0}`, `"Hiking-Contracting-RiskOff-": {"size_mult": 0.4, "orders": "passive"}`, `"-RiskOff-Unwind": {"size_mult": 0.2, "orders": "passive"}`. The substring matching makes partial patterns powerful. |
| Daily macro regime refresh wired into run_daily_refresh.py | Macro regime must be computed after FRED data is synced and before signal generation / executor runs. | Low | New stage in daily refresh: bars -> EMAs -> per-asset regimes -> **macro regime** -> stats -> signals. |
| Macro regime logged alongside per-asset regime in executor | When the executor makes a trade decision, the log should show both the per-asset regime (L0-L2) and the macro regime (L4). | Low | Extend executor logging to include L4 value. Already logs L0-L2 from policy resolution. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Macro-asset regime composite analysis | Dashboard view showing: for each (macro_regime, per_asset_regime) pair, what was the average forward return? Answers: "Is macro conditioning additive to per-asset regime?" | Medium | SQL cross-join of cmc_macro_regimes and cmc_regimes, joined with forward returns. Heatmap in Streamlit. |
| Adaptive gross_cap from macro regime | In risk-off macro environments, cap gross exposure at 50-60% instead of 100%. More nuanced than binary risk-on/off. | Low | Add `gross_cap: 0.5` to risk-off macro policy entries. The resolver already supports gross_cap in TightenOnlyPolicy. |
| Macro regime in backtest replay | Backtests should be conditionable on macro regime. "What was this strategy's Sharpe during risk-off macro?" Enables regime-conditional backtest analysis. | High | Requires joining cmc_macro_regimes with backtest date range. Needs historical macro regime labels computed over the full backtest period (requires historical FRED data). |
| Per-asset proxy from macro when per-asset data is thin | For new assets with <52 weekly bars, macro regime is more informative than per-asset L0/L1 (which are undefined). Existing `proxies.py` already has this pattern. | Medium | Extend `infer_cycle_proxy()` and `infer_weekly_macro_proxy()` to incorporate macro regime as an additional tightening factor. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Macro regime overriding per-asset regime (loosening) | If macro says risk-on but per-asset says Down-High-Stressed, loosening is dangerous. This violates the fundamental tighten-only invariant. | Tighten-only, always. Macro can only reduce exposure, never increase it. |
| Separate macro policy resolver (bypass existing) | Building a parallel resolver for macro creates two policy systems that can contradict. Integration nightmares. | Feed macro through the existing resolver's L4 slot. One resolver, one policy output. |
| Macro regime as a binary on/off switch | "Macro is bad, don't trade" is too coarse. The existing regime system has nuance (size_mult, stop_mult, orders, setups, gross_cap). Macro should have the same nuance. | Map macro regimes to the same policy dimensions: size_mult, stop_mult, gross_cap, orders. Let tighten-only semantics combine them. |
| Asset-specific macro sensitivity weights | "BTC is 0.8 correlated with liquidity, SOL is 0.6" -- asset-specific macro betas are unstable and require frequent recalibration. | Use a single macro regime for all assets. Per-asset sensitivity differences are already captured by per-asset regimes (L0-L2). |

### Feature Dependencies

```
cmc_macro_regimes (Feature Area 2)
  -> Macro regime key read by policy resolver as L4
  -> Must be computed before signal generation each day

regimes/resolver.py (existing)
  -> resolve_policy() already accepts L4 parameter
  -> DEFAULT_POLICY_TABLE needs new macro regime entries
  -> Policy loader (policy_loader.py) supports YAML override

regimes/hysteresis.py (existing)
  -> HysteresisTracker used for macro regime stickiness
  -> is_tightening_change() works with macro keys (substring matching)
```

---

## Feature Area 4: Cross-Asset Aggregation for Macro Context

Using cross-asset crypto signals (BTC dominance, correlation structure, funding rates)
alongside FRED data to build a richer macro picture.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| BTC/ETH rolling correlation as macro health indicator | Correlation breakdown (already in flatten_trigger.py at -0.20 threshold) is a crypto-native macro stress signal. Make it a feature, not just a trigger. | Low | Already computed for tail risk. Expose as a column in a features table. 30d rolling Pearson correlation between BTC and ETH daily returns. |
| Cross-asset correlation matrix (top 5-10 assets) | When all crypto moves together (high average pairwise correlation), the market is in "macro mode" -- driven by macro flows, not asset-specific factors. | Medium | 30d rolling average pairwise correlation across top assets. High avg correlation (>0.7) = macro-driven market; low (<0.4) = idiosyncratic/alpha opportunity. |
| Aggregate funding rate signal | Perp funding rates across BTC and ETH signal market-wide leverage and sentiment. Extremely positive funding = crowded long; negative = crowded short. | Medium | Already have `cmc_funding_rates` table (v1.0.0). Compute: avg funding rate across tracked pairs, z-score of current vs 30d/90d history. |
| BTC dominance proxy (if available) | Rising BTC dominance in risk-off environments = flight to quality within crypto. Falling dominance = risk-on rotation to alts. | Low | Requires BTC market cap / total market cap. May not be available from current data sources. If unavailable, skip -- not critical. Mark as LOW confidence. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Crypto-macro correlation regime | Track whether BTC-VIX, BTC-DXY, BTC-HY_OAS correlations are in their normal range or breaking down. Correlation regime shifts signal structural market changes. | High | Rolling 60d correlation of BTC daily returns vs each macro feature. When BTC-VIX correlation flips from negative (normal) to positive (anomalous), it signals a structural shift. |
| Sector-rotation signal within crypto | When macro turns risk-off, capital flows from alts to BTC to stablecoins. Detecting this flow pattern adds alpha to position sizing. | High | Requires market cap data per asset, which may not be in the current database. Defer unless data is readily available. |
| ETF flow proxy (if accessible) | BTC ETF inflows/outflows are a major post-2024 price driver. Net flows signal institutional macro positioning. | Medium | Requires external data source (not FRED). Alternative.me or similar free API. Mark as LOW confidence for v1.0.1 scope. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| On-chain metrics (active addresses, exchange flows) | Requires Glassnode/CryptoQuant subscription or complex free-tier scraping. High data engineering cost for uncertain alpha. | Defer to future milestone. Focus on FRED (free, reliable) + exchange data (already connected). |
| Social sentiment analysis (Twitter/Reddit NLP) | Noisy, expensive to compute, requires NLP infrastructure. Alpha from social sentiment is well-documented as fleeting. | Use funding rates as a sentiment proxy -- they directly reflect how traders are positioned, not what they say. |
| Order book microstructure as macro signal | The existing microstructure module computes Kyle lambda, VPIN. These are per-asset execution features, not macro signals. Conflating them adds confusion. | Keep microstructure features in their own domain. If order book stress across multiple assets is desired, that's a separate feature area. |

---

## Feature Area 5: Macro Event Risk Gates

Risk gates that activate around known macro events (FOMC, VIX spikes, carry unwinds)
to protect the portfolio from event-driven volatility.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| FOMC event calendar gate | Reduce position limits +/-24h around FOMC meetings. FOMC announcements produce the largest systematic vol spikes in crypto markets. 8 meetings per year, dates are known in advance. | Medium | Store FOMC dates in a `dim_macro_events` table (type, date, description). Risk engine checks: "Is there an FOMC meeting within 24 hours?" If yes, apply size_mult reduction (e.g., 0.5). |
| VIX spike gate | When VIX crosses a crisis threshold (>30), immediately tighten risk beyond what the daily macro regime would apply. This is an intra-day override for extreme conditions. | Medium | New flatten trigger condition in `flatten_trigger.py`: if VIX > 30 (from most recent FRED pull), set tail_risk_state to REDUCE. VIX > 40, set to FLATTEN. Requires VIX value to be accessible from the risk engine (read from fred_macro_daily). |
| Carry unwind velocity gate | When DEXJPUS moves >2 sigma in a single day AND the US-Japan rate spread is positive (carry trade is on), activate REDUCE state. The Aug 2024 unwind moved 5% in DEXJPUS and 20% in BTC simultaneously. | High | New trigger in `flatten_trigger.py`: `carry_unwind_trigger`. Inputs: DEXJPUS daily change z-score (from fred_macro_daily), US_JP_RATE_SPREAD level. If z-score > 2.0 AND spread > 0, return REDUCE. If z-score > 3.0 AND spread > 0, return FLATTEN. |
| Data freshness gate | Alert if FRED sync is stale (>48h without update for daily series). Stale macro data means the macro regime is based on outdated information. | Low | Check `max(ingested_at)` in fred_macro_daily. If > 48h stale, log WARNING and set macro regime confidence to LOW. If > 96h stale, disable macro regime input (fall back to per-asset only). |
| FOMC calendar seeding | Populate dim_macro_events with known FOMC dates for 2026-2027. This is static data -- 8 meetings per year, dates published by the Fed. | Low | Insert rows manually or from a static JSON file. Include: meeting date, minutes release date (3 weeks later), press conference flag. |
| Credit stress gate | When HY OAS widens rapidly (>1.5 sigma in 5 days), apply size reduction. Credit stress precedes equity and crypto selloffs. | Medium | Add to macro risk evaluation: if BAMLH0A0HYM2 5d z-score > 1.5, apply size_mult 0.7. If > 2.5, apply size_mult 0.4. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| CPI release day gate | CPI releases (monthly) produce the second-largest systematic crypto vol spikes after FOMC. Known dates, high impact. | Low | Add CPI release dates to dim_macro_events. Same gate logic as FOMC: reduce exposure +/-24h around release. |
| NFP (Non-Farm Payrolls) gate | First Friday of each month. Less impactful than FOMC/CPI but still moves crypto. | Low | Add NFP dates to dim_macro_events. Lighter gate: size_mult 0.75 (vs 0.5 for FOMC). |
| Composite macro stress score | Single 0-100 score combining VIX level, credit stress, carry velocity, and financial conditions. Higher = more stressed. Threshold-based tier system for risk response. | Medium | Weighted sum: VIX_percentile * 0.3 + HY_OAS_zscore * 0.25 + carry_velocity_zscore * 0.25 + NFCI_level * 0.2. Tiers: 0-30 = calm, 30-60 = elevated, 60-80 = stressed, 80-100 = crisis. |
| Automatic event gate from macro regime | Instead of hardcoded FOMC dates, detect "macro event periods" automatically from vol spike patterns in macro features. | High | Requires anomaly detection on macro feature time series. Interesting research project but premature for v1.0.1. Hardcoded calendars are simpler and more reliable. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real-time VIX feed (websocket) | Requires a separate data provider subscription (CBOE data is not free for streaming). FRED VIX updates once daily. | Use FRED daily VIX. For same-day VIX spikes, the crypto-native vol features (ATR, implied vol from options if available) already capture the information. |
| Predictive macro event models | "Will the Fed cut rates?" -- predicting macro events is a different problem from responding to macro state. Prediction introduces model risk that compounds with trading model risk. | React to state, not predict. The system should detect "rates are being cut" not "rates will be cut." Use current FRED values, not forecasts. |
| Blocking all trades during macro events | Complete halt during FOMC is too aggressive. Some strategies (mean reversion, short vol) may benefit from the event. | Reduce exposure (size_mult), don't block entirely. Let per-strategy configuration decide whether to participate in event windows. |
| Scraping real-time FOMC decisions | FOMC decisions are released at 2:00 PM ET. Scraping the Fed website for real-time decisions is fragile and unnecessary for a paper trading system. | Use next-day FRED data update. For the 2-hour window between announcement and FRED update, the crypto-native tail risk system already handles extreme moves. |

### Feature Dependencies

```
fred_macro_daily (Feature Area 1)
  -> VIX, HY OAS, DEXJPUS values read by risk gates
  -> Data freshness checked by staleness gate

dim_macro_events (new table)
  -> FOMC dates, CPI dates, NFP dates
  -> Seeded statically, updated annually

risk/flatten_trigger.py (existing)
  -> Add new trigger types: vix_spike, carry_unwind, credit_stress
  -> Priority ordering: existing triggers first, macro triggers after

risk/risk_engine.py (existing)
  -> evaluate_tail_risk_state() extended to accept macro inputs
  -> check_order() unchanged (reads from dim_risk_state as before)

run_daily_refresh.py (existing)
  -> New stage: macro risk evaluation after macro regime computation
  -> Updates dim_risk_state.tail_risk_state if macro triggers fire
```

---

## Feature Area 6: Macro Drift and Monitoring

Extending the drift monitor and dashboard to incorporate macro regime state.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Macro regime as drift attribution source | When paper trading PnL diverges from backtest, macro regime change is a plausible explanation. Add macro regime to the drift attribution pipeline. | Medium | New drift source: "macro_regime_changed". If macro regime was different during paper period vs backtest period, flag as potential drift cause. |
| Macro regime display in Streamlit dashboard | Dashboard should show current macro regime alongside per-asset regimes. Without this, the operator has no visibility into macro overlay decisions. | Low | New card/metric on the dashboard: "Macro Regime: Cutting-Expanding-RiskOn-Stable". Color-coded by risk level. |
| Macro feature staleness in pipeline monitor | Pipeline monitor (Mode B) should show FRED data freshness alongside crypto data freshness. | Low | Add fred_macro_daily to the staleness check in the pipeline monitor. Same traffic-light pattern as existing tables. |
| Macro regime change notification via Telegram | When macro regime transitions (especially to risk-off or carry unwind), send a Telegram alert. Macro regime changes are rare (days to weeks between transitions) so alert volume is low. | Low | Reuse existing Telegram notification infrastructure. New message type: "MACRO REGIME CHANGE: risk_appetite changed from neutral to risk_off. VIX at 28.5, HY OAS z-score 1.8." |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Macro regime timeline in dashboard | Visual timeline showing macro regime history overlaid on portfolio PnL. Enables visual correlation between regime changes and performance shifts. | Medium | Plotly chart: x-axis = date, top panel = PnL, bottom panel = macro regime labels as colored bands. |
| FRED data quality dashboard | Show data coverage, freshness, and gap detection for all 39 FRED series in a dedicated dashboard tab. | Medium | Read from fred_macro_daily metadata. Flag series with gaps > 2 business days. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real-time macro dashboard with auto-refresh | FRED data updates once per day. Auto-refreshing a macro dashboard every 5 seconds wastes resources and creates a false sense of real-time monitoring. | Manual refresh button with 1-hour cache TTL. Macro data changes once per day; dashboard reflects that cadence. |

---

## Cross-Feature Dependencies

```
Feature Area 1: Raw FRED Ingestion
  -> Foundation for everything else
  -> MUST be complete and tested before any other area starts

Feature Area 2: Macro Regime Classification
  -> Depends on Feature Area 1 (reads from fred_macro_daily)
  -> Required by Feature Area 3 (regime feeds into resolver)
  -> Required by Feature Area 5 (regime state drives risk gates)

Feature Area 3: Macro-Asset Integration
  -> Depends on Feature Area 2 (macro regime labels)
  -> Modifies resolver.py policy table (but not tighten logic)
  -> Wires into executor via L4 parameter

Feature Area 4: Cross-Asset Aggregation
  -> Partially independent (BTC/ETH correlation is already computed)
  -> Enriches Feature Area 2 (additional inputs to regime classifier)
  -> Can run in parallel with Feature Areas 2-3

Feature Area 5: Event Risk Gates
  -> Depends on Feature Area 1 (reads VIX, DEXJPUS from fred_macro_daily)
  -> Depends on Feature Area 2 (macro regime state as context)
  -> Modifies risk/flatten_trigger.py (adds new trigger types)

Feature Area 6: Drift and Monitoring
  -> Depends on Feature Areas 1-3 (needs macro data and regime labels)
  -> Last in build order (read-only display of other areas' outputs)
```

---

## MVP Recommendation

For v1.0.1 MVP, prioritize by dependency order and value delivered:

### Must Have (enables the macro regime pipeline end-to-end)

1. **FRED series expansion + sync pipeline** (Area 1, table stakes) -- Without macro data in marketdata, nothing else works. This is the critical path. Includes fred_macro_daily table DDL, forward-fill alignment, VM collection expansion to 39 series, and sync automation.

2. **Core derived features** (Area 1, table stakes) -- Net liquidity proxy, rate spreads, VIX regime, YC slope change, dollar strength, credit stress z-score, carry features. These are simple computations on raw series but provide the inputs to everything downstream.

3. **Rule-based macro regime classifier** (Area 2, table stakes) -- Four dimensions (monetary policy, liquidity, risk appetite, carry) with threshold rules. Store in cmc_macro_regimes. Apply hysteresis. This is the core intellectual contribution of the milestone.

4. **L4 integration in policy resolver** (Area 3, table stakes) -- Wire macro regime into the existing resolver's L4 slot. Add policy entries for macro regime keys. Tighten-only semantics preserved automatically.

5. **FOMC event gate + VIX spike gate** (Area 5, table stakes) -- The two highest-impact event risk gates. FOMC dates are static (easy to seed). VIX spike reads from fred_macro_daily (already available after Area 1).

6. **Macro regime in dashboard + Telegram** (Area 6, table stakes) -- Operator visibility into macro overlay decisions. Without this, the macro system is a black box.

### Should Have (adds significant value, not blocking)

- **Carry unwind velocity gate** (Area 5) -- Higher complexity but critical for the next Aug-2024-style event.
- **BTC/ETH correlation as feature** (Area 4) -- Already computed; just needs to be exposed as a feature column.
- **Macro-crypto lead-lag analysis** (Area 4 differentiator) -- Quantifies the value of macro features for crypto timing. Uses existing `lead_lag_max_corr()`.
- **Data freshness gate** (Area 5) -- Simple to implement, prevents silent degradation.
- **Credit stress gate** (Area 5) -- HY OAS widening is a reliable risk-off signal.

### Defer to Post-v1.0.1

- **HMM regime detection**: High complexity model risk on top of model risk. Rule-based must work first.
- **Blended global liquidity proxy**: Requires careful normalization across Fed/ECB/BOJ. Defer until US-only liquidity proxy is validated.
- **CPI surprise proxy**: Without real consensus data, the proxy is low confidence. Defer until consensus data source is identified.
- **ETF flow proxy**: Requires external data source not yet integrated.
- **On-chain metrics**: Requires Glassnode/CryptoQuant subscription.
- **Macro regime in backtest replay**: Requires full historical FRED data and macro regime labels computed over backtest period. Significant data engineering effort.

---

## Sources

### HIGH Confidence (official documentation, codebase inspection)

- Codebase inspection: `regimes/resolver.py` (L3/L4 slots, tighten-only semantics), `regimes/labels.py` (per-asset labeling pattern), `regimes/hysteresis.py` (HysteresisTracker), `risk/risk_engine.py` (7-gate architecture), `risk/flatten_trigger.py` (existing trigger thresholds)
- VM-STRATEGY.md: 39 FRED series list, derived series formulas, infrastructure gaps
- FRED official series pages: [VIXCLS](https://fred.stlouisfed.org/series/VIXCLS), [BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2), [WALCL](https://fred.stlouisfed.org/series/WALCL), [NFCI](https://fred.stlouisfed.org/series/NFCI)
- [Chicago Fed NFCI About Page](https://www.chicagofed.org/research/data/nfci/about) -- 105 measures, positive = tight, negative = loose

### MEDIUM Confidence (multiple credible sources agree)

- Net liquidity formula (WALCL - TGA - RRP): [TradingView indicators](https://www.tradingview.com/script/AWrUtm2d-FED-Net-Liquidity-WALCL-TGA-RRP/), [DurdenBTC](https://durdenbtc.com/charts/netliqz/), [Reflexivity Research PDF](https://cdn.prod.website-files.com/64f99c50f4c866dee943165/65367a37c779eab3fa42c35b_Revisiting%20the%20Net%20Liquidity%20Formula.pdf)
- BTC/equity correlation tightening: [AInvest](https://www.ainvest.com/news/economic-data-fed-policy-signals-reshaping-crypto-market-dynamics-2512/), [MEXC Blog](https://blog.mexc.com/news/how-macro-liquidity-drives-crypto-markets-rate-cuts-etfs-and-capital-flows/)
- 6-week liquidity-BTC lag: [TraderHC analysis](https://www.traderhc.com/p/liquidity-is-everything-the-one-formula)
- VIX thresholds (calm <15, elevated 15-25, crisis >25): [DozenDiamonds](https://www.dozendiamonds.com/volatility-regime-shifting/), [CFA Institute](https://blogs.cfainstitute.org/investor/2026/02/20/why-static-portfolios-fail-when-risk-regimes-change/)
- Carry unwind mechanics: [BIS Bulletin 90](https://www.bis.org/publ/bisbull90.pdf), [CoinDesk analysis](https://www.coindesk.com/markets/2025/12/07/bitcoin-faces-japan-rate-hike-yen-carry-trade-unwind-fears-miss-the-mark-real-risk-lie-elsewhere/)
- HMM for crypto regime detection: [QuantStart](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/), [QuantInsti](https://blog.quantinsti.com/regime-adaptive-trading-python/), [Medium HMM+LSTM](https://medium.com/@akashdevbuilds/how-i-built-a-market-regime-classifier-for-crypto-using-hmms-and-lstms-8151047582f7)

### LOW Confidence (single source, unverified, needs validation)

- 1% liquidity rise = 5% crypto rise claim: Single source (TraderHC). The direction is plausible but the magnitude needs validation against ta_lab2's own data.
- NFCI threshold of -50/-63 for alt season: Single TradingView indicator description. Needs backtesting against ta_lab2 data before use.
- BTC dominance as reliable risk-on/off signal: Commonly stated but the mechanism is less clear in a post-ETF market. Needs validation.

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| Raw FRED features (Area 1) | HIGH | Series list verified against FRED.org; formulas are simple arithmetic; sync architecture validated against existing FDW infrastructure |
| Regime classification (Area 2) | MEDIUM | Rule-based thresholds are reasonable but need calibration against historical data. Exact thresholds (VIX 15/25, rate change 0.25%) are starting points, not final values. |
| Macro-asset integration (Area 3) | HIGH | Resolver architecture inspection confirms L4 slot is available and tighten-only semantics are enforced by existing code |
| Cross-asset aggregation (Area 4) | MEDIUM | BTC/ETH correlation is well-understood; broader cross-asset signals depend on data availability that needs verification |
| Event risk gates (Area 5) | MEDIUM | FOMC/VIX gates are standard practice; carry unwind gate is novel and thresholds need careful calibration from Aug 2024 event data |
| Drift and monitoring (Area 6) | HIGH | Read-only display of other areas' outputs; Streamlit and Telegram infrastructure is proven |

---

*Research completed: 2026-03-01*
*Ready for roadmap: yes*
