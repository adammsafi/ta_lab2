# Quantitative Finance Ecosystem Review vs ta_lab2

**Date**: 2026-02-24
**Source**: https://github.com/topics/quantitative-finance (repos with 4.5k+ stars)
**Purpose**: Identify features ta_lab2 can leverage or copy from top open-source quant finance packages.

---

## Repos Reviewed (20 repos, 4.5k+ stars)

| Repo | Stars | Category | Relevance to ta_lab2 |
|---|---|---|---|
| **Qlib** (Microsoft) | 37.8k | AI quant platform | HIGH — IC eval, expression engine, cross-sectional norms, portfolio strategies |
| **PyPortfolioOpt** | 5.5k | Portfolio optimization | HIGH — mean-variance, HRP, CVaR, Black-Litterman, sector constraints |
| **QuantStats** | 6.8k | Portfolio analytics | HIGH — 60+ metrics, HTML tear sheets, benchmark comparison |
| **MLFinLab** (Hudson & Thames) | 4.6k | ML for finance (AFML) | HIGH — triple barrier, purged CV, feature importance, microstructure |
| **VectorBT** | 6.7k | Backtesting engine | MEDIUM — already using; PRO adds CPCV, MAE/MFE, stop laddering |
| **Jesse** | 7.5k | Crypto trading bot | MEDIUM — Monte Carlo, Optuna optimization, route management |
| **OpenBB** | 61.9k | Data terminal | LOW — different product category |
| **TA-Lib Python** | 11.7k | Indicator library | LOW — already have indicators via pandas-ta |
| **StockSharp** | 9.2k | C# trading platform | NONE — wrong language |
| **QuantLib** | 6.8k | Derivatives pricing | NONE — irrelevant for crypto spot/perps |
| **Qbot** | 16.3k | AI quant platform | LOW — Chinese-focused, less mature |
| **Stock** | 11.7k | Stock data + indicators | LOW — stock-specific |
| **Quant Trading** | 9.2k | Strategy collection | LOW — educational, not a library |
| **Financial ML** | 8.4k | ML guide | LOW — educational |
| **Awesome Quant** | 24.4k | Resource list | REFERENCE — curated links |
| **Awesome Systematic Trading** | 7.2k | Resource list | REFERENCE — curated links |
| **Financial Models & Numerical Methods** | 6.7k | Notebooks | LOW — derivatives-focused |
| **TensorFlow Quant Finance** | 5.2k | GPU quant | LOW — derivatives pricing on GPU |
| **Awesome AI in Finance** | 4.9k | Resource list | REFERENCE — curated links |
| **QuantsPlaybook** | 4.5k | Research reproductions | REFERENCE — strategy ideas |

---

## TIER 1 — High Impact, Direct Fit

### 1.1 Portfolio Optimization (from PyPortfolioOpt)

**Gap**: ta_lab2 has per-asset signals only, no cross-asset allocation or portfolio-level optimization.

**What to adopt**:

#### EfficientCVaR / EfficientCDaR
Tail-risk optimizers that avoid covariance entirely, operating on raw return scenarios.
- `EfficientCVaR`: minimizes average loss in worst alpha% of days
- `EfficientCDaR`: accounts for drawdown duration, not just magnitude
- Especially relevant for crypto given heavy left tails and prolonged drawdowns

#### Hierarchical Risk Parity (HRP)
- Cluster-based, no matrix inversion required
- More robust out-of-sample than mean-variance
- Fallback when covariance matrix is ill-conditioned (common with small altcoin universes)

#### Black-Litterman with CMC Market Caps
- Use CMC market cap data as prior: `market_implied_prior_returns(market_caps, risk_aversion, cov_matrix)`
- Layer model-generated views (EMA/RSI signal outputs) as Q vector
- Bayesian allocation for the crypto universe

#### Sector Constraints
```python
sector_mapper = {"BTC": "L1", "ETH": "L1", "SOL": "L1", "AAVE": "DeFi"}
ef.add_sector_constraints(sector_mapper,
                          sector_lower={"L1": 0.20},
                          sector_upper={"L1": 0.60, "DeFi": 0.30})
```
Map assets by chain/sector using existing `dim_listings` / `dim_assets` tables.

#### Risk Models
| Model | Function | Crypto Fit |
|---|---|---|
| Exponentially weighted | `exp_cov(span=180)` | Short span (30-90) for regime shifts |
| Semicovariance | `semicovariance(benchmark=0)` | Downside-only risk |
| Ledoit-Wolf shrinkage | `.ledoit_wolf()` | Reduces estimation error |
| Min Covariance Determinant | `min_cov_determinant()` | Robust to outliers |

#### Integration Path
- `cmc_features` signals produce per-asset mu vector → `EfficientFrontier(mu, S)`
- `cmc_returns_bars_multi_tf_u` provides returns for covariance estimation
- `cmc_regimes` L0-L2 labels switch optimizer: bear → `EfficientCVaR`, stable → `EfficientFrontier`
- `DiscreteAllocation` converts weights to actionable quantities

---

### 1.2 QuantStats Tear Sheets (from QuantStats)

**Gap**: `cmc_backtest_metrics` stores ~15 metrics. No HTML reports, no benchmark comparison, missing key ratios.

**Metrics missing from current schema**:
- `omega_ratio` — gains/losses above threshold (fat-tail aware)
- `smart_sharpe` / `smart_sortino` — autocorrelation-adjusted (crypto has strong momentum autocorrelation)
- `probabilistic_sharpe_ratio` — statistical significance of Sharpe given sample size
- `kelly_criterion` — optimal position sizing fraction
- `ulcer_index` / `ulcer_performance_index` — drawdown depth+duration composite
- `skewness`, `kurtosis` — return distribution shape
- `tail_ratio` — right vs left tail magnitude
- `recovery_factor` — total return / max drawdown
- `serenity_index` — composite risk-adjusted measure
- `risk_of_ruin` — probability of losing all capital
- `consecutive_wins` / `consecutive_losses` — streak statistics
- `alpha`, `beta`, `correlation` — vs BTC benchmark

**HTML tear sheet generation**:
```python
import quantstats as qs
qs.reports.html(returns_series, benchmark=btc_returns,
                output="strategy_report.html", title="RSI Mean-Revert BTC 1D")
```
Self-contained HTML with 18 embedded charts: cumulative returns, drawdown, monthly heatmap, rolling Sharpe/Sortino/beta, distribution histogram, Monte Carlo paths, etc.

**Integration path**: vectorbt daily returns → `qs.stats.*` functions. BTC benchmark from `cmc_price_bars_multi_tf WHERE tf='1D' AND id=<btc_id>`.

---

### 1.3 Triple Barrier Labeling + Meta-Labeling (from MLFinLab)

**Gap**: Fixed-horizon return labels in `cmc_returns_*`. No adaptive exit logic.

**Triple barrier method** (Chapter 3 of AFML):
1. **Profit-taking barrier**: close when return exceeds `pt * daily_vol`
2. **Stop-loss barrier**: close when return drops below `-sl * daily_vol`
3. **Vertical barrier**: close after N bars (max holding period)
4. Label = which barrier was hit first: {+1 profit, -1 stop, 0 timeout}

**Meta-labeling** (two-model approach):
- Primary model: picks direction (long/short) — your existing EMA crossover, RSI, breakout signals
- Secondary model (typically Random Forest): predicts whether to trade {0, 1}
- Size by confidence: `position_size = predicted_probability`
- Dramatically reduces false positives while maintaining recall

```python
# Step 1: Define barriers
vertical_barriers = add_vertical_barrier(t_events, close, num_days=5)
# Step 2: Get events
events = get_events(close, t_events, pt_sl=[1.5, 1.0], target=daily_vol,
                    min_ret=0.01, side_prediction=signal_direction)
# Step 3: Get labels
labels = get_bins(events, close)
```

---

### 1.4 Purged K-Fold / CPCV Cross-Validation (from MLFinLab + VectorBT PRO)

**Gap**: No cross-validation on backtests. Current vectorbt pipeline likely leaks when labels overlap.

**PurgedKFold**:
- Standard K-Fold with purging (removes training samples whose labels span test period)
- Embargo (drops a time buffer after each test fold)
- Prevents data leakage when using multi-bar holding periods

**CombinatorialPurgedKFold (CPCV)**:
```python
cv = CombinatorialPurgedKFold(
    n_splits=6,          # N: total folds
    n_test_splits=2,     # k: test folds per split
    samples_info_sets=info_sets,  # label start→end mapping
    pct_embargo=0.01
)
# Generates C(6,2)=15 splits → ~6.67 backtest paths
# Distribution of OOS performance estimates → statistical tests on Sharpe
```

**Why critical**: Your signal generators (RSI, EMA crossover, ATR breakout) use multi-bar features. Without purging, train/test contamination inflates performance metrics.

---

### 1.5 IC / Rank IC / Quintile Analysis (from Qlib)

**Gap**: IC exists in `cmc_ic_results` but basic.

**What to add**:

| Metric | Description | Implementation |
|---|---|---|
| **Rank IC** | Spearman rank correlation (robust to outliers) | `scipy.stats.spearmanr(feature_rank, return_rank)` |
| **ICIR** | IC / std(IC) — risk-adjusted IC | Rolling IC series → mean/std |
| **IC decay** | IC at horizons 1/2/5/10/20 bars | Loop around current logic with variable forward return |
| **Quintile group returns** | Rank all assets into 5 buckets by factor, track cumulative return per bucket | Reveals monotonicity — the gold standard for factor validation |
| **Monthly IC heatmap** | IC grouped by month for seasonal analysis | `pd.groupby(month)` on IC series |
| **Long-short spread** | Top quintile return minus bottom quintile | Direct alpha measurement |

**Quintile analysis** is the most efficient way to validate whether a factor has monotonic predictive power across the crypto universe without running full backtests.

---

### 1.6 Cross-Sectional Normalization (from Qlib)

**Gap**: ta_lab2 has time-series z-scores (`_zscore_30/90/365`). No cross-sectional normalization.

**CSZScoreNorm**: normalize each asset relative to all assets at same timestamp
```sql
-- Cross-sectional z-score as a SQL window function
(value - AVG(value) OVER (PARTITION BY ts, tf)) / NULLIF(STDDEV(value) OVER (PARTITION BY ts, tf), 0)
```

**CSRankNorm**: rank-based cross-sectional normalization
```sql
PERCENT_RANK() OVER (PARTITION BY ts, tf ORDER BY value)
```

These are complementary to existing time-series z-scores. Essential for multi-asset ranking and factor-neutral portfolio construction.

---

## TIER 2 — Medium Impact, Solid Additions

### 2.1 Fractional Differentiation (from MLFinLab)

**Problem**: Returns (d=1) destroy memory. Raw prices (d=0) are non-stationary. Both are bad for ML.

**Solution**: `frac_diff_ffd(series, d=0.35)` — stationary with memory preserved. d≈0.3-0.5 is the sweet spot.

```python
from mlfinlab.features.fracdiff import FractionalDifferentiation
fd = FractionalDifferentiation()
stationary_prices = fd.frac_diff_ffd(close_series, diff_amt=0.4, thresh=1e-5)
```

`plot_min_ffd(series)` finds the minimum d that achieves stationarity (ADF test). Add as feature columns in `cmc_features`.

---

### 2.2 SADF Bubble Detection (from MLFinLab)

**What**: Supremum Augmented Dickey-Fuller test detects explosive price behavior.

```python
sadf_values = get_sadf(price_series, model='linear', lags=5, min_length=50)
# High SADF → explosive/bubble behavior
```

**Integration**: Feed into `cmc_regimes` as additional regime signal. Crypto bubble cycles (2017, 2021, etc.) would show clear SADF spikes.

---

### 2.3 Expression Engine for Factors (from Qlib)

**What**: Config-driven factor definitions as strings, parsed at runtime.

```yaml
# Instead of hardcoded Python per factor:
factors:
  macd_signal: "EMA($close, 12) / EMA($close, 26) - 1"
  momentum_5d: "Ref($close, 0) / Ref($close, 5) - 1"
  vol_ratio: "Std($close, 5) / Std($close, 20)"
```

**Integration**: Maps to the feature experimentation framework design in `feature_experimentation.md`. Eliminates code changes for new factor experiments.

---

### 2.4 Kyle/Amihud Lambda — Market Impact (from MLFinLab)

**What**: Bar-based microstructural features from OHLCV + volume (no tick data needed).

| Feature | Formula | Meaning |
|---|---|---|
| Kyle lambda | `regress(delta_price, volume)` | Price impact per volume unit |
| Amihud lambda | `abs(return) / dollar_volume` | Illiquidity ratio |
| Hasbrouck lambda | `regress(delta_price, signed_sqrt(dollar_volume))` | Signed price impact |

**Integration**: Computable from existing `cmc_price_bars_multi_tf` + volume. Add as columns in `cmc_features`.

---

### 2.5 MAE/MFE Trade Analysis (from VectorBT PRO)

**What**: Maximum Adverse Excursion / Maximum Favorable Excursion per trade.

- **MAE**: How far did each trade go against you before closing?
- **MFE**: How far did each trade go in your favor before closing?

**Reveals**: Whether stops are too tight (MAE clusters near stop) or profits left on the table (MFE >> actual exit).

**Integration**: Add `mae` and `mfe` columns to `cmc_backtest_trades` table.

---

### 2.6 Probability-Based Bet Sizing (from MLFinLab)

**What**: Maps classifier confidence to fractional position size.

```python
bet_size = bet_size_probability(events, prob=model_confidence,
                                 num_classes=3, step_size=0.1,
                                 average_active=True)
```

**Integration**: Signal generators already produce directional signals. Add confidence scoring, then map to position size via sigmoid/step function.

---

### 2.7 Black-Litterman with CMC Market Caps (from PyPortfolioOpt)

```python
from pypfopt import BlackLittermanModel, market_implied_prior_returns

# Prior from market caps
pi = market_implied_prior_returns(market_caps, risk_aversion=1, cov_matrix=S)

# Views from your signals
P = np.array([[1, 0, -1, 0, ...]])  # BTC outperforms SOL
Q = np.array([0.15])                 # by 15%

bl = BlackLittermanModel(S, pi=pi, P=P, Q=Q)
posterior_mu = bl.bl_returns()
posterior_cov = bl.bl_cov()

ef = EfficientFrontier(posterior_mu, posterior_cov)
weights = ef.max_sharpe()
```

---

### 2.8 Monte Carlo Trade Resampling (from Jesse)

**What**: Resample completed trades N=1000 times, compute confidence intervals on Sharpe/CAGR.

```python
# From cmc_backtest_trades, resample with replacement
for _ in range(1000):
    sample = trades_df.sample(n=len(trades_df), replace=True)
    sharpe_dist.append(compute_sharpe(sample))
ci_95 = np.percentile(sharpe_dist, [2.5, 97.5])
```

Low-effort anti-overfitting check. ~50 lines of Python against existing `cmc_backtest_trades` table.

---

### 2.9 CUSUM Event Filter (from MLFinLab)

**What**: Event-driven sampling — only generate signals when cumulative deviation crosses threshold.

```python
from mlfinlab.filters.filters import cusum_filter
events = cusum_filter(close_series, threshold=daily_vol * 2)
# Returns timestamps where cumsum crosses threshold
```

**Integration**: Feed event timestamps into signal generators. Reduces noise trades in RSI/EMA/breakout signals.

---

## TIER 3 — Lower Priority, Future Roadmap

### 3.1 TopkDropout Portfolio Strategy (from Qlib)

Hold top K assets by signal score, each period sell bottom-ranked and buy top-ranked. Generates controlled turnover rate of `2 * dropout_rate / K`. Natural multi-asset upgrade to per-asset backtesting.

### 3.2 MDA Feature Importance (from MLFinLab)

Permutation-based importance with purged CV. Identify which of 112 `cmc_features` columns actually predict returns. Uses `PurgedKFold` internally for valid OOS importance estimates. Supports clustered feature importance for correlated features (e.g., multiple EMA periods).

### 3.3 Entropy Features (from MLFinLab)

Shannon/Lempel-Ziv/Kontoyiannis entropy on encoded price series. Measures market predictability/randomness. Novel feature class not in current pipeline:
```python
encoded = quantile_mapping(close_array, num_letters=26)
entropy = get_lempel_ziv_entropy(encoded)  # Low = predictable, High = random
```

### 3.4 Trend Scanning Labels (from MLFinLab)

OLS regression on expanding windows; t-value at max |t-stat| defines label. Sign(t-value) for classification, raw t-value as sample weight. Alternative to triple barrier for trend-following strategies.

### 3.5 Regime-Routed Models / TRA (from Qlib)

Temporal Routing Adaptor: routes samples to specialized sub-models per regime. Your `cmc_regimes` L0-L2 labels → mean-reversion model in sideways regime, momentum model in trending regime.

### 3.6 Stop Laddering (from VectorBT PRO)

Array of incremental exit stops to scale out of positions:
```python
sl_stop = [0.02, 0.03, 0.05]  # Scale out at 2%, 3%, 5% adverse move
tp_stop = [0.03, 0.05, 0.10]  # Scale out at 3%, 5%, 10% favorable move
```
Extends ATR breakout signal generator.

### 3.7 Optuna + Ray Optimization (from Jesse)

Replace grid search with Tree-structured Parzen Estimator for intelligent hyperparameter search. Resumable across sessions, distributed via Ray workers.

### 3.8 Codependence — Mutual Information, Distance Correlation (from MLFinLab)

Non-linear dependency measures between assets/TFs. Complements Pearson correlation in `cmc_regime_comovement`:
- Distance correlation (detects non-linear relationships)
- Mutual information / variation of information
- Wasserstein distance (optimal transport)

### 3.9 DoubleEnsemble / ADARNN (from Qlib)

ML models explicitly designed for concept drift. `DoubleEnsemble` uses double ensemble across time; `ADARNN` adapts RNN hidden states to non-stationary distributions. Relevant for crypto bull/bear regime shifts.

### 3.10 Experiment Tracking / MLflow (from Qlib)

`cmc_backtest_runs` tracks results but not full experiment configurations. MLflow or lightweight PostgreSQL equivalent enables:
- Hyperparameter config → metrics mapping
- Experiment comparison dashboards
- Reproducibility via `QlibRecorder` pattern

---

## Quick Wins (1-2 days each)

| # | Feature | Source | Effort | Implementation |
|---|---|---|---|---|
| 1 | **QuantStats HTML reports** | QuantStats | 4h | `pip install quantstats`, vectorbt returns → `qs.reports.html()` |
| 2 | **Cross-sectional z-scores** | Qlib | 4h | SQL window function: `(val - AVG OVER ts,tf) / STDDEV OVER ts,tf` |
| 3 | **IC decay** | Qlib | 4h | Extend IC computation to 2/5/10/20-bar forward return horizons |
| 4 | **Monte Carlo on trades** | Jesse | 4h | Resample `cmc_backtest_trades` N=1000, compute Sharpe CI |
| 5 | **Kelly criterion** | QuantStats | 1h | `win_rate * avg_win/avg_loss - (1-win_rate)` — inputs already in `cmc_backtest_metrics` |
| 6 | **Fractional differentiation** | MLFinLab | 4h | `pip install fracdiff`, apply to close prices |

---

## What NOT to Copy

| Repo/Feature | Reason |
|---|---|
| **Qlib's binary flat-file storage** | Already have PostgreSQL with proper indexing |
| **Jesse's event-driven backtest engine** | Already have vectorbt (10-100x faster) |
| **StockSharp C# framework** | Wrong language ecosystem |
| **QuantLib derivatives pricing** | Irrelevant for crypto spot/perps |
| **OpenBB terminal UI** | Different product category (data terminal vs research platform) |
| **TensorFlow Quant Finance** | Derivatives/pricing focused, GPU overkill for current pipeline |

---

## Detailed Source Research

### Microsoft Qlib (37.8k stars)

**Expression Engine** — flagship feature. Factor definitions as declarative strings:
| Operator | Description |
|---|---|
| `Ref($close, N)` | Lookback N bars |
| `Delta($close, N)` | N-period difference |
| `Mean($close, N)` / `Std($close, N)` | Rolling mean/std |
| `EMA($close, N)` / `WMA($close, N)` | Moving averages |
| `Rank($close, N)` | Rolling percentile rank |
| `Corr($close, $volume, N)` | Rolling correlation |
| `Slope($close, N)` / `Rsquare($close, N)` | Linear regression |
| `Skew($close, N)` / `Kurt($close, N)` | Higher moments |
| Arithmetic, conditional, unary | Full operator set |

**Canonical Feature Sets**:
- **Alpha158**: ~158 factors from OHLCV — standard benchmark
- **Alpha360**: ~360 factors — extended set

**Preprocessors**: ZscoreNorm, CSZScoreNorm, CSRankNorm, MinMaxNorm, DropnaProcessor, DropInf, RobustNorm

**ML Models shipped** (20+): LightGBM, XGBoost, CatBoost, LSTM, ALSTM, GRU, Transformer, Localformer, TFT, TCN, TabNet, DoubleEnsemble, ADARNN, HIST, GATs, TRA, TCTS, DDG-DA, PPO (RL)

**Portfolio Strategies**: TopkDropoutStrategy, EnhancedIndexingStrategy (QP optimizer with tracking error constraint), WeightStrategyBase, TWAPStrategy

**Evaluation**: IC, ICIR, Rank IC, Rank ICIR, IC decay (1-20d), monthly IC, quintile group returns, long-short spread, turnover rate, cumulative returns vs benchmark, drawdown, Q-Q plot

**Experiment Management**: MLflow-backed QlibRecorder, hierarchical experiment→recorder→run structure

---

### PyPortfolioOpt (5.5k stars)

**Optimizers**: EfficientFrontier (mean-variance), HRPOpt (hierarchical risk parity), CLA (critical line algorithm), EfficientSemivariance, EfficientCVaR, EfficientCDaR, BlackLittermanModel

**Constraints**: weight bounds (per-asset), sector/group constraints, market neutral, L2 regularization, transaction cost penalty, tracking error objectives

**Expected Returns**: mean_historical_return (geometric/arithmetic), ema_historical_return, capm_return, custom mu vector

**Risk Models**: sample_cov, semicovariance, exp_cov, Ledoit-Wolf (3 shrinkage targets), Oracle Approximating Shrinkage, Min Covariance Determinant

**Discrete Allocation**: greedy_portfolio (fast, near-optimal) and lp_portfolio (integer programming, exact)

**Plotting**: efficient frontier curve, covariance/correlation heatmap, dendrogram (HRP), weight bar chart

---

### QuantStats (6.8k stars)

**60+ metrics across categories**:
- Returns: CAGR, comp, geometric mean, best/worst period, exposure, RAR
- Risk-adjusted: Sharpe, smart_sharpe, Sortino, smart_sortino, Calmar, Omega, Treynor, UPI, serenity_index
- Probabilistic: probabilistic_sharpe_ratio, probabilistic_sortino_ratio
- Win/loss: win_rate, avg_win/loss, consecutive_wins/losses, payoff_ratio, profit_factor, gain_to_pain, CPC index, common_sense_ratio
- Tail risk: VaR, CVaR/expected_shortfall, tail_ratio
- Drawdown: max_drawdown, to_drawdown_series, ulcer_index, recovery_factor
- Volatility: annualized vol, implied_vol, rolling_vol, autocorr_penalty
- Distribution: skew, kurtosis, outlier_win/loss_ratio
- Sizing: kelly_criterion, risk_of_ruin
- Monte Carlo: bust_probability, goal_probability

**18 plot types**: snapshot, cumulative returns, log returns, daily/yearly returns, distribution, drawdown, drawdown periods, rolling beta/vol/Sharpe/Sortino, monthly heatmap, Monte Carlo

**HTML tear sheet**: self-contained file with all metrics + charts + benchmark comparison

---

### MLFinLab (4.6k stars) — "Advances in Financial Machine Learning"

**Data Structures (Bars)**:
- Standard: tick bars, volume bars, dollar bars, time bars
- Imbalance: EMA/Const dollar/volume/tick imbalance bars (sample when order flow imbalance high)
- Run: EMA/Const dollar/volume/tick run bars (sample on directional runs)

**Labeling**:
- Triple barrier method (profit-taking + stop-loss + vertical barrier)
- Meta-labeling (primary model → direction, secondary → trade/no-trade)
- Trend scanning (OLS t-value based)
- Tail sets (cross-sectional extreme performers)
- Fixed time horizon, excess over mean/median, raw return, vs benchmark, matrix flags, bull/bear

**Feature Importance**:
- MDI (Mean Decrease Impurity) — fast, in-sample, biased
- MDA (Mean Decrease Accuracy) — OOS, permutation-based, reliable
- SFI (Single Feature Importance) — each feature trained alone
- Clustered Feature Importance — group correlated features
- Stacked multi-asset variants

**Bet Sizing**:
- Probability-based (ML output → position size)
- Dynamic (price forecast deviation → sigmoid/power sizing)
- Budget-based (concurrent position balancing)
- Reserve-based (EF3M Gaussian mixture → data-driven sizing)

**Structural Breaks**:
- SADF (Supremum ADF) — bubble/explosive behavior detection
- Chow-type Dickey-Fuller — unknown breakpoint detection
- Chu-Stinchcombe-White CUSUM — mean-shift detection

**Cross-Validation**:
- PurgedKFold — purging + embargo
- CombinatorialPurgedKFold — C(N,k) splits, multiple backtest paths
- StackedCombinatorialPurgedKFold — multi-asset variant

**Microstructural Features**:
- First generation (from OHLCV): Roll measure, Corwin-Schultz spread, Bekker-Parkinson vol
- Second generation (market impact): Kyle/Amihud/Hasbrouck lambda (bar-based and trade-based)
- Third generation: VPIN (Volume-Synchronized Probability of Informed Trading)
- Entropy: Shannon, Plug-in, Lempel-Ziv, Kontoyiannis

**Other**:
- Fractional differentiation (stationary prices with memory)
- CUSUM filter (event-driven sampling)
- Sequential bootstrapping (uniqueness-weighted draws)
- Sample weighting (by return magnitude or time decay)
- Codependence: distance correlation, mutual information, variation of information, Wasserstein distance

---

### VectorBT PRO (6.7k stars)

**Portfolio simulation**: Market + limit + stop orders with TIF variants, long/short, leverage (lazy/eager), cash deposits/withdrawals, DCA, dividend reinvestment, bar skipping, dynamic signal callbacks

**Parameter optimization**: Grid + random search, `run_combs()`, conditional parameters, lazy grids, walk-forward CV with purging, CPCV, Splitter class (rolling/expanding/anchored/random windows)

**Parallelization**: `@vbt.iterated`, multithreading, Ray multiprocessing, chunk caching

**Indicator factory**: 500+ indicators, Numba-accelerated, parameter broadcasting, multi-timeframe, indicator expressions

**Analysis**: MAE/MFE, edge ratio, pattern detection, event projections, heatmaps with sliders, GIF animation

**Performance**: 1M orders in 70-100ms, rolling Sortino 1000x faster than QuantStats

---

### Jesse (7.5k stars)

**Strategy framework**: Pure Python class with method overrides (`should_long`, `go_long`, etc.), 300+ Rust-compiled indicators, hyperparameter definition in strategy class

**Routes**: `(exchange, symbol, timeframe, strategy_class)` tuples, multiple routes simultaneously

**Multi-TF**: 1-minute base candles, auto-aggregation to higher TFs, `self.get_candles()` API

**Orders**: Market, limit, stop, bracket. Partial fills via arrays: `self.buy = [(qty1, price1), (qty2, price2)]`

**Risk**: `self.risk(2, entry, stop)` — size position for 2% max loss. Stop/TP automation.

**Optimization**: Optuna (TPE) + Ray distributed workers. Objective: Sharpe/Calmar/Sortino/Omega. Resumable to SQLite.

**Anti-overfitting**: Monte Carlo trade resampling + walk-forward CV

**Live trading**: WebSocket feeds, REST order submission, web dashboard (Nuxt.js + FastAPI), Telegram/Slack/Discord notifications
