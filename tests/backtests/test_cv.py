"""
Tests for PurgedKFoldSplitter and CPCVSplitter.

Tests follow RED-GREEN-REFACTOR TDD cycle.
CV-01: PurgedKFoldSplitter inherits BaseCrossValidator, t1_series required
CV-02: Embargo gap parameterized via embargo_frac, monotonic index validation
CV-03: CPCVSplitter generates combinatorial path matrix, correct path count
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.model_selection import BaseCrossValidator, cross_val_score

from ta_lab2.backtests.cv import CPCVSplitter, PurgedKFoldSplitter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_series(n: int = 100, start: str = "2020-01-01") -> pd.Series:
    """
    Build a t1_series of label-end timestamps.

    Each label ends 3 bars after its start (simulating a 3-bar holding period).
    The series index is the label-start timestamp; values are label-end timestamps.
    """
    idx = pd.date_range(start=start, periods=n, freq="D", tz="UTC")
    t1 = idx.shift(3)  # label ends 3 bars later
    return pd.Series(t1, index=idx)


def _make_features(n: int = 100) -> np.ndarray:
    """Simple feature matrix (n x 2) with constant values."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((n, 2))


def _make_labels(n: int = 100) -> np.ndarray:
    """Binary labels (0 or 1) of length n."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 2, size=n)


# ---------------------------------------------------------------------------
# PurgedKFoldSplitter — CV-01 basic interface
# ---------------------------------------------------------------------------


class TestPurgedKFoldSplitterInterface:
    """CV-01: Basic interface requirements."""

    def test_inherits_base_cross_validator(self):
        """PurgedKFoldSplitter must inherit from sklearn BaseCrossValidator."""
        t1 = _make_series()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        assert isinstance(splitter, BaseCrossValidator)

    def test_raises_value_error_when_t1_none(self):
        """ValueError must be raised when t1_series is None (the default)."""
        with pytest.raises(ValueError, match="t1_series is required"):
            PurgedKFoldSplitter(n_splits=5, t1_series=None)

    def test_raises_value_error_no_t1_kwarg(self):
        """ValueError must be raised when t1_series is omitted entirely."""
        with pytest.raises(ValueError, match="t1_series is required"):
            PurgedKFoldSplitter(n_splits=5)

    def test_get_n_splits_returns_correct_value(self):
        """get_n_splits() must return n_splits."""
        t1 = _make_series()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        assert splitter.get_n_splits() == 5

    def test_get_n_splits_with_arguments(self):
        """get_n_splits() accepts X, y, groups kwargs per sklearn API."""
        t1 = _make_series()
        X = _make_features()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        assert splitter.get_n_splits(X=X, y=None, groups=None) == 5

    def test_yields_exactly_n_splits(self):
        """split() must yield exactly n_splits (train, test) tuples."""
        t1 = _make_series()
        X = _make_features()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        folds = list(splitter.split(X))
        assert len(folds) == 5

    def test_split_returns_tuple_of_arrays(self):
        """Each split must be a 2-tuple of integer index arrays."""
        t1 = _make_series()
        X = _make_features()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        for train_idx, test_idx in splitter.split(X):
            assert isinstance(train_idx, np.ndarray)
            assert isinstance(test_idx, np.ndarray)
            assert train_idx.dtype.kind == "i"  # integer dtype
            assert test_idx.dtype.kind == "i"

    def test_all_samples_covered_in_test_folds(self):
        """Union of all test folds must cover all sample indices."""
        t1 = _make_series()
        X = _make_features()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        all_test = set()
        for _, test_idx in splitter.split(X):
            all_test |= set(test_idx.tolist())
        assert all_test == set(range(len(X)))


# ---------------------------------------------------------------------------
# PurgedKFoldSplitter — no train/test overlap
# ---------------------------------------------------------------------------


class TestPurgedKFoldNoOverlap:
    """No train observation may appear in the test set."""

    def test_no_train_test_overlap_5_folds(self):
        """No index appears in both train and test for any fold."""
        t1 = _make_series(100)
        X = _make_features(100)
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        for train_idx, test_idx in splitter.split(X):
            overlap = set(train_idx.tolist()) & set(test_idx.tolist())
            assert overlap == set(), f"Overlap found: {overlap}"

    def test_no_train_test_overlap_10_folds(self):
        """No overlap with 10 folds on 200 samples."""
        t1 = _make_series(200)
        X = _make_features(200)
        splitter = PurgedKFoldSplitter(n_splits=10, t1_series=t1)
        for train_idx, test_idx in splitter.split(X):
            overlap = set(train_idx.tolist()) & set(test_idx.tolist())
            assert overlap == set()


# ---------------------------------------------------------------------------
# PurgedKFoldSplitter — purge correctness
# ---------------------------------------------------------------------------


class TestPurgedKFoldPurge:
    """
    Purge: training obs whose label-end (t1[i]) overlaps the test period are removed.

    A training obs i is purged when: t1.iloc[i] > test_fold_start_timestamp.
    This ensures no label from training bleeds into the test window.
    """

    def test_purge_removes_overlapping_labels(self):
        """
        Construct scenario with 3-bar labels. Obs in train whose t1 > test_start
        must be removed from the training set.
        """
        n = 60
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        # 3-bar label: label ends 3 days after start
        t1 = pd.Series(idx.shift(3), index=idx)

        X = _make_features(n)
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1, embargo_frac=0.0)

        for train_idx, test_idx in splitter.split(X):
            # determine the test window start
            test_start_ts = t1.index[test_idx.min()]

            # for each train obs, t1 value must NOT exceed test_start_ts
            for i in train_idx:
                assert t1.iloc[i] <= test_start_ts, (
                    f"Train obs {i} has t1={t1.iloc[i]} which leaks into test "
                    f"starting at {test_start_ts}"
                )

    def test_purge_applied_after_test_fold(self):
        """
        Training indices just before the test fold may have labels that overlap
        the test period. Those indices must NOT appear in train.
        """
        n = 50
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        # Large label span: 5 bars
        t1 = pd.Series(idx.shift(5), index=idx)
        X = _make_features(n)

        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1, embargo_frac=0.0)
        for train_idx, test_idx in splitter.split(X):
            test_start_ts = t1.index[test_idx.min()]
            for i in train_idx:
                # No purged obs should be in train
                assert t1.iloc[i] <= test_start_ts, (
                    f"Train obs {i} with t1={t1.iloc[i]} > test_start={test_start_ts}"
                )


# ---------------------------------------------------------------------------
# PurgedKFoldSplitter — embargo correctness (CV-02)
# ---------------------------------------------------------------------------


class TestPurgedKFoldEmbargo:
    """
    CV-02: Embargo gap after test fold.

    Obs in [test_end, test_end + embargo_size) must not appear in train.
    embargo_frac=0.01 by default -> embargo_size = max(1, int(0.01 * n)).
    """

    def test_default_embargo_frac(self):
        """Default embargo_frac=0.01 is stored on the splitter."""
        t1 = _make_series()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        assert splitter.embargo_frac == 0.01

    def test_custom_embargo_frac(self):
        """Custom embargo_frac is stored on the splitter."""
        t1 = _make_series()
        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1, embargo_frac=0.05)
        assert splitter.embargo_frac == 0.05

    def test_embargo_removes_post_test_obs(self):
        """
        When embargo_frac > 0, observations immediately after the test fold
        must be excluded from training.
        """
        n = 100
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        t1 = pd.Series(idx, index=idx)  # point labels (same day)
        X = _make_features(n)

        embargo_frac = 0.05
        embargo_size = max(1, int(embargo_frac * n))  # 5 obs
        splitter = PurgedKFoldSplitter(
            n_splits=5, t1_series=t1, embargo_frac=embargo_frac
        )

        for train_idx, test_idx in splitter.split(X):
            test_end_pos = test_idx.max()
            # embargo zone: positions (test_end_pos + 1) to (test_end_pos + embargo_size)
            embargo_start = test_end_pos + 1
            embargo_end = min(test_end_pos + embargo_size, n - 1)
            embargo_zone = set(range(embargo_start, embargo_end + 1))
            train_set = set(train_idx.tolist())
            in_both = train_set & embargo_zone
            assert in_both == set(), (
                f"Embargo violation: obs {in_both} in both train and embargo zone "
                f"[{embargo_start}, {embargo_end}]"
            )

    def test_zero_embargo_frac(self):
        """With embargo_frac=0.0, no extra observations are excluded beyond purge."""
        n = 60
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        t1 = pd.Series(idx, index=idx)
        X = _make_features(n)
        splitter = PurgedKFoldSplitter(n_splits=3, t1_series=t1, embargo_frac=0.0)

        # Should not raise; splits must still have no overlap
        for train_idx, test_idx in splitter.split(X):
            overlap = set(train_idx.tolist()) & set(test_idx.tolist())
            assert overlap == set()

    def test_monotonic_index_validation(self):
        """Constructor must raise ValueError for non-monotonic t1_series index."""
        # Reverse-sorted index is NOT monotonically increasing
        idx = pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC")[::-1]
        t1 = pd.Series(idx, index=idx)
        with pytest.raises(ValueError, match="monoton"):
            PurgedKFoldSplitter(n_splits=5, t1_series=t1)


# ---------------------------------------------------------------------------
# PurgedKFoldSplitter — sklearn integration
# ---------------------------------------------------------------------------


class TestPurgedKFoldSklearnIntegration:
    """PurgedKFoldSplitter must work as a drop-in sklearn CV splitter."""

    def test_cross_val_score_runs_without_error(self):
        """cross_val_score must complete without raising exceptions."""
        n = 100
        t1 = _make_series(n)
        X = _make_features(n)
        y = _make_labels(n)

        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        clf = DummyClassifier(strategy="most_frequent")
        scores = cross_val_score(clf, X, y, cv=splitter)
        assert len(scores) == 5

    def test_cross_val_score_returns_array(self):
        """cross_val_score must return a numeric array of length n_splits."""
        n = 100
        t1 = _make_series(n)
        X = _make_features(n)
        y = _make_labels(n)

        splitter = PurgedKFoldSplitter(n_splits=5, t1_series=t1)
        clf = DummyClassifier(strategy="most_frequent")
        scores = cross_val_score(clf, X, y, cv=splitter)
        assert isinstance(scores, np.ndarray)
        assert scores.shape == (5,)


# ---------------------------------------------------------------------------
# CPCVSplitter — CV-03 interface
# ---------------------------------------------------------------------------


class TestCPCVSplitterInterface:
    """CV-03: CPCVSplitter interface requirements."""

    def test_raises_value_error_when_t1_none(self):
        """ValueError must be raised when t1_series is None."""
        with pytest.raises(ValueError, match="t1_series is required"):
            CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=None)

    def test_raises_value_error_no_t1_kwarg(self):
        """ValueError must be raised when t1_series is omitted."""
        with pytest.raises(ValueError, match="t1_series is required"):
            CPCVSplitter(n_splits=6, n_test_splits=2)

    def test_get_n_splits_c6_2(self):
        """C(6,2)=15 combinations for n_splits=6, n_test_splits=2."""
        t1 = _make_series(120)
        splitter = CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=t1)
        assert splitter.get_n_splits() == 15

    def test_get_n_splits_c10_2(self):
        """C(10,2)=45 combinations for n_splits=10, n_test_splits=2."""
        t1 = _make_series(200)
        splitter = CPCVSplitter(n_splits=10, n_test_splits=2, t1_series=t1)
        assert splitter.get_n_splits() == 45

    def test_get_n_splits_c5_3(self):
        """C(5,3)=10 combinations for n_splits=5, n_test_splits=3."""
        t1 = _make_series(100)
        splitter = CPCVSplitter(n_splits=5, n_test_splits=3, t1_series=t1)
        assert splitter.get_n_splits() == 10

    def test_yields_correct_number_of_combinations(self):
        """split() must yield exactly C(n_splits, n_test_splits) tuples."""
        t1 = _make_series(120)
        X = _make_features(120)
        splitter = CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=t1)
        combos = list(splitter.split(X))
        assert len(combos) == 15

    def test_split_returns_tuple_of_arrays(self):
        """Each CPCV split must be a 2-tuple of integer arrays."""
        t1 = _make_series(120)
        X = _make_features(120)
        splitter = CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=t1)
        for train_idx, test_idx in splitter.split(X):
            assert isinstance(train_idx, np.ndarray)
            assert isinstance(test_idx, np.ndarray)

    def test_inherits_base_cross_validator(self):
        """CPCVSplitter must inherit from BaseCrossValidator."""
        t1 = _make_series(120)
        splitter = CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=t1)
        assert isinstance(splitter, BaseCrossValidator)


# ---------------------------------------------------------------------------
# CPCVSplitter — no train/test overlap
# ---------------------------------------------------------------------------


class TestCPCVNoOverlap:
    """No train/test index overlap in any combination."""

    def test_no_overlap_c6_2(self):
        """No overlap in any of the 15 combinations for C(6,2)."""
        t1 = _make_series(120)
        X = _make_features(120)
        splitter = CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=t1)
        for train_idx, test_idx in splitter.split(X):
            overlap = set(train_idx.tolist()) & set(test_idx.tolist())
            assert overlap == set(), f"CPCV overlap found: {overlap}"

    def test_no_overlap_c5_2(self):
        """No overlap in any combination for C(5,2)=10."""
        t1 = _make_series(100)
        X = _make_features(100)
        splitter = CPCVSplitter(n_splits=5, n_test_splits=2, t1_series=t1)
        for train_idx, test_idx in splitter.split(X):
            overlap = set(train_idx.tolist()) & set(test_idx.tolist())
            assert overlap == set()


# ---------------------------------------------------------------------------
# CPCVSplitter — combinatorial correctness
# ---------------------------------------------------------------------------


class TestCPCVCombinatorialCorrectness:
    """CPCV path coverage and combinatorial correctness."""

    def test_all_combinations_are_unique(self):
        """No two CPCV combinations should yield the same test set."""
        t1 = _make_series(120)
        X = _make_features(120)
        splitter = CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=t1)
        test_sets = []
        for _, test_idx in splitter.split(X):
            key = frozenset(test_idx.tolist())
            assert key not in test_sets, f"Duplicate test set: {key}"
            test_sets.append(key)

    def test_full_sample_covered_across_all_test_sets(self):
        """
        Union of all test sets across all CPCV combinations covers full sample.

        Each fold group appears in C(n_splits-1, n_test_splits-1) combinations
        as part of the test set.
        """
        n = 120
        t1 = _make_series(n)
        X = _make_features(n)
        splitter = CPCVSplitter(n_splits=6, n_test_splits=2, t1_series=t1)
        all_test = set()
        for _, test_idx in splitter.split(X):
            all_test |= set(test_idx.tolist())
        # All sample indices should appear in at least one test set
        assert all_test == set(range(n))

    def test_purge_applied_in_cpcv(self):
        """Purge must be applied in CPCV: no train obs with t1 > test_start."""
        n = 120
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        t1 = pd.Series(idx.shift(3), index=idx)
        X = _make_features(n)

        splitter = CPCVSplitter(
            n_splits=6, n_test_splits=2, t1_series=t1, embargo_frac=0.0
        )
        for train_idx, test_idx in splitter.split(X):
            test_start_ts = t1.index[test_idx.min()]
            for i in train_idx:
                assert t1.iloc[i] <= test_start_ts, (
                    f"CPCV purge failed: train obs {i} t1={t1.iloc[i]} "
                    f"> test_start={test_start_ts}"
                )

    def test_cpcv_combinations_math_c_n_k(self):
        """get_n_splits() must equal math.comb(n_splits, n_test_splits) for several values."""
        t1_100 = _make_series(100)
        t1_200 = _make_series(200)
        cases = [
            (6, 2, t1_100, math.comb(6, 2)),
            (10, 2, t1_200, math.comb(10, 2)),
            (5, 3, t1_100, math.comb(5, 3)),
            (4, 2, t1_100, math.comb(4, 2)),
        ]
        for n_splits, n_test_splits, t1, expected in cases:
            splitter = CPCVSplitter(
                n_splits=n_splits, n_test_splits=n_test_splits, t1_series=t1
            )
            assert splitter.get_n_splits() == expected, (
                f"C({n_splits},{n_test_splits})={expected} but got {splitter.get_n_splits()}"
            )
