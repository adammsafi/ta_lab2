# Phase 59: Microstructural & Advanced Features - Research

**Researched:** 2026-02-27
**Domain:** Quantitative microstructure, stationarity-preserving transforms, statistical hypothesis testing, information theory
**Confidence:** HIGH

---

## Summary

Phase 59 adds five classes of advanced features to `cmc_features`: fractional differentiation, liquidity impact measures (Kyle/Amihud/Hasbrouck lambda), rolling ADF-based bubble detection, entropy features, and non-linear codependence measures. All five feature classes originate from MLFinLab's implementation of "Advances in Financial Machine Learning" (Lopez de Prado, 2018).

The critical prior decision is that mlfinlab cannot be installed (requires numpy<1.27; project has numpy 2.4.1). All algorithms must be reimplemented from scratch. This has been verified: every required algorithm is implementable using the project's existing stack (numpy 2.4.1, scipy 1.17.0, pandas 2.3.3, sklearn 1.8.0). No new mandatory dependencies are required, though `statsmodels` can optionally be added for proper ADF p-values with MacKinnon critical values.

The standard implementation pattern follows `vol_feature.py` — a `BaseFeature` subclass with `load_source_data`, `compute_features`, `get_output_schema`, `get_feature_columns`. New feature columns are added to `cmc_features` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` SQL migration. The non-linear codependence measures (MICRO-05) require a new table (`cmc_codependence`) because they are pairwise asset metrics, not per-bar features.

**Primary recommendation:** Implement all five feature classes as self-contained Python modules in `src/ta_lab2/features/microstructure.py`, then wire each into a dedicated refresh script following the `refresh_cmc_vol_daily.py` pattern. True SADF (O(n^2)) is infeasible for daily refresh — use rolling ADF (63-bar window) as the per-bar proxy stored in `cmc_features`, and offer a one-time historical SADF computation script for bubble retrospective analysis.

---

## Standard Stack

The established libraries for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.4.1 (installed) | FFD weights, distance correlation, entropy, matrix ops | Already project-wide; no install needed |
| scipy | 1.17.0 (installed) | `scipy.linalg.lstsq` for OLS (ADF/Kyle/Hasbrouck), `scipy.stats.linregress` for rolling regression | Already installed; provides numerically stable linear algebra |
| sklearn | 1.8.0 (installed) | `mutual_info_regression` for MI estimation via k-NN | Already installed; handles continuous MI correctly |
| pandas | 2.3.3 (installed) | Rolling windows, groupby, DataFrame I/O | Project standard |

### Optional Addition
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| statsmodels | 0.14.6 (installable, no conflicts) | `adfuller()` with proper MacKinnon critical values and p-values | If precise ADF p-values are needed for auto-tuning d in MICRO-01 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom FFD | `fracdiff` pip package | `fracdiff` pip package works but adds dependency; custom FFD is ~30 lines of numpy and verified to work |
| sklearn MI | `dcor` pip package | `dcor` handles distance correlation more elegantly but is not installed; numpy implementation verified at 140ms/pair |
| Custom ADF | `statsmodels.tsa.stattools.adfuller` | MacKinnon p-values are more accurate; custom OLS is sufficient for ADF t-stat threshold (>1.5 for explosive) |

**Installation (if adding statsmodels):**
```bash
pip install statsmodels
```

---

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── features/
│   └── microstructure.py          # Core math: FFD, lambdas, ADF, entropy, codependence
├── scripts/features/
│   ├── microstructure_feature.py  # BaseFeature subclass: MICRO-01, MICRO-02, MICRO-03, MICRO-04
│   └── codependence_feature.py    # Standalone script: MICRO-05 (pairwise, not per-bar)
sql/
└── migration/
    └── add_microstructure_to_features.sql   # ALTER TABLE cmc_features ADD COLUMN IF NOT EXISTS
    └── create_cmc_codependence.sql          # New table for pairwise MI/dcor
```

### Pattern 1: Fractional Differentiation (FFD) — MICRO-01

**What:** Applies fractional difference operator with order d to close prices, preserving memory while achieving stationarity. d=0 is raw price (non-stationary), d=1 is returns (no memory). d≈0.35-0.45 is the empirical sweet spot for crypto.

**When to use:** Pre-processing close prices for ML features. Auto-tune d per asset by finding minimum d that passes ADF stationarity test (t-stat < -2.9 for 5% significance in 252-bar windows).

**Implementation (verified working):**
```python
# Source: manual implementation, verified against AFML Chapter 5
def ffd_weights(d: float, size: int = 1000, threshold: float = 1e-2) -> np.ndarray:
    """Fixed-width window fractional differentiation weights.

    threshold=1e-2 gives ~12 weights for d=0.4 (practical window size).
    threshold=1e-5 gives full series length (impractical).
    Use 1e-2 for daily refresh; 1e-4 for research.
    """
    w = [1.0]
    for k in range(1, size):
        w_ = -w[-1] / k * (d - k + 1)
        w.append(w_)
        if abs(w_) < threshold:
            break
    return np.array(w)

def frac_diff_ffd(series: np.ndarray, d: float = 0.4, threshold: float = 1e-2) -> np.ndarray:
    """Apply FFD to price series. Returns NaN for first (width-1) bars."""
    w = ffd_weights(d, size=len(series), threshold=threshold)
    width = len(w)
    result = np.full(len(series), np.nan)
    for t in range(width - 1, len(series)):
        result[t] = np.dot(w[::-1], series[t - width + 1:t + 1])
    return result

def find_min_d_adf(series: np.ndarray, d_range=(0.0, 1.0), n_steps=10,
                   adf_threshold=-2.9) -> float:
    """Find minimum d achieving stationarity (ADF t-stat < adf_threshold).

    Uses OLS-based ADF without statsmodels. If statsmodels available,
    use adfuller() for proper MacKinnon p-values.
    """
    for d in np.linspace(d_range[0], d_range[1], n_steps):
        fd = frac_diff_ffd(series, d=d)
        fd_valid = fd[~np.isnan(fd)]
        if len(fd_valid) < 30:
            continue
        t_stat = _adf_tstat(fd_valid, lags=1)
        if t_stat < adf_threshold:
            return round(d, 3)
    return 1.0  # fallback to returns
```

**Columns added to cmc_features:**
- `close_fracdiff DOUBLE PRECISION` — FFD-transformed close price
- `close_fracdiff_d DOUBLE PRECISION` — the d parameter used (asset-specific, stored per-bar)

### Pattern 2: Liquidity Impact Measures — MICRO-02

**What:** Three market microstructure proxies computed from OHLCV bars (no tick data needed). All use rolling OLS regression or simple arithmetic over a 20-bar window.

**Implementation (verified working):**
```python
# Source: manual implementation, verified with scipy.stats

def amihud_lambda(close: np.ndarray, volume: np.ndarray,
                  window: int = 20) -> np.ndarray:
    """Amihud (2002) illiquidity ratio: |return| / dollar_volume."""
    ret = np.abs(np.diff(np.log(close + 1e-10)))
    dollar_vol = close[1:] * volume[1:]
    ratio = ret / (dollar_vol + 1.0)  # +1 avoids div/zero
    # Rolling mean
    result = np.full(len(close), np.nan)
    for t in range(window, len(ret)):
        result[t + 1] = ratio[t - window + 1:t + 1].mean()
    return result

def kyle_lambda(close: np.ndarray, volume: np.ndarray,
                window: int = 20) -> np.ndarray:
    """Kyle (1985) lambda: OLS(delta_price ~ signed_volume)."""
    from scipy.stats import linregress
    delta_p = np.diff(close)
    signed_vol = volume[1:] * np.sign(delta_p)
    result = np.full(len(close), np.nan)
    for t in range(window, len(delta_p)):
        dp = delta_p[t - window:t]
        sv = signed_vol[t - window:t]
        slope, _, _, _, _ = linregress(sv, dp)
        result[t + 1] = slope
    return result

def hasbrouck_lambda(close: np.ndarray, volume: np.ndarray,
                     window: int = 20) -> np.ndarray:
    """Hasbrouck (2009): OLS(delta_price ~ signed_sqrt(dollar_volume))."""
    from scipy.stats import linregress
    delta_p = np.diff(close)
    dollar_vol = close[1:] * volume[1:]
    signed_sqrt_dv = np.sign(delta_p) * np.sqrt(np.abs(delta_p * dollar_vol[: len(delta_p)]))
    result = np.full(len(close), np.nan)
    for t in range(window, len(delta_p)):
        dp = delta_p[t - window:t]
        x = signed_sqrt_dv[t - window:t]
        slope, _, _, _, _ = linregress(x, dp)
        result[t + 1] = slope
    return result
```

**Columns added to cmc_features:**
- `kyle_lambda DOUBLE PRECISION`
- `amihud_lambda DOUBLE PRECISION`
- `hasbrouck_lambda DOUBLE PRECISION`

### Pattern 3: Rolling ADF as SADF Proxy — MICRO-03

**What:** Supremum ADF (SADF) is theoretically the maximum ADF t-statistic over all expanding sub-samples from t0 to t. True SADF is O(n^2) and requires ~348s per asset for 1460 bars — infeasible for daily refresh.

**Practical implementation:** Rolling ADF on a 63-bar fixed window. For each bar t, compute ADF t-statistic on log(close[t-63:t]). This detects local explosive price behavior without the O(n^2) cost. Store as `adf_stat_63` in `cmc_features`. Threshold > 1.5 (approximately 5% significance) indicates explosive/bubble behavior.

**SADF critical values (approximate, from Phillips-Wu-Yu 2011, Table 1):**
- 10% significance: ~1.25
- 5% significance: ~1.50
- 1% significance: ~2.10

**Implementation (verified working, 0.5s per 1460-bar asset):**
```python
# Source: manual implementation based on ADF OLS formulation

def adf_tstat(log_prices: np.ndarray, lags: int = 1) -> float:
    """ADF t-statistic via OLS. Returns NaN if insufficient data."""
    dy = np.diff(log_prices)
    n = len(dy)
    if n < lags + 5:
        return np.nan
    y = dy[lags:]
    y_lag = log_prices[lags:-1]
    X = np.column_stack([np.ones(len(y_lag)), y_lag])
    for i in range(1, lags + 1):
        lag_col = dy[lags - i:n - i]
        min_len = min(len(y), len(lag_col))
        X = X[:min_len]
        y = y[:min_len]
        X = np.column_stack([X, lag_col[:min_len]])
    if len(y) < X.shape[1] + 3:
        return np.nan
    beta, _, _, _ = scipy.linalg.lstsq(X, y, check_finite=False)
    resid = y - X @ beta
    s2 = np.dot(resid, resid) / max(1, len(y) - X.shape[1])
    cov = s2 * np.linalg.pinv(X.T @ X)
    return beta[1] / np.sqrt(max(cov[1, 1], 1e-20))

def rolling_adf(log_prices: np.ndarray, window: int = 63, lags: int = 1) -> np.ndarray:
    """Rolling ADF t-statistic. Stored as sadf_stat in cmc_features."""
    result = np.full(len(log_prices), np.nan)
    for t in range(window, len(log_prices)):
        result[t] = adf_tstat(log_prices[t - window:t + 1], lags=lags)
    return result
```

**Columns added to cmc_features:**
- `sadf_stat DOUBLE PRECISION` — rolling 63-bar ADF t-statistic
- `sadf_is_explosive BOOLEAN` — True when sadf_stat > 1.5 (5% approximate significance)

**Regime integration:** `sadf_is_explosive` is stored in `cmc_features`. The regime pipeline (`refresh_cmc_regimes.py`) can LEFT JOIN `cmc_features` to read this flag — no changes to `cmc_regimes` DDL required. A separate one-time script can compute true expanding SADF for historical bubble labeling.

### Pattern 4: Entropy Features — MICRO-04

**What:** Encode return series as discrete symbols (quantile binning), then compute information-theoretic complexity. Low entropy = predictable patterns. High entropy = random / efficient market.

**Critical implementation note:** Entropy must be computed on RETURN series (not price levels) in a rolling window. Computing on price levels produces uniform distributions regardless of trend/mean-reversion structure. Rolling window of 50 bars is practical.

**Implementation (verified working — rolling LZ detects predictable patterns):**
```python
# Source: manual implementation based on AFML Chapter 18 encoding approach

def quantile_encode(arr: np.ndarray, n_bins: int = 10) -> np.ndarray:
    """Map continuous values to discrete symbols via quantile binning."""
    quantiles = np.percentile(arr, np.linspace(0, 100, n_bins + 1))
    quantiles = np.unique(quantiles)
    return np.digitize(arr, quantiles[1:-1])

def shannon_entropy(encoded: np.ndarray) -> float:
    """Shannon entropy in nats."""
    _, counts = np.unique(encoded, return_counts=True)
    probs = counts / counts.sum()
    return -np.sum(probs * np.log(probs + 1e-12))

def lempel_ziv_complexity(s: list) -> int:
    """Lempel-Ziv complexity: count of distinct sub-phrases."""
    n = len(s)
    complexity, prefix_set, current = 1, set(), []
    for i in range(1, n):
        current.append(s[i])
        sub = tuple(current)
        if sub not in prefix_set:
            complexity += 1
            prefix_set.add(sub)
            current = []
    return complexity

def rolling_entropy(returns: np.ndarray, window: int = 50,
                    n_bins: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Rolling Shannon + LZ entropy on encoded return windows.

    Returns: (shannon_vals, lz_vals) both shape (len(returns),)
    """
    encoded = quantile_encode(returns, n_bins=n_bins)
    shannon = np.full(len(returns), np.nan)
    lz = np.full(len(returns), np.nan)
    for t in range(window, len(returns)):
        w = encoded[t - window:t]
        shannon[t] = shannon_entropy(w)
        lz[t] = lempel_ziv_complexity(list(w)) / np.log2(window)
    return shannon, lz
```

**Columns added to cmc_features:**
- `entropy_shannon DOUBLE PRECISION` — Shannon entropy of 50-bar return window
- `entropy_lz DOUBLE PRECISION` — Lempel-Ziv complexity (normalized) of 50-bar return window

### Pattern 5: Non-Linear Codependence — MICRO-05

**What:** Pairwise distance correlation and mutual information between assets. These detect non-linear statistical dependence invisible to Pearson correlation. Cannot be stored as per-bar columns in `cmc_features` (pairwise structure). Requires a dedicated table `cmc_codependence`.

**Performance (verified):**
- Mutual information (sklearn): 23ms per pair at n=1460 bars
- Distance correlation (numpy): 140ms per pair at n=1460 bars, 34MB RAM per pair

**Scale constraint:** Full all-vs-all for 50 assets = 1225 pairs. MI sweep = 28s. Distance corr sweep = 3 minutes. Tractable if run separately from daily refresh.

**Implementation (verified working):**
```python
# Mutual information: use sklearn (k-NN estimator, handles continuous)
from sklearn.feature_selection import mutual_info_regression

def pairwise_mi(x: np.ndarray, y: np.ndarray, n_neighbors: int = 3) -> float:
    """Mutual information between two continuous series."""
    return mutual_info_regression(
        x.reshape(-1, 1), y, n_neighbors=n_neighbors, random_state=42
    )[0]

# Distance correlation: pure numpy (verified, no dcor package needed)
def distance_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Szekely (2007) distance correlation. Zero iff independent."""
    n = len(x)
    a = np.abs(x[:, None] - x[None, :])
    b = np.abs(y[:, None] - y[None, :])
    A = a - a.mean(0, keepdims=True) - a.mean(1, keepdims=True) + a.mean()
    B = b - b.mean(0, keepdims=True) - b.mean(1, keepdims=True) + b.mean()
    dcov2 = (A * B).mean()
    dvar_x = (A * A).mean()
    dvar_y = (B * B).mean()
    denom = np.sqrt(dvar_x * dvar_y)
    return float(np.sqrt(max(0, dcov2) / denom)) if denom > 0 else 0.0

def variation_of_information(x_encoded: np.ndarray, y_encoded: np.ndarray) -> float:
    """Variation of information: H(X|Y) + H(Y|X). Metric distance."""
    from sklearn.metrics import mutual_info_score
    hx = shannon_entropy(x_encoded)
    hy = shannon_entropy(y_encoded)
    mi = mutual_info_score(x_encoded, y_encoded)
    return hx + hy - 2 * mi  # = H(X) + H(Y) - 2*I(X;Y)
```

**New table `cmc_codependence`:**
```sql
CREATE TABLE IF NOT EXISTS public.cmc_codependence (
    id_a            INTEGER NOT NULL,    -- first asset
    id_b            INTEGER NOT NULL,    -- second asset
    tf              TEXT NOT NULL,
    window_bars     INTEGER NOT NULL,    -- rolling window used (e.g. 252)
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    pearson_corr    DOUBLE PRECISION,   -- baseline (linear)
    distance_corr   DOUBLE PRECISION,   -- non-linear
    mutual_info     DOUBLE PRECISION,   -- total dependence
    variation_of_info DOUBLE PRECISION, -- information-theoretic distance

    n_obs           INTEGER,

    PRIMARY KEY (id_a, id_b, tf, window_bars, computed_at)
);
```

### Pattern 6: SQL Migration for cmc_features

```sql
-- sql/migration/add_microstructure_to_features.sql
-- Use encoding='utf-8' when reading on Windows (cp1252 default breaks box chars)

ALTER TABLE public.cmc_features
    ADD COLUMN IF NOT EXISTS close_fracdiff       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS close_fracdiff_d     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS kyle_lambda          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS amihud_lambda        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hasbrouck_lambda     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS sadf_stat            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS sadf_is_explosive    BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS entropy_shannon      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entropy_lz           DOUBLE PRECISION;
```

### Anti-Patterns to Avoid

- **True SADF in daily refresh:** O(n^2) ADF calls = 348s per asset for 1460 bars. Use rolling ADF (63-bar window) instead.
- **Entropy on price levels:** Always encode RETURN series, not price series. Price levels yield trivially high entropy.
- **All-vs-all distance correlation in daily refresh:** 1225 pairs x 140ms = 3 minutes. Run as a weekly batch or only on demand.
- **Storing codependence in cmc_features:** Pairwise metrics are not per-bar; they belong in a separate `cmc_codependence` table.
- **Using mlfinlab import:** Package has numpy<1.27 constraint, incompatible with project's numpy 2.4.1. All algorithms must be re-implemented.
- **Fractional diff on price levels with all weights:** threshold=1e-5 causes all 300+ weights to be used, producing near-zero output. Use threshold=1e-2 for practical window size (~12 weights for d=0.4).

---

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mutual information between continuous variables | Histogram binning MI | `sklearn.feature_selection.mutual_info_regression` | k-NN estimator handles continuous data correctly; histogram suffers from binning sensitivity |
| Numerically stable OLS for ADF regression | `np.linalg.solve` | `scipy.linalg.lstsq(check_finite=False)` | lstsq handles rank-deficient cases; solve fails on near-singular matrices from price regressions |
| Distance correlation | `scipy.stats.pearsonr` | Custom numpy Szekely implementation | Pearson misses all non-linear dependence; dcor package unavailable; numpy impl verified working |
| ADF stationarity test with proper p-values | Manual t-distribution lookup | `statsmodels.tsa.stattools.adfuller` (if installed) | MacKinnon (2010) critical values differ from standard t-distribution; manual lookup error-prone |

**Key insight:** The three hardest parts of this domain (ADF, mutual information, distance correlation) all have correct implementations that are 20-50 lines of numpy/scipy. The temptation to import mlfinlab is understandable but blocked by the numpy version constraint. The custom implementations are verified to be correct.

---

## Common Pitfalls

### Pitfall 1: FFD Weight Cutoff Threshold

**What goes wrong:** Using `threshold=1e-5` causes all weights to be used (up to 1000 weights), making the output near-constant because very small weights effectively zero out the signal.

**Why it happens:** At d=0.4 with threshold=1e-5, weights decay very slowly — numpy uses 1000 weights, and the dot product collapses to near zero.

**How to avoid:** Use `threshold=1e-2` for daily refresh (yields ~12 weights for d=0.4, practical window). Use `threshold=1e-4` for research accuracy.

**Warning signs:** `frac_diff_ffd` returns values with very small variance or only 1 non-NaN value.

### Pitfall 2: True SADF Performance

**What goes wrong:** Implementing the textbook SADF (expanding window ADF for every possible t0) produces correct results but takes 348 seconds per asset for 1460 bars.

**Why it happens:** O(n^2) ADF calls. For 50 assets, that is ~5 hours per daily refresh.

**How to avoid:** Use rolling ADF on a 63-bar fixed window as the per-bar feature. Store as `sadf_stat`. Optionally run true SADF once as a historical analysis script.

**Warning signs:** Daily refresh hangs for minutes on a single asset during SADF computation.

### Pitfall 3: Entropy on Price Levels

**What goes wrong:** Computing entropy directly on close prices yields uniform high entropy for all assets regardless of market structure.

**Why it happens:** Price levels are non-stationary and fill the entire range of quantile bins uniformly.

**How to avoid:** Always compute entropy on RETURN series (bar-to-bar log returns). Returns are stationary and show actual predictability structure.

**Warning signs:** All assets show identical entropy values (~2.3 for 10-bin Shannon), with no differentiation between trending and mean-reverting assets.

### Pitfall 4: Distance Correlation Memory

**What goes wrong:** Computing distance correlation for all 1225 asset pairs simultaneously allocates n^2 arrays for each pair, potentially exhausting RAM.

**Why it happens:** The Szekely algorithm builds n x n distance matrices. For n=1460, each pair requires 34MB. 1225 pairs in parallel = 40GB.

**How to avoid:** Process pairs sequentially (verified: 140ms each = 3 minutes total). Or reduce window length to 252 bars (~6MB per pair) for the matrix computation.

**Warning signs:** OOM errors during codependence computation.

### Pitfall 5: SQL Migration Encoding on Windows

**What goes wrong:** `UnicodeDecodeError: 'cp1252' codec can't decode byte` when running SQL migration scripts that contain UTF-8 box-drawing characters.

**Why it happens:** Windows default encoding is cp1252; box-drawing characters (U+2550, etc.) are valid UTF-8 but invalid cp1252.

**How to avoid:** Always open SQL files with `encoding='utf-8'` in Python. Avoid box-drawing characters in new SQL files for cross-platform compatibility.

**Warning signs:** Migration scripts fail on Windows CI but pass on Linux.

### Pitfall 6: Amihud Lambda Scale

**What goes wrong:** Raw Amihud lambda values are on the order of 1e-13 for high-volume crypto (e.g., BTC/USD), making direct comparison across assets or thresholding meaningless.

**Why it happens:** Dollar volume for BTC is ~$30B/day. `|return|/dollar_volume` produces very small numbers.

**How to avoid:** Log-transform Amihud lambda before computing z-scores: `log_amihud = np.log(amihud + 1e-20)`. Use the log-transformed value for IC evaluation and cross-sectional comparisons.

**Warning signs:** IC of raw amihud_lambda is near zero; log-transformed version shows positive IC.

---

## Code Examples

Verified patterns from scratch implementations:

### ADF T-Statistic (used in FFD auto-tuning and SADF)
```python
# Verified: stationary series returns t < -6, random walk returns t ~ -2
import scipy.linalg
import numpy as np

def _adf_tstat(log_prices: np.ndarray, lags: int = 1) -> float:
    """ADF t-statistic via OLS without statsmodels.

    H0: series has a unit root (non-stationary).
    Reject H0 (stationary) when t < -2.9 (5% approx).
    """
    dy = np.diff(log_prices)
    n = len(dy)
    if n < lags + 5:
        return np.nan
    y = dy[lags:]
    y_lag = log_prices[lags:-1]
    X = np.column_stack([np.ones(len(y_lag)), y_lag])
    for i in range(1, lags + 1):
        lag_col = dy[lags - i:n - i]
        min_len = min(len(y), len(lag_col))
        X = X[:min_len]
        y = y[:min_len]
        X = np.column_stack([X, lag_col[:min_len]])
    if len(y) < X.shape[1] + 3:
        return np.nan
    beta, _, _, _ = scipy.linalg.lstsq(X, y, check_finite=False)
    resid = y - X @ beta
    s2 = np.dot(resid, resid) / max(1, len(y) - X.shape[1])
    cov = s2 * np.linalg.pinv(X.T @ X)
    return float(beta[1] / np.sqrt(max(cov[1, 1], 1e-20)))
```

### FFD with Auto-Tuned d
```python
# Verified: weights(d=0.4, threshold=1e-2) gives 12 weights, practical window
def find_min_d(close: np.ndarray, min_d: float = 0.1, max_d: float = 1.0,
               n_steps: int = 20, adf_threshold: float = -2.9) -> float:
    """Find minimum fractional differencing order that achieves stationarity."""
    log_close = np.log(close + 1e-10)
    for d in np.linspace(min_d, max_d, n_steps):
        fd = frac_diff_ffd(log_close, d=d, threshold=1e-2)
        fd_valid = fd[~np.isnan(fd)]
        if len(fd_valid) < 30:
            continue
        t_stat = _adf_tstat(fd_valid, lags=1)
        if t_stat < adf_threshold:
            return round(float(d), 3)
    return 1.0
```

### Mutual Information (sklearn, continuous)
```python
# Verified: MI=1.5 for x^2 + noise relationship (Pearson misses it)
from sklearn.feature_selection import mutual_info_regression

def pairwise_mi(x: np.ndarray, y: np.ndarray) -> float:
    """Estimate mutual information between two continuous series."""
    return float(mutual_info_regression(
        x.reshape(-1, 1), y, n_neighbors=3, random_state=42
    )[0])
```

### Distance Correlation (pure numpy)
```python
# Verified: dcor=0.55 for x^2 + noise (Pearson=-0.15, misses relationship)
def distance_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Szekely (2007) distance correlation. Zero iff statistically independent."""
    n = len(x)
    a = np.abs(x[:, None] - x[None, :])
    b = np.abs(y[:, None] - y[None, :])
    A = a - a.mean(0, keepdims=True) - a.mean(1, keepdims=True) + a.mean()
    B = b - b.mean(0, keepdims=True) - b.mean(1, keepdims=True) + b.mean()
    dcov2 = (A * B).mean()
    dvar_x = (A * A).mean()
    dvar_y = (B * B).mean()
    denom = np.sqrt(dvar_x * dvar_y)
    return float(np.sqrt(max(0.0, dcov2) / denom)) if denom > 0 else 0.0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw prices as ML features | Fractionally differentiated prices (d≈0.35-0.45) | AFML 2018 | Stationary features with preserved autocorrelation structure |
| Pearson correlation for asset grouping | Distance correlation + MI for codependence | AFML 2018 | Detects non-linear relationships between assets |
| Fixed-horizon return labels | SADF-based bubble detection | AFML 2018 | Identifies explosive regimes before they peak |
| Pearson correlation in comovement table | MI + distance corr extending cmc_regime_comovement | Phase 59 | More complete picture of inter-EMA and inter-asset relationships |

**Deprecated/outdated in this domain:**
- **mlfinlab direct import:** Requires numpy<1.27, project has 2.4.1. Custom re-implementation is the standard approach for this project.
- **True SADF for daily refresh:** O(n^2) makes it infeasible. Rolling ADF (window=63) is the practical daily proxy.

---

## Open Questions

1. **Auto-tune d per asset or use fixed d=0.4?**
   - What we know: AFML recommends auto-tuning; d=0.35-0.45 works empirically for most assets
   - What's unclear: Whether per-asset d changes frequently enough to require daily recompute, or if it can be cached and recomputed monthly
   - Recommendation: Compute d once per asset (daily full-history recompute of d would add ~10ms/asset) and store `close_fracdiff_d` as a constant per bar for that refresh cycle

2. **Regime integration for SADF — extend cmc_regimes or read from cmc_features?**
   - What we know: cmc_regimes has l0/l1/l2_label columns; adding l3 for bubble detection is natural
   - What's unclear: Whether the downstream signal generators should read sadf_is_explosive from cmc_features (JOIN) or from cmc_regimes (already loaded)
   - Recommendation: Store in `cmc_features` (per MICRO-03 spec: "feeds into cmc_regimes as additional regime signal"). Add a JOIN in `refresh_cmc_regimes.py` to read `sadf_is_explosive` and surface it in `regime_key`.

3. **cmc_codependence refresh frequency?**
   - What we know: Full 50-asset MI sweep = 28s; full distance corr = 3 minutes
   - What's unclear: Whether daily refresh or weekly snapshot is more appropriate for codependence measures
   - Recommendation: Weekly refresh via separate cron job, not part of `run_daily_refresh.py`. The `computed_at` timestamp in PK retains history.

4. **Entropy window size (bars)?**
   - What we know: Window=50 is verified to differentiate predictable vs. random series
   - What's unclear: Whether shorter windows (20 bars = 1 month of 1D data) have better IC vs. longer windows (100 bars)
   - Recommendation: Start with 50-bar window; expose as configurable parameter. IC evaluation in Phase 56 will determine optimal window.

---

## Sources

### Primary (HIGH confidence)
- Verified numpy/scipy implementations — all code snippets in this document were executed and verified in the project's Python environment (numpy 2.4.1, scipy 1.17.0, sklearn 1.8.0)
- `src/ta_lab2/scripts/features/base_feature.py` — confirmed BaseFeature pattern (Template Method, load/compute/write)
- `src/ta_lab2/scripts/features/vol_feature.py` — confirmed VolatilityFeature as the reference implementation pattern
- `sql/views/050_cmc_features.sql` — confirmed current cmc_features schema (112 columns, PK: id, ts, tf, alignment_source)
- `sql/regimes/080_cmc_regimes.sql` — confirmed cmc_regimes schema (no l3_label yet)
- `sql/regimes/084_cmc_regime_comovement.sql` — confirmed comovement table uses Pearson only

### Secondary (MEDIUM confidence)
- `.planning/research/quant_finance_ecosystem_review.md` — MLFinLab algorithm catalog (Tier 2-3 for Phase 59 features)
- `.planning/phases/55-feature-signal-evaluation/55-RESEARCH.md` — confirmed ExperimentRunner, IC infrastructure, feature_registry lifecycle

### Tertiary (LOW confidence)
- AFML (Lopez de Prado 2018) algorithm descriptions (via training data) — used as reference for algorithm correctness, but all implementations verified empirically
- Phillips-Wu-Yu (2011) SADF critical values — approximate values used, would need statsmodels for exact MacKinnon values

---

## Metadata

**Confidence breakdown:**
- FFD implementation: HIGH — code executed, weights verified, output shape confirmed
- Liquidity measures: HIGH — all three executed, scipy.stats.linregress confirmed working
- Rolling ADF / SADF proxy: HIGH — benchmarked at 0.54s per 1460-bar asset; true SADF infeasibility confirmed (40.8s for 500 bars, extrapolates to 348s for 1460)
- Entropy: HIGH — rolling LZ correctly differentiates predictable from random returns
- Distance correlation: HIGH — Szekely formula verified (dcor=0.55 for x^2 relationship, Pearson=-0.15)
- Mutual information: HIGH — sklearn.mutual_info_regression confirmed available (v1.8.0)
- Performance estimates: HIGH — all benchmarked in project environment
- ADF critical values: MEDIUM — approximate thresholds from training data; statsmodels would give exact MacKinnon p-values
- Codependence table design: MEDIUM — schema proposed but not validated against downstream use cases

**Research date:** 2026-02-27
**Valid until:** 2026-03-27 (stable domain; numpy/scipy APIs are stable)
