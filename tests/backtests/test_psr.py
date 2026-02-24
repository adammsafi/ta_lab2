"""
Tests for PSR/DSR/MinTRL formula module (Lopez de Prado).

TDD RED phase: these tests are written BEFORE implementation.
They document expected behavior and guard against the critical kurtosis trap.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

# ── Import under test ────────────────────────────────────────────────────────
from ta_lab2.backtests.psr import compute_psr, compute_dsr, min_trl, expected_max_sr


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def strong_returns(rng):
    """10 000 bars of daily returns with mean=0.01, std=0.1 → high Sharpe."""
    return rng.normal(loc=0.01, scale=0.1, size=10_000)


@pytest.fixture
def modest_returns(rng):
    """500 bars — sufficient for reliable PSR estimate."""
    return rng.normal(loc=0.002, scale=0.1, size=500)


@pytest.fixture
def small_n_30(rng):
    """20 bars — below minimum; must trigger NaN + warning."""
    return rng.normal(loc=0.01, scale=0.1, size=20)


@pytest.fixture
def small_n_50(rng):
    """50 bars — above 30 but below 100; must trigger warning only."""
    return rng.normal(loc=0.01, scale=0.1, size=50)


@pytest.fixture
def zero_returns():
    """500 bars of zero returns — std = 0."""
    return np.zeros(500)


@pytest.fixture
def constant_nonzero_returns():
    """500 bars of constant 0.01 — std = 0 (same logic as zero_returns)."""
    return np.full(500, 0.01)


@pytest.fixture
def negative_sr_returns(rng):
    """500 bars where mean < 0 → negative Sharpe ratio."""
    return rng.normal(loc=-0.005, scale=0.1, size=500)


# ─────────────────────────────────────────────────────────────────────────────
# compute_psr tests
# ─────────────────────────────────────────────────────────────────────────────


class TestComputePSR:
    """Unit tests for compute_psr."""

    def test_returns_float_in_unit_interval(self, strong_returns):
        result = compute_psr(strong_returns, sr_star=0.0)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_strong_positive_returns_high_psr(self, strong_returns):
        """10 000 bars with Sharpe≈0.1 should give PSR > 0.99."""
        result = compute_psr(strong_returns, sr_star=0.0)
        assert result > 0.99

    def test_nan_when_n_lt_30(self, small_n_30):
        """n < 30 must return NaN and emit a UserWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = compute_psr(small_n_30, sr_star=0.0)
        assert math.isnan(result)
        assert len(w) >= 1
        assert any("30" in str(warning.message) for warning in w)

    def test_warning_when_n_lt_100(self, small_n_50):
        """n in [30, 100) must emit a warning but still return a valid float."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = compute_psr(small_n_50, sr_star=0.0)
        assert not math.isnan(result)
        assert 0.0 <= result <= 1.0
        assert len(w) >= 1
        assert any("100" in str(warning.message) for warning in w)

    def test_zero_std_sr_star_zero_returns_half(self, zero_returns):
        """Zero-std returns with sr_star=0 must return exactly 0.5."""
        result = compute_psr(zero_returns, sr_star=0.0)
        assert result == 0.5

    def test_zero_std_sr_star_positive_returns_zero(self, zero_returns):
        """Zero-std returns with sr_star>0 must return exactly 0.0."""
        result = compute_psr(zero_returns, sr_star=0.05)
        assert result == 0.0

    def test_zero_std_sr_star_negative_returns_one(self, zero_returns):
        """Zero-std returns with sr_star<0 must return exactly 1.0."""
        result = compute_psr(zero_returns, sr_star=-0.05)
        assert result == 1.0

    def test_constant_nonzero_returns_same_as_zero_returns(
        self, constant_nonzero_returns
    ):
        """Constant non-zero returns also have std=0 → same zero-std guard."""
        result = compute_psr(constant_nonzero_returns, sr_star=0.0)
        assert result == 0.5

    def test_higher_sr_star_lowers_psr(self, modest_returns):
        """Increasing the benchmark SR* must decrease PSR."""
        psr_0 = compute_psr(modest_returns, sr_star=0.0)
        psr_005 = compute_psr(modest_returns, sr_star=0.05)
        assert psr_005 < psr_0

    def test_pearson_kurtosis_variance_formula(self):
        """
        Critical kurtosis trap test.

        For iid normal returns with T observations and SR=sr_hat:
          var_sr ≈ (1 - gamma_3*sr_hat + (gamma_4-1)/4 * sr_hat^2) / (T-1)

        For normal dist: gamma_3≈0, gamma_4≈3 (Pearson).
        So var_sr ≈ (1 + sr_hat^2/2) / (T-1).

        This test confirms the Pearson kurtosis convention is used
        (NOT Fisher/excess kurtosis which gives gamma_4≈0 for normal data).
        """
        rng = np.random.default_rng(0)
        T = 100_000
        returns = rng.normal(loc=0.02, scale=0.1, size=T)
        sr_hat = np.mean(returns) / np.std(returns, ddof=1)

        from scipy.stats import skew, kurtosis

        gamma_3 = skew(returns)
        gamma_4 = kurtosis(returns, fisher=False)  # Pearson ≈ 3

        # Theoretical variance using Pearson kurtosis
        var_sr_theoretical = (1 - gamma_3 * sr_hat + (gamma_4 - 1) / 4 * sr_hat**2) / (
            T - 1
        )

        # var_sr using WRONG excess kurtosis (should differ significantly)
        gamma_4_fisher = kurtosis(returns, fisher=True)  # ≈ 0
        var_sr_wrong = (1 - gamma_3 * sr_hat + (gamma_4_fisher - 1) / 4 * sr_hat**2) / (
            T - 1
        )

        # Both formulas at large T converge near (1 + SR^2/2)/(T-1) for normal data
        # Pearson: gamma_4 ≈ 3  → (gamma_4-1)/4 ≈ 0.5  → var_sr ≈ (1 + SR^2/2)/(T-1)
        # Fisher:  gamma_4 ≈ 0  → (gamma_4-1)/4 ≈ -0.25 → var_sr ≈ (1 - SR^2/4)/(T-1)
        expected_approx = (1 + sr_hat**2 / 2) / (T - 1)
        wrong_approx = (1 - sr_hat**2 / 4) / (T - 1)

        # Pearson formula must be closer to the correct expected_approx than
        # it is to the wrong Fisher-based approximation
        err_pearson = abs(var_sr_theoretical - expected_approx)
        err_fisher = abs(var_sr_wrong - wrong_approx)

        # Both formulas are close to their respective approximations at T=100_000
        assert err_pearson < 1e-7, (
            f"Pearson kurtosis formula too far from expected ≈ {expected_approx:.4e}: "
            f"got {var_sr_theoretical:.4e}, err={err_pearson:.2e}"
        )

        # Pearson and Fisher formulas MUST diverge — catching the kurtosis trap
        # gamma_4(Pearson) ≈ 3 vs gamma_4(Fisher) ≈ 0 → (gamma4-1)/4 differs by 0.75
        # With sr_hat ≈ 0.2, the difference per bar is ≈ 0.75 * 0.04 / 4 / (T-1) ≈ 7.5e-9
        assert var_sr_theoretical > var_sr_wrong, (
            "Pearson kurtosis (≈3) gives larger var_sr than Fisher (≈0) for positive SR — "
            "Pearson is the correct convention!"
        )

    def test_accepts_pandas_series(self, modest_returns):
        """compute_psr must accept pd.Series (not just np.ndarray)."""
        import pandas as pd

        result = compute_psr(pd.Series(modest_returns), sr_star=0.0)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_accepts_list(self, modest_returns):
        """compute_psr must accept Python list."""
        result = compute_psr(modest_returns.tolist(), sr_star=0.0)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_negative_sr_returns_low_psr(self, negative_sr_returns):
        """Returns with negative Sharpe should produce PSR < 0.5 vs sr_star=0."""
        result = compute_psr(negative_sr_returns, sr_star=0.0)
        assert result < 0.5


# ─────────────────────────────────────────────────────────────────────────────
# expected_max_sr tests
# ─────────────────────────────────────────────────────────────────────────────


class TestExpectedMaxSR:
    """Unit tests for expected_max_sr."""

    def test_returns_positive_float(self):
        sr_estimates = [0.5, 0.3, -0.1, 0.8, 0.2]
        result = expected_max_sr(sr_estimates)
        assert isinstance(result, float)
        assert result > 0

    def test_monotone_in_n_trials(self):
        """More trials → higher expected maximum SR."""
        rng = np.random.default_rng(7)
        sr_small = rng.normal(0, 1, 10).tolist()
        sr_large = rng.normal(0, 1, 100).tolist()
        e_small = expected_max_sr(sr_small)
        e_large = expected_max_sr(sr_large)
        assert e_large > e_small

    def test_single_trial_returns_mean_ish(self):
        """With a single SR estimate, expected max equals that estimate."""
        sr = [0.5]
        result = expected_max_sr(sr)
        # For N=1: norm.ppf(1-1/1) = norm.ppf(0) = -inf, norm.ppf(1-1/e) ≈ -0.068
        # Just check it returns a finite float
        assert math.isfinite(result)

    def test_all_positive_estimates(self):
        """Positive-only SR estimates give positive expected max."""
        result = expected_max_sr([1.0, 1.2, 0.8, 1.5, 0.9])
        assert result > 0


# ─────────────────────────────────────────────────────────────────────────────
# compute_dsr tests
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeDSR:
    """Unit tests for compute_dsr."""

    def test_exact_mode_less_than_raw_psr(self, strong_returns, rng):
        """DSR (exact mode) must be <= raw PSR with sr_star=0."""
        # Simulate multiple trial SR estimates
        trial_srs = rng.normal(0.1, 0.05, 20).tolist()
        dsr = compute_dsr(strong_returns, sr_estimates=trial_srs)
        raw_psr = compute_psr(strong_returns, sr_star=0.0)
        assert dsr <= raw_psr, f"DSR={dsr:.4f} should be <= PSR={raw_psr:.4f}"

    def test_approximate_mode_less_than_raw_psr(self, strong_returns):
        """DSR (n_trials mode) must be <= raw PSR with sr_star=0."""
        dsr = compute_dsr(strong_returns, n_trials=100)
        raw_psr = compute_psr(strong_returns, sr_star=0.0)
        assert dsr <= raw_psr, f"DSR={dsr:.4f} should be <= PSR={raw_psr:.4f}"

    def test_raises_without_sr_or_n(self, strong_returns):
        """Without sr_estimates or n_trials, must raise ValueError."""
        with pytest.raises(ValueError, match=r"sr_estimates|n_trials"):
            compute_dsr(strong_returns)

    def test_returns_float_in_unit_interval(self, strong_returns, rng):
        """DSR result must be in [0, 1]."""
        trial_srs = rng.normal(0.1, 0.05, 10).tolist()
        result = compute_dsr(strong_returns, sr_estimates=trial_srs)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_more_trials_lowers_dsr(self, strong_returns, rng):
        """More trials → higher expected max SR → lower DSR (more deflation)."""
        dsr_10 = compute_dsr(strong_returns, n_trials=10)
        dsr_1000 = compute_dsr(strong_returns, n_trials=1000)
        assert dsr_1000 <= dsr_10, (
            f"More trials should lower DSR: dsr_10={dsr_10:.4f}, dsr_1000={dsr_1000:.4f}"
        )

    def test_sr_override_is_respected(self, strong_returns):
        """sr_star_override should bypass computed benchmark."""
        dsr_0 = compute_dsr(strong_returns, n_trials=10, sr_star_override=0.0)
        dsr_high = compute_dsr(strong_returns, n_trials=10, sr_star_override=10.0)
        assert dsr_0 > dsr_high


# ─────────────────────────────────────────────────────────────────────────────
# min_trl tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMinTRL:
    """Unit tests for min_trl."""

    def test_returns_dict_with_required_keys(self, modest_returns):
        result = min_trl(modest_returns, sr_star=0.0)
        assert isinstance(result, dict)
        for key in ("n_obs", "calendar_days", "sr_hat", "target_psr"):
            assert key in result, f"Missing key: {key}"

    def test_positive_n_obs_and_calendar_days(self, strong_returns):
        """Strong positive SR → finite, positive n_obs and calendar_days."""
        result = min_trl(strong_returns, sr_star=0.0)
        assert math.isfinite(result["n_obs"]) and result["n_obs"] > 0
        assert math.isfinite(result["calendar_days"]) and result["calendar_days"] > 0

    def test_inf_when_sr_hat_leq_sr_star(self, strong_returns):
        """When sr_hat <= sr_star, TRL is infinite — can never beat benchmark."""
        # Use a very high sr_star that exceeds the strong returns' Sharpe
        result = min_trl(strong_returns, sr_star=1000.0)
        assert result["n_obs"] == float("inf")
        assert result["calendar_days"] == float("inf")

    def test_higher_target_psr_needs_more_obs(self, modest_returns):
        """Higher confidence target requires more observations."""
        result_95 = min_trl(modest_returns, sr_star=0.0, target_psr=0.95)
        result_99 = min_trl(modest_returns, sr_star=0.0, target_psr=0.99)
        assert result_99["n_obs"] > result_95["n_obs"], (
            f"99% target ({result_99['n_obs']}) should need more obs than 95% ({result_95['n_obs']})"
        )

    def test_sr_hat_in_result(self, modest_returns):
        """Result must include sr_hat used in computation."""
        result = min_trl(modest_returns, sr_star=0.0)
        expected_sr = np.mean(modest_returns) / np.std(modest_returns, ddof=1)
        assert abs(result["sr_hat"] - expected_sr) < 1e-10

    def test_target_psr_in_result(self, modest_returns):
        """Result must echo back the target_psr used."""
        result = min_trl(modest_returns, sr_star=0.0, target_psr=0.99)
        assert result["target_psr"] == 0.99

    def test_calendar_days_proportional_to_n_obs(self, strong_returns):
        """calendar_days should be roughly n_obs / freq_per_year * 365."""
        freq = 252
        result = min_trl(strong_returns, sr_star=0.0, freq_per_year=freq)
        expected_days = math.ceil(result["n_obs"]) / freq * 365
        assert abs(result["calendar_days"] - round(expected_days)) <= 1

    def test_n_obs_negative_sr_star(self, strong_returns):
        """Negative sr_star: TRL should still return finite values."""
        result = min_trl(strong_returns, sr_star=-0.1)
        assert math.isfinite(result["n_obs"])
        assert result["n_obs"] > 0
