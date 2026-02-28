"""Unit tests for microstructure core math library.

Tests all 5 feature classes using synthetic data (no DB required).
Uses np.random.default_rng(42) for reproducibility throughout.
"""

from __future__ import annotations

import numpy as np
import pytest

from ta_lab2.features.microstructure import (
    _adf_tstat,
    amihud_lambda,
    distance_correlation,
    ffd_weights,
    find_min_d,
    frac_diff_ffd,
    hasbrouck_lambda,
    kyle_lambda,
    lempel_ziv_complexity,
    pairwise_mi,
    quantile_encode,
    rolling_adf,
    rolling_entropy,
    shannon_entropy,
    variation_of_information,
)

RNG = np.random.default_rng(42)


# =========================================================
# FFD Tests (Section 1: Fractional Differentiation)
# =========================================================


class TestFFDWeights:
    """Tests for ffd_weights and related FFD functions."""

    def test_ffd_weights_count(self) -> None:
        """FFD weights at d=0.4, threshold=1e-2 should produce ~8-20 weights."""
        w = ffd_weights(d=0.4, threshold=1e-2)
        assert 8 <= len(w) <= 20, f"Expected 8-20 weights, got {len(w)}"

    def test_ffd_weights_first_is_one(self) -> None:
        """First FFD weight is always 1.0."""
        w = ffd_weights(d=0.4)
        assert w[0] == pytest.approx(1.0)

    def test_ffd_weights_subsequent_negative(self) -> None:
        """Subsequent FFD weights are negative and decreasing in absolute value."""
        w = ffd_weights(d=0.4)
        for i in range(1, len(w)):
            assert w[i] < 0, f"Weight {i} should be negative, got {w[i]}"
        # Absolute values should generally decrease
        abs_w = np.abs(w[1:])
        for i in range(len(abs_w) - 1):
            assert abs_w[i] >= abs_w[i + 1], (
                f"Weight abs values should decrease: |w[{i + 1}]|={abs_w[i]} < |w[{i + 2}]|={abs_w[i + 1]}"
            )

    def test_frac_diff_ffd_output_shape(self) -> None:
        """Output length equals input length; first (width-1) values are NaN."""
        rng = np.random.default_rng(42)
        series = np.cumsum(rng.standard_normal(200))
        result = frac_diff_ffd(series, d=0.4)
        assert len(result) == len(series)
        w = ffd_weights(0.4)
        width = len(w)
        # First (width-1) should be NaN
        assert np.all(np.isnan(result[: width - 1]))
        # Remaining should be non-NaN
        assert np.all(~np.isnan(result[width - 1 :]))

    def test_frac_diff_ffd_stationarity(self) -> None:
        """FFD at d=0.4 produces lower autocorrelation than raw prices."""
        rng = np.random.default_rng(42)
        series = np.cumsum(rng.standard_normal(500))
        ffd_result = frac_diff_ffd(series, d=0.4)
        valid = ffd_result[~np.isnan(ffd_result)]
        # Autocorrelation at lag 1
        ac_raw = np.corrcoef(series[:-1], series[1:])[0, 1]
        ac_ffd = np.corrcoef(valid[:-1], valid[1:])[0, 1]
        assert abs(ac_ffd) < abs(ac_raw), (
            f"FFD autocorrelation ({ac_ffd:.3f}) should be lower than raw ({ac_raw:.3f})"
        )

    def test_find_min_d_random_walk(self) -> None:
        """For a random walk, find_min_d returns d in (0.1, 1.0]."""
        rng = np.random.default_rng(42)
        rw = np.cumsum(rng.standard_normal(500)) + 100
        rw = np.abs(rw) + 1  # Ensure positive for log
        d = find_min_d(rw)
        assert 0.1 <= d <= 1.0, f"Expected d in [0.1, 1.0], got {d}"

    def test_find_min_d_stationary(self) -> None:
        """For a stationary series, find_min_d returns low d (<= 0.3)."""
        rng = np.random.default_rng(42)
        # Stationary series: exp of random noise (positive, near-stationary)
        stationary = np.exp(0.01 * rng.standard_normal(500)) * 100
        d = find_min_d(stationary)
        assert d <= 0.3, f"Expected d <= 0.3 for near-stationary series, got {d}"

    def test_ffd_threshold_pitfall(self) -> None:
        """Smaller threshold yields significantly more weights."""
        w_coarse = ffd_weights(d=0.4, threshold=1e-2)
        w_fine = ffd_weights(d=0.4, threshold=1e-5)
        assert len(w_fine) > len(w_coarse) + 5, (
            f"Fine threshold should yield many more weights: {len(w_fine)} vs {len(w_coarse)}"
        )


# =========================================================
# Liquidity Tests (Section 2: Liquidity Impact)
# =========================================================


class TestLiquidity:
    """Tests for Amihud, Kyle, and Hasbrouck lambda measures."""

    @pytest.fixture()
    def ohlcv_data(self) -> dict:
        """Generate synthetic OHLCV data."""
        rng = np.random.default_rng(42)
        n = 200
        close = 100 + np.cumsum(rng.standard_normal(n))
        volume = rng.uniform(1e6, 1e7, n)
        return {"close": close, "volume": volume}

    def test_amihud_lambda_shape(self, ohlcv_data: dict) -> None:
        """Output same length as close; first window values are NaN."""
        result = amihud_lambda(ohlcv_data["close"], ohlcv_data["volume"], window=20)
        assert len(result) == len(ohlcv_data["close"])
        assert np.all(np.isnan(result[:20]))

    def test_amihud_lambda_positive(self, ohlcv_data: dict) -> None:
        """Non-NaN Amihud values are non-negative."""
        result = amihud_lambda(ohlcv_data["close"], ohlcv_data["volume"], window=20)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0), "Amihud lambda should be non-negative"

    def test_kyle_lambda_shape(self, ohlcv_data: dict) -> None:
        """Output same length as close; first window values NaN."""
        result = kyle_lambda(ohlcv_data["close"], ohlcv_data["volume"], window=20)
        assert len(result) == len(ohlcv_data["close"])
        assert np.all(np.isnan(result[:20]))

    def test_hasbrouck_lambda_shape(self, ohlcv_data: dict) -> None:
        """Output same length as close; first window values NaN."""
        result = hasbrouck_lambda(ohlcv_data["close"], ohlcv_data["volume"], window=20)
        assert len(result) == len(ohlcv_data["close"])
        assert np.all(np.isnan(result[:20]))

    def test_liquidity_handles_zero_volume(self) -> None:
        """No crash when volume contains zeros."""
        rng = np.random.default_rng(42)
        close = 100 + np.cumsum(rng.standard_normal(100))
        volume = rng.uniform(1e6, 1e7, 100)
        volume[10:15] = 0  # Zero volume periods

        # Should not raise
        a = amihud_lambda(close, volume, window=20)
        k = kyle_lambda(close, volume, window=20)
        h = hasbrouck_lambda(close, volume, window=20)
        assert len(a) == 100
        assert len(k) == 100
        assert len(h) == 100


# =========================================================
# Rolling ADF Tests (Section 3: Rolling ADF / SADF)
# =========================================================


class TestRollingADF:
    """Tests for _adf_tstat and rolling_adf."""

    def test_adf_tstat_stationary(self) -> None:
        """For a stationary series, ADF t-stat should be < -2.9."""
        rng = np.random.default_rng(42)
        stationary = rng.standard_normal(500)
        t_stat = _adf_tstat(stationary)
        assert t_stat < -2.9, (
            f"Expected t-stat < -2.9 for stationary series, got {t_stat}"
        )

    def test_adf_tstat_random_walk(self) -> None:
        """For a random walk, ADF t-stat should be > -2.9 (fail to reject unit root)."""
        rng = np.random.default_rng(42)
        rw = np.cumsum(rng.standard_normal(500))
        t_stat = _adf_tstat(rw)
        assert t_stat > -2.9, f"Expected t-stat > -2.9 for random walk, got {t_stat}"

    def test_rolling_adf_shape(self) -> None:
        """Output same length as input; first window values NaN."""
        rng = np.random.default_rng(42)
        series = np.cumsum(rng.standard_normal(200))
        result = rolling_adf(series, window=63)
        assert len(result) == len(series)
        assert np.all(np.isnan(result[:63]))

    def test_rolling_adf_explosive(self) -> None:
        """For explosive AR(1) process (phi > 1), some ADF t-stats are positive."""
        rng = np.random.default_rng(42)
        # Simulate explosive AR(1): y_t = 1.02 * y_{t-1} + noise
        n = 300
        y = np.zeros(n, dtype=np.float64)
        y[0] = 100.0
        for t in range(1, n):
            y[t] = 1.02 * y[t - 1] + rng.standard_normal()
        result = rolling_adf(y, window=63)
        valid = result[~np.isnan(result)]
        # Explosive process should yield positive ADF t-stats (right-tailed)
        assert np.any(valid > 0), (
            f"Expected some values > 0 for explosive series, max was {np.nanmax(result):.2f}"
        )

    def test_adf_tstat_insufficient_data(self) -> None:
        """Returns NaN for very short series."""
        short = np.array([1.0, 2.0, 3.0])
        assert np.isnan(_adf_tstat(short, lags=1))


# =========================================================
# Entropy Tests (Section 4: Entropy Features)
# =========================================================


class TestEntropy:
    """Tests for quantile_encode, shannon_entropy, lempel_ziv_complexity, rolling_entropy."""

    def test_quantile_encode_range(self) -> None:
        """Encoded values should be in [0, n_bins-1]."""
        rng = np.random.default_rng(42)
        arr = rng.standard_normal(200)
        encoded = quantile_encode(arr, n_bins=10)
        assert encoded.min() >= 0
        assert encoded.max() <= 9

    def test_shannon_entropy_uniform(self) -> None:
        """Uniform distribution has higher entropy than peaked distribution."""
        uniform = np.arange(100) % 10  # uniform across 10 bins
        peaked = np.zeros(100, dtype=int)
        peaked[:5] = 1  # mostly 0, a few 1s
        h_uniform = shannon_entropy(uniform)
        h_peaked = shannon_entropy(peaked)
        assert h_uniform > h_peaked, (
            f"Uniform entropy ({h_uniform:.3f}) should exceed peaked ({h_peaked:.3f})"
        )

    def test_shannon_entropy_degenerate(self) -> None:
        """Single-value array has entropy near 0."""
        degenerate = np.ones(100, dtype=int)
        h = shannon_entropy(degenerate)
        assert h < 0.01, f"Degenerate entropy should be near 0, got {h}"

    def test_lempel_ziv_complexity_repetitive(self) -> None:
        """Repetitive sequence has lower complexity than random."""
        repetitive = [0, 1] * 50  # length 100, very repetitive
        rng = np.random.default_rng(42)
        random_seq = rng.integers(0, 10, 100).tolist()
        lz_rep = lempel_ziv_complexity(repetitive)
        lz_rand = lempel_ziv_complexity(random_seq)
        assert lz_rep < lz_rand, (
            f"Repetitive LZ ({lz_rep}) should be less than random ({lz_rand})"
        )

    def test_rolling_entropy_shape(self) -> None:
        """Both outputs same length; first window values NaN."""
        rng = np.random.default_rng(42)
        rets = rng.standard_normal(200)
        sh, lz = rolling_entropy(rets, window=50)
        assert len(sh) == 200
        assert len(lz) == 200
        assert np.all(np.isnan(sh[:50]))
        assert np.all(np.isnan(lz[:50]))

    def test_entropy_on_returns_vs_prices(self) -> None:
        """LZ complexity differentiates structured from random return series.

        Quantile encoding normalizes marginal distributions, so Shannon
        entropy is similar for any smooth distribution. The real
        differentiation is in LZ complexity (temporal structure).
        """
        rng = np.random.default_rng(42)
        # Highly structured: alternating positive/negative returns
        n = 200
        predictable = np.where(np.arange(n) % 2 == 0, 0.01, -0.01)
        # Random returns
        random_rets = rng.standard_normal(n) * 0.01

        _, lz_pred = rolling_entropy(predictable, window=50)
        _, lz_rand = rolling_entropy(random_rets, window=50)

        # Mean LZ complexity of random should exceed predictable (more complex)
        mean_pred = np.nanmean(lz_pred)
        mean_rand = np.nanmean(lz_rand)
        assert mean_rand > mean_pred, (
            f"Random LZ ({mean_rand:.3f}) should exceed predictable ({mean_pred:.3f})"
        )

    def test_lempel_ziv_empty(self) -> None:
        """Empty sequence returns 0."""
        assert lempel_ziv_complexity([]) == 0


# =========================================================
# Codependence Tests (Section 5: Non-Linear Codependence)
# =========================================================


class TestCodependence:
    """Tests for distance_correlation, pairwise_mi, variation_of_information."""

    def test_distance_correlation_independent(self) -> None:
        """Distance correlation < 0.2 for independent series."""
        rng = np.random.default_rng(42)
        x = rng.standard_normal(500)
        y = rng.standard_normal(500)
        dcor = distance_correlation(x, y)
        assert dcor < 0.2, f"Expected dcor < 0.2 for independent, got {dcor:.3f}"

    def test_distance_correlation_nonlinear(self) -> None:
        """Distance correlation > 0.3 for y = x^2 + noise."""
        rng = np.random.default_rng(42)
        x = rng.standard_normal(500)
        y = x**2 + 0.1 * rng.standard_normal(500)
        dcor = distance_correlation(x, y)
        assert dcor > 0.3, f"Expected dcor > 0.3 for nonlinear, got {dcor:.3f}"

    def test_distance_correlation_perfect(self) -> None:
        """Distance correlation should be high for perfectly correlated series."""
        rng = np.random.default_rng(42)
        x = rng.standard_normal(200)
        y = 2 * x + 1
        dcor = distance_correlation(x, y)
        assert dcor > 0.9, f"Expected dcor > 0.9 for perfect linear, got {dcor:.3f}"

    def test_pairwise_mi_dependent(self) -> None:
        """MI > 0 for correlated series."""
        rng = np.random.default_rng(42)
        x = rng.standard_normal(500)
        y = x + 0.1 * rng.standard_normal(500)
        mi = pairwise_mi(x, y)
        assert mi > 0, f"Expected MI > 0 for dependent series, got {mi:.4f}"

    def test_pairwise_mi_independent(self) -> None:
        """MI < 0.1 for independent series."""
        rng = np.random.default_rng(42)
        x = rng.standard_normal(500)
        y = rng.standard_normal(500)
        mi = pairwise_mi(x, y)
        assert mi < 0.1, f"Expected MI < 0.1 for independent series, got {mi:.4f}"

    def test_variation_of_information_self(self) -> None:
        """VI(x, x) should be near 0."""
        rng = np.random.default_rng(42)
        x = rng.integers(0, 10, 200)
        vi = variation_of_information(x, x)
        assert vi < 0.01, f"Expected VI(x,x) near 0, got {vi:.4f}"

    def test_variation_of_information_independent(self) -> None:
        """VI for independent series should be > 0."""
        rng = np.random.default_rng(42)
        x = rng.integers(0, 10, 200)
        y = rng.integers(0, 10, 200)
        vi = variation_of_information(x, y)
        assert vi > 0, f"Expected VI > 0 for independent, got {vi:.4f}"
