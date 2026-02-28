"""Core mathematical implementations for microstructural features.

All functions are pure (no DB/IO). Used by MicrostructureFeature and
CodependenceFeature scripts.

Sections:
    1. Fractional Differentiation (MICRO-01)
    2. Liquidity Impact Measures (MICRO-02)
    3. Rolling ADF / SADF Proxy (MICRO-03)
    4. Entropy Features (MICRO-04)
    5. Non-Linear Codependence (MICRO-05)
"""

from __future__ import annotations

import numpy as np
import scipy.linalg
import scipy.stats
from sklearn.feature_selection import mutual_info_regression
from sklearn.metrics import mutual_info_score


# =========================================================
# Section 1: Fractional Differentiation (MICRO-01)
# =========================================================


def ffd_weights(d: float, size: int = 1000, threshold: float = 1e-2) -> np.ndarray:
    """Compute Fixed-Width Window Fractional Differentiation (FFD) weights.

    Implements the weight generation from Marcos Lopez de Prado,
    *Advances in Financial Machine Learning* (2018), Ch. 5.

    Parameters
    ----------
    d : float
        Fractional differentiation order, typically in [0.3, 0.5].
    size : int
        Maximum number of weights to compute before thresholding.
    threshold : float
        Minimum absolute weight to retain. Default 1e-2 yields ~12
        weights at d=0.4, providing a practical rolling window size.

    Returns
    -------
    np.ndarray
        1-D array of FFD weights (first element is always 1.0).
        Subsequent weights are negative and decreasing in absolute value.
    """
    weights = [1.0]
    for k in range(1, size):
        w_k = -weights[-1] * (d - k + 1) / k
        if abs(w_k) < threshold:
            break
        weights.append(w_k)
    return np.array(weights, dtype=np.float64)


def frac_diff_ffd(
    series: np.ndarray, d: float = 0.4, threshold: float = 1e-2
) -> np.ndarray:
    """Apply FFD to a price (or log-price) series.

    Produces a fractionally differentiated series that preserves long-range
    memory while achieving (or approaching) stationarity.

    Reference: Lopez de Prado (2018), Ch. 5, Section 5.4.

    Parameters
    ----------
    series : np.ndarray
        1-D input series (e.g., close prices or log-close prices).
    d : float
        Fractional differentiation order.
    threshold : float
        Minimum absolute weight for the FFD window.

    Returns
    -------
    np.ndarray
        Fractionally differentiated series. First ``(width - 1)`` values
        are NaN where ``width = len(ffd_weights(d, threshold=threshold))``.
    """
    series = np.asarray(series, dtype=np.float64)
    w = ffd_weights(d, size=len(series), threshold=threshold)
    width = len(w)
    out = np.full(len(series), np.nan, dtype=np.float64)
    for t in range(width - 1, len(series)):
        out[t] = np.dot(w, series[t - width + 1 : t + 1][::-1])
    return out


def find_min_d(
    close: np.ndarray,
    min_d: float = 0.1,
    max_d: float = 1.0,
    n_steps: int = 20,
    adf_threshold: float = -2.9,
) -> float:
    """Find the minimum fractional differentiation order achieving stationarity.

    Searches over d in [min_d, max_d] and returns the smallest d for which
    the Augmented Dickey-Fuller t-statistic is below ``adf_threshold``
    (indicating stationarity).

    Reference: Lopez de Prado (2018), Ch. 5, Section 5.5.

    Parameters
    ----------
    close : np.ndarray
        1-D close price array. Log is taken internally.
    min_d : float
        Minimum d to test.
    max_d : float
        Maximum d to test.
    n_steps : int
        Number of steps in the search grid.
    adf_threshold : float
        ADF t-stat threshold (default -2.9 roughly corresponds to 5%
        significance for typical sample sizes).

    Returns
    -------
    float
        Minimum d that achieves stationarity. Returns ``max_d`` if no
        tested d passes the ADF test.
    """
    close = np.asarray(close, dtype=np.float64)
    log_close = np.log(np.maximum(close, 1e-12))
    d_values = np.linspace(min_d, max_d, n_steps)
    for d in d_values:
        ffd_series = frac_diff_ffd(log_close, d=d)
        valid = ffd_series[~np.isnan(ffd_series)]
        if len(valid) < 30:
            continue
        try:
            t_stat = _adf_tstat(ffd_series[~np.isnan(ffd_series)])
            if t_stat < adf_threshold:
                return float(d)
        except Exception:
            continue
    return float(max_d)


# =========================================================
# Section 2: Liquidity Impact Measures (MICRO-02)
# =========================================================


def amihud_lambda(
    close: np.ndarray, volume: np.ndarray, window: int = 20
) -> np.ndarray:
    """Amihud (2002) illiquidity ratio: rolling mean of |return| / dollar_volume.

    Higher values indicate lower liquidity (greater price impact per unit
    of volume traded).

    Reference: Amihud, Y. (2002). "Illiquidity and stock returns:
    cross-section and time-series effects." *Journal of Financial Markets*.

    Parameters
    ----------
    close : np.ndarray
        1-D close price array.
    volume : np.ndarray
        1-D volume array (same length as close).
    window : int
        Rolling window size.

    Returns
    -------
    np.ndarray
        Amihud lambda values. First ``window`` values are NaN.
        Non-NaN values are non-negative.
    """
    close = np.asarray(close, dtype=np.float64)
    volume = np.asarray(volume, dtype=np.float64)
    n = len(close)

    ret = np.empty(n, dtype=np.float64)
    ret[0] = np.nan
    ret[1:] = np.abs(close[1:] / close[:-1] - 1.0)

    # Dollar volume; guard against zero
    dvol = np.abs(close * volume)
    dvol = np.where(dvol == 0, np.nan, dvol)

    ratio = ret / dvol

    out = np.full(n, np.nan, dtype=np.float64)
    for t in range(window, n):
        chunk = ratio[t - window + 1 : t + 1]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) > 0:
            out[t] = np.mean(valid)
    return out


def kyle_lambda(close: np.ndarray, volume: np.ndarray, window: int = 20) -> np.ndarray:
    """Kyle (1985) lambda: rolling OLS slope of delta_price on signed_volume.

    Measures the price impact of order flow. Higher values indicate less
    liquid markets.

    Reference: Kyle, A. S. (1985). "Continuous Auctions and Insider Trading."
    *Econometrica*.

    Parameters
    ----------
    close : np.ndarray
        1-D close price array.
    volume : np.ndarray
        1-D volume array (same length as close).
    window : int
        Rolling window size for OLS regression.

    Returns
    -------
    np.ndarray
        Kyle lambda (OLS slope) values. First ``window`` values are NaN.
    """
    close = np.asarray(close, dtype=np.float64)
    volume = np.asarray(volume, dtype=np.float64)
    n = len(close)

    delta_price = np.empty(n, dtype=np.float64)
    delta_price[0] = np.nan
    delta_price[1:] = close[1:] - close[:-1]

    # Signed volume: sign of price change * volume
    sign = np.sign(delta_price)
    signed_vol = sign * volume

    out = np.full(n, np.nan, dtype=np.float64)
    for t in range(window, n):
        y = delta_price[t - window + 1 : t + 1]
        x = signed_vol[t - window + 1 : t + 1]
        mask = ~(np.isnan(y) | np.isnan(x))
        if mask.sum() < 3:
            continue
        result = scipy.stats.linregress(x[mask], y[mask])
        out[t] = result.slope
    return out


def hasbrouck_lambda(
    close: np.ndarray, volume: np.ndarray, window: int = 20
) -> np.ndarray:
    """Hasbrouck (2009) lambda: OLS of delta_price on signed sqrt(dollar_volume).

    A variant of Kyle lambda that uses the square root of dollar volume
    to account for concavity in the price impact function.

    Reference: Hasbrouck, J. (2009). "Trading Costs and Returns for U.S.
    Equities: Estimating Effective Costs from Daily Data."
    *Journal of Finance*.

    Parameters
    ----------
    close : np.ndarray
        1-D close price array.
    volume : np.ndarray
        1-D volume array (same length as close).
    window : int
        Rolling window size for OLS regression.

    Returns
    -------
    np.ndarray
        Hasbrouck lambda (OLS slope) values. First ``window`` values are NaN.
    """
    close = np.asarray(close, dtype=np.float64)
    volume = np.asarray(volume, dtype=np.float64)
    n = len(close)

    delta_price = np.empty(n, dtype=np.float64)
    delta_price[0] = np.nan
    delta_price[1:] = close[1:] - close[:-1]

    sign = np.sign(delta_price)
    dvol = np.abs(close * volume)
    signed_sqrt_dvol = sign * np.sqrt(np.maximum(dvol, 0.0))

    out = np.full(n, np.nan, dtype=np.float64)
    for t in range(window, n):
        y = delta_price[t - window + 1 : t + 1]
        x = signed_sqrt_dvol[t - window + 1 : t + 1]
        mask = ~(np.isnan(y) | np.isnan(x))
        if mask.sum() < 3:
            continue
        result = scipy.stats.linregress(x[mask], y[mask])
        out[t] = result.slope
    return out


# =========================================================
# Section 3: Rolling ADF / SADF Proxy (MICRO-03)
# =========================================================


def _adf_tstat(log_prices: np.ndarray, lags: int = 1) -> float:
    """Compute ADF t-statistic for a unit root test.

    Uses OLS via ``scipy.linalg.lstsq`` for numerical stability.

    Parameters
    ----------
    log_prices : np.ndarray
        1-D array of (log) prices or any level series.
    lags : int
        Number of lagged difference terms to include in the regression.

    Returns
    -------
    float
        ADF t-statistic. More negative values indicate stronger evidence
        against a unit root (i.e., stationarity). Returns NaN if
        insufficient data (< lags + 5 observations).
    """
    y = np.asarray(log_prices, dtype=np.float64)
    n = len(y)
    if n < lags + 5:
        return np.nan

    dy = np.diff(y)
    # Dependent variable: dy[lags:]
    dep = dy[lags:]
    m = len(dep)

    # Build regressor matrix: [y_{t-1}, dy_{t-1}, ..., dy_{t-lags}, 1]
    ncols = 1 + lags + 1  # level + lagged diffs + intercept
    X = np.empty((m, ncols), dtype=np.float64)
    X[:, 0] = y[lags:-1]  # lagged level
    for lag in range(1, lags + 1):
        X[:, lag] = dy[lags - lag : -lag] if lag < len(dy) else 0.0
    X[:, -1] = 1.0  # intercept

    result = scipy.linalg.lstsq(X, dep, check_finite=False)
    beta = result[0]

    residuals = dep - X @ beta
    sse = np.dot(residuals, residuals)
    dof = m - ncols
    if dof <= 0:
        return np.nan
    mse = sse / dof

    # Variance of beta[0] (the coefficient on the lagged level)
    XtX = X.T @ X
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        return np.nan
    var_beta0 = max(mse * XtX_inv[0, 0], 1e-20)
    se_beta0 = np.sqrt(var_beta0)

    return float(beta[0] / se_beta0)


def rolling_adf(log_prices: np.ndarray, window: int = 63, lags: int = 1) -> np.ndarray:
    """Rolling-window ADF t-statistic for detecting explosive behavior.

    Applying this to log-prices with a rolling window provides a proxy for
    the SADF (Supremum ADF) bubble detector from Phillips, Shi & Yu (2015).

    Parameters
    ----------
    log_prices : np.ndarray
        1-D array of log-prices.
    window : int
        Rolling window size for the ADF test.
    lags : int
        Number of lagged difference terms in the ADF regression.

    Returns
    -------
    np.ndarray
        Rolling ADF t-statistics. First ``window`` values are NaN.
        Values > ~1.5 may indicate explosive (bubble-like) behavior.
    """
    log_prices = np.asarray(log_prices, dtype=np.float64)
    n = len(log_prices)
    out = np.full(n, np.nan, dtype=np.float64)
    for t in range(window, n):
        segment = log_prices[t - window + 1 : t + 1]
        out[t] = _adf_tstat(segment, lags=lags)
    return out


# =========================================================
# Section 4: Entropy Features (MICRO-04)
# =========================================================


def quantile_encode(arr: np.ndarray, n_bins: int = 10) -> np.ndarray:
    """Map continuous values to discrete symbols via quantile binning.

    Parameters
    ----------
    arr : np.ndarray
        1-D array of continuous values.
    n_bins : int
        Number of discrete bins (symbols range from 0 to n_bins-1).

    Returns
    -------
    np.ndarray
        Integer-encoded array with values in [0, n_bins-1].
    """
    arr = np.asarray(arr, dtype=np.float64)
    # Compute quantile edges, using np.unique to handle duplicate edges
    quantiles = np.linspace(0, 1, n_bins + 1)
    edges = np.quantile(arr, quantiles)
    edges = np.unique(edges)
    # Use searchsorted to bin; clip to [0, n_actual_bins-1]
    n_actual_bins = max(len(edges) - 1, 1)
    encoded = np.searchsorted(edges[1:], arr, side="left")
    encoded = np.clip(encoded, 0, n_actual_bins - 1)
    return encoded.astype(np.int64)


def shannon_entropy(encoded: np.ndarray) -> float:
    """Shannon entropy in nats of a discrete-encoded series.

    Parameters
    ----------
    encoded : np.ndarray
        1-D integer-encoded array (e.g., from ``quantile_encode``).

    Returns
    -------
    float
        Shannon entropy: -sum(p * log(p + 1e-12)).
        Near 0 for degenerate (single-value) distributions.
    """
    encoded = np.asarray(encoded)
    _, counts = np.unique(encoded, return_counts=True)
    p = counts / counts.sum()
    return float(-np.sum(p * np.log(p + 1e-12)))


def lempel_ziv_complexity(s: list) -> int:
    """Lempel-Ziv 76 complexity: count distinct sub-phrases.

    Reference: Lempel, A. & Ziv, J. (1976). "On the Complexity of
    Finite Sequences." *IEEE Transactions on Information Theory*.

    Parameters
    ----------
    s : list
        Sequence of discrete symbols.

    Returns
    -------
    int
        Number of distinct sub-phrases in the LZ76 decomposition.
    """
    n = len(s)
    if n == 0:
        return 0
    c = 1  # complexity count
    u = 1  # current phrase length
    v = 1  # lookahead
    while u + v <= n:
        # Check if s[u:u+v] is a substring of s[0:u+v-1]
        substring = s[u : u + v]
        found = False
        for j in range(u + v - 1):
            if s[j : j + v] == substring and j + v <= u + v - 1:
                found = True
                break
        if found:
            v += 1
        else:
            c += 1
            u += v
            v = 1
    return c


def rolling_entropy(
    returns: np.ndarray, window: int = 50, n_bins: int = 10
) -> tuple[np.ndarray, np.ndarray]:
    """Rolling Shannon entropy and Lempel-Ziv complexity on return series.

    CRITICAL: Entropy must be computed on RETURN series, not price levels.

    Parameters
    ----------
    returns : np.ndarray
        1-D return series.
    window : int
        Rolling window size.
    n_bins : int
        Number of quantile bins for encoding.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (shannon_vals, lz_vals) both of shape ``(len(returns),)``.
        First ``window`` values are NaN.
        LZ complexity is normalized by ``log2(window)``.
    """
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    shannon_vals = np.full(n, np.nan, dtype=np.float64)
    lz_vals = np.full(n, np.nan, dtype=np.float64)
    lz_norm = np.log2(max(window, 2))

    for t in range(window, n):
        chunk = returns[t - window + 1 : t + 1]
        if np.all(np.isnan(chunk)):
            continue
        valid = chunk[~np.isnan(chunk)]
        if len(valid) < 3:
            continue
        enc = quantile_encode(valid, n_bins=n_bins)
        shannon_vals[t] = shannon_entropy(enc)
        lz_vals[t] = lempel_ziv_complexity(enc.tolist()) / lz_norm
    return shannon_vals, lz_vals


# =========================================================
# Section 5: Non-Linear Codependence (MICRO-05)
# =========================================================


def distance_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Szekely (2007) distance correlation.

    Distance correlation measures both linear and non-linear dependence
    between two random variables. Unlike Pearson correlation, dcor = 0
    implies independence (for finite-variance distributions).

    Reference: Szekely, G. J., Rizzo, M. L. & Bakirov, N. K. (2007).
    "Measuring and testing dependence by correlation of distances."
    *Annals of Statistics*.

    Parameters
    ----------
    x : np.ndarray
        1-D array of observations.
    y : np.ndarray
        1-D array of observations (same length as x).

    Returns
    -------
    float
        Distance correlation in [0, 1]. Returns 0.0 if denominator is zero.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    n = len(x)
    if n < 2:
        return 0.0

    # Distance matrices
    a = np.abs(x[:, None] - x[None, :])
    b = np.abs(y[:, None] - y[None, :])

    # Double-centering
    a_row = a.mean(axis=1, keepdims=True)
    a_col = a.mean(axis=0, keepdims=True)
    a_grand = a.mean()
    A = a - a_row - a_col + a_grand

    b_row = b.mean(axis=1, keepdims=True)
    b_col = b.mean(axis=0, keepdims=True)
    b_grand = b.mean()
    B = b - b_row - b_col + b_grand

    dcov2_xy = (A * B).mean()
    dcov2_xx = (A * A).mean()
    dcov2_yy = (B * B).mean()

    denom = np.sqrt(dcov2_xx * dcov2_yy)
    if denom < 1e-20:
        return 0.0

    dcor2 = dcov2_xy / denom
    # dcor2 can be slightly negative due to numerical precision
    return float(np.sqrt(max(dcor2, 0.0)))


def pairwise_mi(x: np.ndarray, y: np.ndarray, n_neighbors: int = 3) -> float:
    """Mutual information between two continuous series via k-NN estimation.

    Uses ``sklearn.feature_selection.mutual_info_regression`` which
    implements the Kraskov et al. (2004) estimator.

    Reference: Kraskov, A., Stogbauer, H. & Grassberger, P. (2004).
    "Estimating mutual information." *Physical Review E*.

    Parameters
    ----------
    x : np.ndarray
        1-D array of observations (treated as feature).
    y : np.ndarray
        1-D array of observations (treated as target).
    n_neighbors : int
        Number of neighbors for k-NN MI estimator.

    Returns
    -------
    float
        Estimated mutual information (non-negative).
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    if len(x) < n_neighbors + 1:
        return 0.0
    mi = mutual_info_regression(
        x.reshape(-1, 1), y, n_neighbors=n_neighbors, random_state=42
    )
    return float(mi[0])


def variation_of_information(x_encoded: np.ndarray, y_encoded: np.ndarray) -> float:
    """Variation of Information: H(X) + H(Y) - 2*I(X;Y).

    A true metric on the space of random variable clusterings. Lower
    values indicate more similar (more dependent) distributions.

    Reference: Meila, M. (2007). "Comparing clusterings -- an information
    based distance." *Journal of Multivariate Analysis*.

    Parameters
    ----------
    x_encoded : np.ndarray
        1-D integer-encoded (discrete) array.
    y_encoded : np.ndarray
        1-D integer-encoded (discrete) array (same length as x_encoded).

    Returns
    -------
    float
        Variation of Information. 0.0 when x_encoded == y_encoded.
    """
    x_encoded = np.asarray(x_encoded).ravel()
    y_encoded = np.asarray(y_encoded).ravel()

    hx = shannon_entropy(x_encoded)
    hy = shannon_entropy(y_encoded)

    # Joint MI using sklearn (expects integer labels)
    mi = mutual_info_score(x_encoded.astype(int), y_encoded.astype(int))
    # mutual_info_score returns MI in nats

    vi = hx + hy - 2.0 * mi
    return float(max(vi, 0.0))
