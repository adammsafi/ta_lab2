# -*- coding: utf-8 -*-
"""
Comprehensive test suite for IC computation library (src/ta_lab2/analysis/ic.py).

Test classes:
1. TestComputeForwardReturns  - arithmetic and log forward returns
2. TestComputeIC              - full IC DataFrame shape, values, edge cases
3. TestBoundaryMasking        - look-ahead bias prevention
4. TestRollingIC              - vectorized rolling IC + IC-IR
5. TestICSignificance         - t-stat and p-value correctness
6. TestFeatureTurnover        - stable vs random feature turnover
7. TestComputeICByRegime      - regime-conditional IC breakdown
8. TestBatchComputeIC         - batch wrapper over multiple feature columns
9. TestPlotICDecay            - Plotly IC decay bar chart
10. TestPlotRollingIC         - Plotly rolling IC line chart
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from ta_lab2.analysis.ic import (
    compute_feature_turnover,
    compute_forward_returns,
    compute_ic,
    compute_ic_by_regime,
    batch_compute_ic,
    compute_rolling_ic,
    plot_ic_decay,
    plot_rolling_ic,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rng():
    return np.random.default_rng(42)


@pytest.fixture(scope="module")
def index_500():
    return pd.date_range("2020-01-01", periods=500, freq="D", tz="UTC")


@pytest.fixture(scope="module")
def close_series(rng, index_500):
    """500-bar synthetic close prices starting at 100 with random walk."""
    log_returns = rng.normal(0.001, 0.02, size=500)
    prices = 100.0 * np.exp(np.cumsum(log_returns))
    return pd.Series(prices, index=index_500, name="close")


@pytest.fixture(scope="module")
def predictive_feature(close_series):
    """
    Feature correlated with next-bar return.
    Yesterday's return predicts today's return (momentum signal).
    """
    return close_series.pct_change().shift(1)


@pytest.fixture(scope="module")
def random_feature(rng, index_500):
    """Random feature with no predictive power."""
    return pd.Series(rng.standard_normal(500), index=index_500, name="random")


@pytest.fixture(scope="module")
def stable_feature(index_500):
    """
    Cumulative sum series — ranks barely change bar-to-bar.
    Expected: very low turnover (high rank autocorrelation).
    """
    vals = np.cumsum(np.ones(500)) + np.linspace(0, 1, 500) * 0.01
    return pd.Series(vals, index=index_500, name="stable")


@pytest.fixture(scope="module")
def train_start():
    return pd.Timestamp("2020-01-01", tz="UTC")


@pytest.fixture(scope="module")
def train_end():
    return pd.Timestamp("2021-06-01", tz="UTC")


# ---------------------------------------------------------------------------
# 1. TestComputeForwardReturns
# ---------------------------------------------------------------------------


class TestComputeForwardReturns:
    def test_arithmetic_length(self, close_series):
        """Full series returned; last horizon bars are NaN."""
        result = compute_forward_returns(close_series, horizon=5, log=False)
        assert len(result) == len(close_series)

    def test_arithmetic_last_bars_nan(self, close_series):
        """Last 5 bars must be NaN for horizon=5."""
        result = compute_forward_returns(close_series, horizon=5, log=False)
        assert result.iloc[-5:].isna().all()

    def test_arithmetic_non_nan_earlier_bars(self, close_series):
        """Bars before the last horizon should not be NaN."""
        result = compute_forward_returns(close_series, horizon=5, log=False)
        assert result.iloc[:-5].notna().all()

    def test_arithmetic_value_correctness(self, close_series):
        """Verify arithmetic return formula: close[t+h]/close[t] - 1."""
        result = compute_forward_returns(close_series, horizon=1, log=False)
        # check a specific bar
        expected = close_series.iloc[1] / close_series.iloc[0] - 1.0
        assert abs(result.iloc[0] - expected) < 1e-12

    def test_log_length(self, close_series):
        """Log return series has same length as input."""
        result = compute_forward_returns(close_series, horizon=5, log=True)
        assert len(result) == len(close_series)

    def test_log_last_bars_nan(self, close_series):
        """Last 5 bars must be NaN for log horizon=5."""
        result = compute_forward_returns(close_series, horizon=5, log=True)
        assert result.iloc[-5:].isna().all()

    def test_log_value_correctness(self, close_series):
        """Verify log return formula: log(close[t+h]) - log(close[t])."""
        result = compute_forward_returns(close_series, horizon=1, log=True)
        expected = np.log(close_series.iloc[1]) - np.log(close_series.iloc[0])
        assert abs(result.iloc[0] - expected) < 1e-12

    def test_full_series_computation(self, close_series):
        """compute_forward_returns works on full series, not a slice."""
        full_result = compute_forward_returns(close_series, horizon=3, log=False)
        # slice then compute vs compute on full — should produce same non-null values for earlier bars
        slice_result = compute_forward_returns(
            close_series.iloc[:100], horizon=3, log=False
        )
        # First 97 values of full series should match slice values
        np.testing.assert_allclose(
            full_result.iloc[:97].values,
            slice_result.iloc[:97].values,
            rtol=1e-10,
        )


# ---------------------------------------------------------------------------
# 2. TestComputeIC
# ---------------------------------------------------------------------------


class TestComputeIC:
    def test_requires_train_start(self, predictive_feature, close_series):
        """TypeError when train_start is omitted."""
        with pytest.raises(TypeError):
            compute_ic(predictive_feature, close_series)

    def test_requires_train_end(self, predictive_feature, close_series, train_start):
        """TypeError when train_end is omitted."""
        with pytest.raises(TypeError):
            compute_ic(predictive_feature, close_series, train_start)

    def test_default_shape(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Default horizons=[1,2,3,5,10,20,60] x return_types=['arith','log'] = 14 rows."""
        df = compute_ic(predictive_feature, close_series, train_start, train_end)
        assert len(df) == 14, f"Expected 14 rows, got {len(df)}"

    def test_required_columns(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Result must have all required columns."""
        df = compute_ic(predictive_feature, close_series, train_start, train_end)
        required = {
            "horizon",
            "return_type",
            "ic",
            "ic_t_stat",
            "ic_p_value",
            "ic_ir",
            "ic_ir_t_stat",
            "turnover",
            "n_obs",
        }
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_seven_horizons_present(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """All 7 default horizons present in result."""
        df = compute_ic(predictive_feature, close_series, train_start, train_end)
        assert set(df["horizon"].unique()) == {1, 2, 3, 5, 10, 20, 60}

    def test_two_return_types_present(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Both 'arith' and 'log' return types present."""
        df = compute_ic(predictive_feature, close_series, train_start, train_end)
        assert set(df["return_type"].unique()) == {"arith", "log"}

    def test_predictive_feature_positive_ic(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """For the momentum (predictive) feature, IC at horizon=1 arith should be > 0."""
        df = compute_ic(predictive_feature, close_series, train_start, train_end)
        row = df[(df["horizon"] == 1) & (df["return_type"] == "arith")]
        assert len(row) == 1
        ic_val = row.iloc[0]["ic"]
        # IC should be positive for a momentum signal
        assert not math.isnan(ic_val), "IC should not be NaN for predictive feature"
        assert ic_val > 0, f"Expected positive IC for predictive feature, got {ic_val}"

    def test_random_feature_ic_near_zero(
        self, random_feature, close_series, train_start, train_end
    ):
        """For random feature, |IC| should be close to 0 for all horizons."""
        df = compute_ic(random_feature, close_series, train_start, train_end)
        for _, row in df.iterrows():
            if not math.isnan(row["ic"]):
                assert abs(row["ic"]) < 0.25, (
                    f"Random feature IC={row['ic']:.4f} for horizon={row['horizon']} "
                    f"return_type={row['return_type']} — expected near 0"
                )

    def test_oversized_horizon_nan_ic(
        self, predictive_feature, close_series, train_start
    ):
        """horizon=60 on a 50-bar window should produce NaN IC."""
        short_end = train_start + pd.Timedelta(days=50)
        df = compute_ic(
            predictive_feature,
            close_series,
            train_start,
            short_end,
            horizons=[60],
        )
        for _, row in df.iterrows():
            assert math.isnan(row["ic"]), (
                f"Expected NaN IC for oversized horizon, got {row['ic']}"
            )

    def test_custom_horizons(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Custom horizons=[1, 5] -> 4 rows (2 horizons x 2 return types)."""
        df = compute_ic(
            predictive_feature,
            close_series,
            train_start,
            train_end,
            horizons=[1, 5],
        )
        assert len(df) == 4
        assert set(df["horizon"].unique()) == {1, 5}

    def test_custom_return_types(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """return_types=['arith'] -> 7 rows."""
        df = compute_ic(
            predictive_feature,
            close_series,
            train_start,
            train_end,
            return_types=["arith"],
        )
        assert len(df) == 7
        assert set(df["return_type"].unique()) == {"arith"}

    def test_n_obs_positive(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """n_obs should be > 0 for valid results."""
        df = compute_ic(predictive_feature, close_series, train_start, train_end)
        valid = df[df["ic"].notna()]
        assert (valid["n_obs"] > 0).all()

    def test_turnover_column_populated(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """turnover column should be a float (same value for all rows since it's per-feature)."""
        df = compute_ic(predictive_feature, close_series, train_start, train_end)
        valid = df[df["turnover"].notna()]
        assert len(valid) > 0, "At least some rows should have non-NaN turnover"

    def test_returns_dataframe(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """compute_ic must return a DataFrame."""
        result = compute_ic(predictive_feature, close_series, train_start, train_end)
        assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# 3. TestBoundaryMasking
# ---------------------------------------------------------------------------


class TestBoundaryMasking:
    def test_last_horizon_bars_nulled(self, close_series):
        """
        100-bar window with horizon=10, tf_days_nominal=1 (daily).
        The last 10 bars' forward returns within train window must be NaN.
        """
        from ta_lab2.analysis.ic import _compute_single_ic

        # Create 100-bar window
        idx = close_series.index[:100]
        feat = pd.Series(np.random.default_rng(99).standard_normal(100), index=idx)
        fwd_ret = compute_forward_returns(
            close_series.iloc[:100], horizon=10, log=False
        )

        train_start_b = idx[0]
        train_end_b = idx[-1]

        result = _compute_single_ic(
            feat,
            fwd_ret,
            train_start_b,
            train_end_b,
            horizon=10,
            tf_days_nominal=1,
        )
        # With last 10 bars nulled, n_obs should be <= 90
        assert result["n_obs"] <= 90, (
            f"Expected n_obs <= 90 after boundary masking, got {result['n_obs']}"
        )

    def test_boundary_prevents_look_ahead(self, close_series):
        """
        Verify that boundary masking actually removes bars near train_end.
        Create a scenario where horizon would look past train_end.
        """
        from ta_lab2.analysis.ic import _compute_single_ic

        idx = close_series.index[:50]
        feat = pd.Series(range(50), dtype=float, index=idx)
        fwd_ret = compute_forward_returns(close_series.iloc[:100], horizon=5, log=False)

        train_start_b = idx[0]
        train_end_b = idx[-1]  # last bar in 50-bar window

        result = _compute_single_ic(
            feat,
            fwd_ret,
            train_start_b,
            train_end_b,
            horizon=5,
            tf_days_nominal=1,
        )
        # n_obs should be at most 50 - 5 = 45
        if not math.isnan(result["ic"]):
            assert result["n_obs"] <= 45, (
                f"Expected n_obs <= 45 after boundary masking, got {result['n_obs']}"
            )


# ---------------------------------------------------------------------------
# 4. TestRollingIC
# ---------------------------------------------------------------------------


class TestRollingIC:
    def test_series_length_matches_input(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Rolling IC series length must equal the length of the aligned input."""
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        feat_train = predictive_feature[mask]
        fwd_ret = compute_forward_returns(close_series, horizon=1, log=False)[mask]

        rolling_ic, ic_ir, ic_ir_tstat = compute_rolling_ic(
            feat_train, fwd_ret, window=63
        )

        assert len(rolling_ic) == len(feat_train)

    def test_first_window_minus_1_bars_are_nan(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """First window-1 bars of rolling IC must be NaN."""
        window = 63
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        feat_train = predictive_feature[mask]
        fwd_ret = compute_forward_returns(close_series, horizon=1, log=False)[mask]

        rolling_ic, _, _ = compute_rolling_ic(feat_train, fwd_ret, window=window)

        assert rolling_ic.iloc[: window - 1].isna().all(), (
            f"Expected first {window - 1} bars to be NaN"
        )

    def test_remaining_bars_are_valid(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Bars from window onwards should have valid IC values (some may be NaN from dropna, but most should be valid)."""
        window = 63
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        feat_train = predictive_feature[mask]
        fwd_ret = compute_forward_returns(close_series, horizon=1, log=False)[mask]

        rolling_ic, _, _ = compute_rolling_ic(feat_train, fwd_ret, window=window)

        # After window-1, we should have some valid values
        n_valid = rolling_ic.iloc[window - 1 :].notna().sum()
        assert n_valid > 0, "Expected some valid rolling IC values after first window"

    def test_ic_ir_matches_manual_calculation(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """IC-IR = mean(rolling_IC.dropna()) / std(rolling_IC.dropna())."""
        window = 63
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        feat_train = predictive_feature[mask]
        fwd_ret = compute_forward_returns(close_series, horizon=1, log=False)[mask]

        rolling_ic, ic_ir, _ = compute_rolling_ic(feat_train, fwd_ret, window=window)

        valid_ic = rolling_ic.dropna()
        expected_ic_ir = float(valid_ic.mean()) / float(valid_ic.std(ddof=1))

        if not math.isnan(ic_ir):
            assert abs(ic_ir - expected_ic_ir) < 1e-10, (
                f"IC-IR {ic_ir:.6f} != manual {expected_ic_ir:.6f}"
            )

    def test_ic_ir_tstat_matches_manual(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """IC-IR t-stat = mean * sqrt(n) / std."""
        window = 63
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        feat_train = predictive_feature[mask]
        fwd_ret = compute_forward_returns(close_series, horizon=1, log=False)[mask]

        rolling_ic, ic_ir, ic_ir_tstat = compute_rolling_ic(
            feat_train, fwd_ret, window=window
        )

        valid_ic = rolling_ic.dropna()
        n = len(valid_ic)
        ic_mean = float(valid_ic.mean())
        ic_std = float(valid_ic.std(ddof=1))
        expected_tstat = ic_mean * np.sqrt(n) / ic_std

        if not math.isnan(ic_ir_tstat):
            assert abs(ic_ir_tstat - expected_tstat) < 1e-10, (
                f"IC-IR t-stat {ic_ir_tstat:.6f} != manual {expected_tstat:.6f}"
            )

    def test_nan_for_insufficient_data(self, index_500):
        """With fewer than 5 valid rolling IC values, ic_ir and ic_ir_tstat are NaN."""
        # Use only 4 bars of data (far less than any window)
        short_feat = pd.Series([1.0, 2.0, 3.0, 4.0], index=index_500[:4])
        short_fwd = pd.Series([0.01, -0.01, 0.02, -0.02], index=index_500[:4])

        _, ic_ir, ic_ir_tstat = compute_rolling_ic(short_feat, short_fwd, window=63)

        assert math.isnan(ic_ir), "Expected NaN ic_ir for insufficient data"
        assert math.isnan(ic_ir_tstat), "Expected NaN ic_ir_tstat for insufficient data"

    def test_returns_tuple_of_three(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """compute_rolling_ic returns (Series, float, float)."""
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        feat_train = predictive_feature[mask]
        fwd_ret = compute_forward_returns(close_series, horizon=1, log=False)[mask]

        result = compute_rolling_ic(feat_train, fwd_ret, window=63)
        assert len(result) == 3
        rolling_ic, ic_ir, ic_ir_tstat = result
        assert isinstance(rolling_ic, pd.Series)
        assert isinstance(ic_ir, (float, int)) or math.isnan(ic_ir)
        assert isinstance(ic_ir_tstat, (float, int)) or math.isnan(ic_ir_tstat)


# ---------------------------------------------------------------------------
# 5. TestICSignificance
# ---------------------------------------------------------------------------


class TestICSignificance:
    def test_t_stat_formula_positive_ic(self):
        """t_stat = ic * sqrt(n-2) / sqrt(max(1-ic^2, 1e-15))."""
        from ta_lab2.analysis.ic import _ic_t_stat

        ic = 0.3
        n = 100
        expected = ic * np.sqrt(n - 2) / np.sqrt(max(1 - ic**2, 1e-15))
        result = _ic_t_stat(ic, n)
        assert abs(result - expected) < 1e-10

    def test_t_stat_formula_negative_ic(self):
        """t_stat formula works for negative IC."""
        from ta_lab2.analysis.ic import _ic_t_stat

        ic = -0.4
        n = 200
        expected = ic * np.sqrt(n - 2) / np.sqrt(max(1 - ic**2, 1e-15))
        result = _ic_t_stat(ic, n)
        assert abs(result - expected) < 1e-10

    def test_t_stat_guard_at_ic_equals_1(self):
        """When |ic| = 1.0, denominator guarded by 1e-15 — finite result."""
        from ta_lab2.analysis.ic import _ic_t_stat

        result = _ic_t_stat(1.0, 100)
        assert math.isfinite(result), "t_stat should be finite when |ic|=1"
        assert result > 0, "t_stat should be positive when ic=1"

    def test_t_stat_guard_at_ic_equals_minus_1(self):
        """When ic = -1.0, result is finite and negative."""
        from ta_lab2.analysis.ic import _ic_t_stat

        result = _ic_t_stat(-1.0, 100)
        assert math.isfinite(result), "t_stat should be finite when ic=-1"
        assert result < 0, "t_stat should be negative when ic=-1"

    def test_p_value_two_sided(self):
        """p_value = 2 * (1 - norm.cdf(|t_stat|)) — two-sided test."""
        from scipy.stats import norm
        from ta_lab2.analysis.ic import _ic_p_value

        t_stat = 2.0
        expected = float(2 * (1 - norm.cdf(abs(t_stat))))
        result = _ic_p_value(t_stat)
        assert abs(result - expected) < 1e-12

    def test_p_value_large_t_stat_near_zero(self):
        """Very large t_stat produces p_value near 0."""
        from ta_lab2.analysis.ic import _ic_p_value

        result = _ic_p_value(10.0)
        assert result < 0.001, f"Expected p<0.001 for t=10, got {result}"

    def test_p_value_zero_t_stat_near_one(self):
        """t_stat = 0 produces p_value near 1.0 (two-sided)."""
        from ta_lab2.analysis.ic import _ic_p_value

        result = _ic_p_value(0.0)
        assert abs(result - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# 6. TestFeatureTurnover
# ---------------------------------------------------------------------------


class TestFeatureTurnover:
    def test_stable_feature_near_zero(self, stable_feature):
        """Stable feature (monotonically increasing) -> turnover near 0."""
        turnover = compute_feature_turnover(stable_feature)
        assert not math.isnan(turnover), "Expected finite turnover for stable feature"
        assert turnover < 0.1, (
            f"Expected turnover < 0.1 for stable feature, got {turnover:.4f}"
        )

    def test_random_feature_near_one(self, random_feature):
        """Random feature -> turnover near 1 (low rank autocorrelation)."""
        turnover = compute_feature_turnover(random_feature)
        assert not math.isnan(turnover), "Expected finite turnover for random feature"
        # Random walk has ~0 autocorrelation => turnover ~1
        assert turnover > 0.8, (
            f"Expected turnover > 0.8 for random feature, got {turnover:.4f}"
        )

    def test_nan_for_small_n(self, index_500):
        """With fewer than 20 obs, returns NaN."""
        small = pd.Series([1.0, 2.0, 3.0], index=index_500[:3])
        result = compute_feature_turnover(small, min_obs=20)
        assert math.isnan(result), "Expected NaN for small n"

    def test_returns_float(self, stable_feature):
        """compute_feature_turnover returns a float."""
        result = compute_feature_turnover(stable_feature)
        assert isinstance(result, float)

    def test_turnover_range(self, random_feature):
        """Turnover should be between -1 and 2 (1 - spearmanr range)."""
        result = compute_feature_turnover(random_feature)
        if not math.isnan(result):
            assert -1.0 <= result <= 2.0, (
                f"Turnover {result} outside expected range [-1, 2]"
            )

    def test_formula_correctness(self, stable_feature):
        """Verify: turnover = 1 - spearmanr(ranks[:-1], ranks[1:]).statistic."""
        from scipy.stats import spearmanr

        feature_clean = stable_feature.dropna()
        ranks = feature_clean.rank()
        expected = float(
            1 - spearmanr(ranks.iloc[:-1].values, ranks.iloc[1:].values).statistic
        )
        result = compute_feature_turnover(stable_feature)
        assert abs(result - expected) < 1e-10


# ---------------------------------------------------------------------------
# 7. TestComputeICByRegime
# ---------------------------------------------------------------------------


def _make_regime_series(index, labels_cycle):
    """Helper: build a regime Series alternating labels across the index."""
    labels = [labels_cycle[i % len(labels_cycle)] for i in range(len(index))]
    return pd.Series(labels, index=index, name="trend_state")


class TestComputeICByRegime:
    def test_empty_regimes_returns_full_sample(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Pass empty DataFrame -> result has regime_label='all' and matches compute_ic output."""
        empty_regimes = pd.DataFrame(
            columns=["trend_state"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        result = compute_ic_by_regime(
            predictive_feature,
            close_series,
            empty_regimes,
            train_start,
            train_end,
            regime_col="trend_state",
        )
        assert isinstance(result, pd.DataFrame)
        assert (result["regime_label"] == "all").all()
        assert (result["regime_col"] == "trend_state").all()
        # Shape should match full compute_ic output (14 rows by default)
        assert len(result) == 14

    def test_none_regimes_returns_full_sample(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Pass None -> same result as empty DataFrame (regime_label='all')."""
        result = compute_ic_by_regime(
            predictive_feature,
            close_series,
            None,
            train_start,
            train_end,
            regime_col="trend_state",
        )
        assert isinstance(result, pd.DataFrame)
        assert (result["regime_label"] == "all").all()
        assert len(result) == 14

    def test_splits_by_regime_label(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """
        Create synthetic regimes_df with 2 labels ('Up', 'Down'), each with
        many bars. Verify separate IC rows per label.
        """
        # Build regimes_df covering the full train window
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        train_idx = predictive_feature[mask].index

        # Alternate 'Up' and 'Down' every bar
        regime_series = _make_regime_series(train_idx, ["Up", "Down"])
        regimes_df = regime_series.to_frame(name="trend_state")

        result = compute_ic_by_regime(
            predictive_feature,
            close_series,
            regimes_df,
            train_start,
            train_end,
            regime_col="trend_state",
            min_obs_per_regime=30,
        )

        assert isinstance(result, pd.DataFrame)
        labels_found = set(result["regime_label"].unique())
        # Both labels should be present (enough bars per regime)
        assert "Up" in labels_found, f"Expected 'Up' label, got: {labels_found}"
        assert "Down" in labels_found, f"Expected 'Down' label, got: {labels_found}"
        assert "all" not in labels_found, "Should not have 'all' when regimes provided"

    def test_sparse_regime_skipped(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """
        Create regime 'Rare' with only 10 bars. That label should not appear in results.
        The dominant regime 'Common' has many bars and should appear.
        """
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        train_idx = predictive_feature[mask].index

        # 10 'Rare' bars, rest 'Common'
        labels = ["Common"] * len(train_idx)
        for i in range(min(10, len(train_idx))):
            labels[i] = "Rare"

        regime_series = pd.Series(labels, index=train_idx, name="trend_state")
        regimes_df = regime_series.to_frame(name="trend_state")

        result = compute_ic_by_regime(
            predictive_feature,
            close_series,
            regimes_df,
            train_start,
            train_end,
            regime_col="trend_state",
            min_obs_per_regime=30,
        )

        labels_found = set(result["regime_label"].unique())
        assert "Rare" not in labels_found, (
            f"Sparse 'Rare' regime should be skipped, got labels: {labels_found}"
        )
        assert "Common" in labels_found, (
            f"'Common' regime should be present, got labels: {labels_found}"
        )

    def test_regime_col_parameter(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Pass regime_col='vol_state' with 'High'/'Low' labels -> results have correct regime_col and regime_label values."""
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        train_idx = predictive_feature[mask].index

        regime_series = _make_regime_series(train_idx, ["High", "Low"])
        regimes_df = regime_series.rename("vol_state").to_frame(name="vol_state")

        result = compute_ic_by_regime(
            predictive_feature,
            close_series,
            regimes_df,
            train_start,
            train_end,
            regime_col="vol_state",
            min_obs_per_regime=30,
        )

        assert isinstance(result, pd.DataFrame)
        assert (result["regime_col"] == "vol_state").all(), (
            f"Expected regime_col='vol_state', got: {result['regime_col'].unique()}"
        )
        labels_found = set(result["regime_label"].unique())
        assert "High" in labels_found, f"Expected 'High', got: {labels_found}"
        assert "Low" in labels_found, f"Expected 'Low', got: {labels_found}"


# ---------------------------------------------------------------------------
# 8. TestBatchComputeIC
# ---------------------------------------------------------------------------


class TestBatchComputeIC:
    @pytest.fixture(scope="class")
    def features_df(self, close_series):
        """DataFrame with 3 numeric feature columns."""
        rng = np.random.default_rng(77)
        idx = close_series.index
        return pd.DataFrame(
            {
                "feat_a": rng.standard_normal(len(idx)),
                "feat_b": close_series.pct_change().shift(1).values,
                "feat_c": rng.standard_normal(len(idx)) * 2,
            },
            index=idx,
        )

    def test_batch_multiple_features(
        self, features_df, close_series, train_start, train_end
    ):
        """Pass DataFrame with 3 numeric columns -> result has 'feature' column with all 3 names."""
        result = batch_compute_ic(
            features_df,
            close_series,
            train_start,
            train_end,
        )
        assert isinstance(result, pd.DataFrame)
        assert "feature" in result.columns
        features_found = set(result["feature"].unique())
        assert features_found == {"feat_a", "feat_b", "feat_c"}, (
            f"Expected all 3 features, got: {features_found}"
        )

    def test_batch_feature_cols_filter(
        self, features_df, close_series, train_start, train_end
    ):
        """Pass feature_cols=['feat_a', 'feat_b'] when df has 3 columns -> only 2 features in result."""
        result = batch_compute_ic(
            features_df,
            close_series,
            train_start,
            train_end,
            feature_cols=["feat_a", "feat_b"],
        )
        features_found = set(result["feature"].unique())
        assert features_found == {"feat_a", "feat_b"}, (
            f"Expected only feat_a and feat_b, got: {features_found}"
        )
        assert "feat_c" not in features_found

    def test_batch_shape(self, features_df, close_series, train_start, train_end):
        """
        3 features x 7 horizons x 2 return types = 42 rows.
        """
        result = batch_compute_ic(
            features_df,
            close_series,
            train_start,
            train_end,
        )
        # Default: 3 features x 7 horizons x 2 return_types = 42
        assert len(result) == 42, (
            f"Expected 42 rows (3 features x 7 horizons x 2 return_types), got {len(result)}"
        )

    def test_batch_excludes_close_column(self, close_series, train_start, train_end):
        """When features_df has a 'close' column, it should be excluded from feature_cols."""
        rng = np.random.default_rng(88)
        idx = close_series.index
        df_with_close = pd.DataFrame(
            {
                "feat_x": rng.standard_normal(len(idx)),
                "close": close_series.values,
            },
            index=idx,
        )
        result = batch_compute_ic(
            df_with_close,
            close_series,
            train_start,
            train_end,
        )
        features_found = set(result["feature"].unique())
        assert "close" not in features_found, (
            f"'close' column should be excluded, got: {features_found}"
        )
        assert "feat_x" in features_found


# ---------------------------------------------------------------------------
# 9. TestPlotICDecay
# ---------------------------------------------------------------------------


class TestPlotICDecay:
    @pytest.fixture(scope="class")
    def ic_df_for_plot(self, predictive_feature, close_series, train_start, train_end):
        """Compute a standard IC DataFrame filtered to 'arith' return type."""
        df = compute_ic(
            predictive_feature,
            close_series,
            train_start,
            train_end,
            horizons=[1, 2, 3, 5, 10, 20, 60],
            return_types=["arith"],
        )
        return df

    def test_returns_plotly_figure(
        self, ic_df_for_plot, predictive_feature, close_series, train_start, train_end
    ):
        """plot_ic_decay returns a plotly Figure."""
        import plotly.graph_objects as go

        fig = plot_ic_decay(ic_df_for_plot, feature="predictive_feature")
        assert isinstance(fig, go.Figure), f"Expected go.Figure, got {type(fig)}"

    def test_bar_count_matches_horizons(
        self, ic_df_for_plot, predictive_feature, close_series, train_start, train_end
    ):
        """Number of bars in figure.data[0] matches len(ic_df)."""
        fig = plot_ic_decay(ic_df_for_plot, feature="predictive_feature")
        # figure.data[0] is the Bar trace
        bar_trace = fig.data[0]
        n_bars = len(bar_trace.x)
        assert n_bars == len(ic_df_for_plot), (
            f"Expected {len(ic_df_for_plot)} bars, got {n_bars}"
        )

    def test_significance_coloring(self, close_series, train_start, train_end):
        """With mix of p < 0.05 and p > 0.05 -> verify marker_color list has both 'royalblue' and 'lightgray'."""
        import plotly.graph_objects as go

        # Build a synthetic ic_df with known p-values spanning both sides of 0.05
        ic_df_mixed = pd.DataFrame(
            {
                "horizon": [1, 2, 3, 5, 10, 20, 60],
                "return_type": ["arith"] * 7,
                "ic": [0.3, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005],
                # Mix: first 3 below 0.05, last 4 above 0.05
                "ic_p_value": [0.01, 0.02, 0.04, 0.10, 0.20, 0.40, 0.80],
            }
        )

        fig = plot_ic_decay(ic_df_mixed, feature="test_feature")
        assert isinstance(fig, go.Figure)

        bar_trace = fig.data[0]
        colors = list(bar_trace.marker.color)

        assert "royalblue" in colors, "Expected at least one 'royalblue' bar (p < 0.05)"
        assert "lightgray" in colors, (
            "Expected at least one 'lightgray' bar (p >= 0.05)"
        )

    def test_title_includes_feature_name(self, ic_df_for_plot):
        """Figure title should include the feature name."""
        feature_name = "my_test_feature"
        fig = plot_ic_decay(ic_df_for_plot, feature=feature_name)
        title_text = fig.layout.title.text
        assert feature_name in title_text, (
            f"Expected '{feature_name}' in title, got: '{title_text}'"
        )


# ---------------------------------------------------------------------------
# 10. TestPlotRollingIC
# ---------------------------------------------------------------------------


class TestPlotRollingIC:
    @pytest.fixture(scope="class")
    def rolling_ic_series(
        self, predictive_feature, close_series, train_start, train_end
    ):
        """Compute rolling IC series for use in plot tests."""
        mask = (predictive_feature.index >= train_start) & (
            predictive_feature.index <= train_end
        )
        feat_train = predictive_feature[mask]
        fwd_ret = compute_forward_returns(close_series, horizon=1, log=False)[mask]
        rolling_ic, _, _ = compute_rolling_ic(feat_train, fwd_ret, window=63)
        return rolling_ic

    def test_returns_plotly_figure(self, rolling_ic_series):
        """plot_rolling_ic returns a plotly Figure."""
        import plotly.graph_objects as go

        fig = plot_rolling_ic(rolling_ic_series, feature="predictive_feature")
        assert isinstance(fig, go.Figure), f"Expected go.Figure, got {type(fig)}"

    def test_title_includes_feature_name(self, rolling_ic_series):
        """Figure title should contain the feature name."""
        feature_name = "my_rolling_feature"
        fig = plot_rolling_ic(rolling_ic_series, feature=feature_name)
        title_text = fig.layout.title.text
        assert feature_name in title_text, (
            f"Expected '{feature_name}' in title, got: '{title_text}'"
        )

    def test_has_zero_reference_line(self, rolling_ic_series):
        """Figure should include a horizontal reference line at y=0."""
        fig = plot_rolling_ic(rolling_ic_series, feature="test_feature")
        # add_hline creates a shape in layout.shapes
        has_zero_line = any(
            shape.y0 == 0 and shape.y1 == 0
            for shape in fig.layout.shapes
            if hasattr(shape, "y0")
        )
        assert has_zero_line, "Expected a horizontal reference line at y=0"

    def test_horizon_and_return_type_in_title(self, rolling_ic_series):
        """When horizon and return_type are provided, they appear in the title."""
        fig = plot_rolling_ic(
            rolling_ic_series,
            feature="my_feature",
            horizon=5,
            return_type="log",
        )
        title_text = fig.layout.title.text
        assert "horizon=5" in title_text, (
            f"Expected 'horizon=5' in title: '{title_text}'"
        )
        assert "return_type=log" in title_text, (
            f"Expected 'return_type=log' in title: '{title_text}'"
        )
