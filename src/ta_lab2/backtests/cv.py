"""
Leakage-free cross-validation splitters for financial time series.

Implements sklearn-compatible CV splitters that respect the temporal structure
of financial data with overlapping labels (e.g., multi-bar holding periods).

Classes
-------
PurgedKFoldSplitter
    Standard purged k-fold: purges training observations whose label-end
    timestamp bleeds into the test fold, then applies an embargo gap after
    each test fold.

CPCVSplitter
    Combinatorial Purged Cross-Validation (Lopez de Prado).
    Generates all C(n_splits, n_test_splits) combinations of fold groups as
    test sets, enabling unbiased backtest statistics for PBO analysis.

References
----------
Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Chapter 7 (PurgedKFold) and Chapter 12 (CPCV).

Notes
-----
Implemented from scratch to avoid mlfinlab (discontinued; known bug #295).
Both splitters require t1_series (label-end timestamps) as a mandatory
constructor argument — no silent default that could mask leakage.

This module is library-only. No pipeline integration or CLI wiring is
included; callers handle the train/predict/score loop.
"""

from __future__ import annotations

import itertools
from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator


class PurgedKFoldSplitter(BaseCrossValidator):
    """
    Purged K-Fold cross-validator for financial time series.

    Divides the sample into ``n_splits`` sequential fold groups. For each fold
    used as a test set the algorithm:

    1. **Purges** training observations whose label spans overlap the test
       window (i.e., ``t1.iloc[i] > test_fold_start_timestamp``).
    2. **Embargos** training observations in the window
       ``[test_end, test_end + embargo_size)`` to prevent lookahead from
       serial autocorrelation.

    Parameters
    ----------
    n_splits : int, default 5
        Number of folds.
    t1_series : pd.Series
        Label-end timestamps.  The index must be the label-start timestamps
        (monotonically increasing), and the values must be the label-end
        timestamps.  **Required** — raises ``ValueError`` when ``None``.
    embargo_frac : float, default 0.01
        Fraction of the sample to embargo after each test fold.
        ``embargo_size = max(1, int(embargo_frac * n))``.
        Pass ``0.0`` to disable the embargo.

    Raises
    ------
    ValueError
        If ``t1_series`` is ``None``.
    ValueError
        If the index of ``t1_series`` is not monotonically increasing.
    """

    def __init__(
        self,
        n_splits: int = 5,
        t1_series: pd.Series | None = None,
        embargo_frac: float = 0.01,
    ) -> None:
        if t1_series is None:
            raise ValueError(
                "t1_series is required for PurgedKFoldSplitter. "
                "Pass a pd.Series whose index is label-start timestamps and "
                "values are label-end timestamps."
            )
        if not t1_series.index.is_monotonic_increasing:
            raise ValueError(
                "t1_series index must be monotonically increasing. "
                "Ensure the series is sorted by label-start timestamp."
            )
        super().__init__()
        self.n_splits = n_splits
        self.t1 = t1_series
        self.embargo_frac = embargo_frac

    # ------------------------------------------------------------------
    # sklearn BaseCrossValidator interface
    # ------------------------------------------------------------------

    def get_n_splits(
        self,
        X: np.ndarray | None = None,
        y: np.ndarray | None = None,
        groups: np.ndarray | None = None,
    ) -> int:
        """Return the number of splitting iterations."""
        return self.n_splits

    def _iter_test_masks(
        self,
        X: np.ndarray | None = None,
        y: np.ndarray | None = None,
        groups: np.ndarray | None = None,
    ) -> Iterator[np.ndarray]:
        """Yield boolean test masks — required by BaseCrossValidator."""
        n = len(self.t1)
        fold_sizes = _fold_sizes(n, self.n_splits)
        current = 0
        for fold_size in fold_sizes:
            mask = np.zeros(n, dtype=bool)
            mask[current : current + fold_size] = True
            yield mask
            current += fold_size

    def split(
        self,
        X: np.ndarray,
        y: np.ndarray | None = None,
        groups: np.ndarray | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """
        Yield (train_idx, test_idx) for each fold.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            Feature matrix.  Only ``len(X)`` is used.
        y : ignored
        groups : ignored

        Yields
        ------
        train_idx : np.ndarray of int
            Training indices after purge and embargo.
        test_idx : np.ndarray of int
            Test indices.
        """
        n = len(X)
        embargo_size = (
            max(1, int(self.embargo_frac * n)) if self.embargo_frac > 0 else 0
        )

        fold_bounds = fold_boundaries(n, self.n_splits)

        for fold_start, fold_end in fold_bounds:
            test_idx = np.arange(fold_start, fold_end)

            # Timestamps bounding the test window
            test_start_ts = self.t1.index[fold_start]
            test_end_pos = fold_end - 1  # last position index in test fold

            # Build the complement (everything except test)
            complement = np.concatenate(
                [np.arange(0, fold_start), np.arange(fold_end, n)]
            )

            # ----------------------------------------------------------
            # Purge: remove training obs whose label-end > test_start
            # Use pd.array comparison to handle tz-aware timestamps correctly.
            # NOTE: .values on tz-aware Series returns tz-naive numpy.datetime64
            # on this platform, causing TypeError. Use boolean mask via pandas.
            # ----------------------------------------------------------
            t1_complement = self.t1.iloc[complement]
            purge_mask = (t1_complement <= test_start_ts).to_numpy()

            # ----------------------------------------------------------
            # Embargo: remove training obs in [test_end+1, test_end+embargo_size)
            # ----------------------------------------------------------
            if embargo_size > 0:
                embargo_start = test_end_pos + 1
                embargo_end = min(test_end_pos + embargo_size, n - 1)
                embargo_mask = ~(
                    (complement >= embargo_start) & (complement <= embargo_end)
                )
            else:
                embargo_mask = np.ones(len(complement), dtype=bool)

            combined_mask = purge_mask & embargo_mask
            train_idx = complement[combined_mask].astype(np.intp)

            yield train_idx, test_idx.astype(np.intp)


class CPCVSplitter(BaseCrossValidator):
    """
    Combinatorial Purged Cross-Validation (CPCV) splitter.

    Generates all ``C(n_splits, n_test_splits)`` combinations of fold groups as
    test sets.  For each combination the training set is the complement minus
    purged and embargoed observations.

    Used for constructing the full path matrix required for Probability of
    Back-test Overfitting (PBO) analysis (Phase 38+).

    Parameters
    ----------
    n_splits : int, default 6
        Number of fold groups to partition the sample into.
    n_test_splits : int, default 2
        Number of fold groups to combine as the test set per combination.
        Results in ``C(n_splits, n_test_splits)`` total combinations.
    t1_series : pd.Series
        Label-end timestamps.  **Required** — raises ``ValueError`` when
        ``None``.
    embargo_frac : float, default 0.01
        Fraction of the sample to embargo after the last test group in each
        combination.

    Raises
    ------
    ValueError
        If ``t1_series`` is ``None``.
    ValueError
        If the index of ``t1_series`` is not monotonically increasing.
    """

    def __init__(
        self,
        n_splits: int = 6,
        n_test_splits: int = 2,
        t1_series: pd.Series | None = None,
        embargo_frac: float = 0.01,
    ) -> None:
        if t1_series is None:
            raise ValueError(
                "t1_series is required for CPCVSplitter. "
                "Pass a pd.Series whose index is label-start timestamps and "
                "values are label-end timestamps."
            )
        if not t1_series.index.is_monotonic_increasing:
            raise ValueError(
                "t1_series index must be monotonically increasing. "
                "Ensure the series is sorted by label-start timestamp."
            )
        super().__init__()
        self.n_splits = n_splits
        self.n_test_splits = n_test_splits
        self.t1 = t1_series
        self.embargo_frac = embargo_frac
        # Pre-compute all combinations for get_n_splits()
        self._combos: list[tuple[int, ...]] = list(
            itertools.combinations(range(n_splits), n_test_splits)
        )

    # ------------------------------------------------------------------
    # sklearn BaseCrossValidator interface
    # ------------------------------------------------------------------

    def get_n_splits(
        self,
        X: np.ndarray | None = None,
        y: np.ndarray | None = None,
        groups: np.ndarray | None = None,
    ) -> int:
        """Return C(n_splits, n_test_splits) — the number of combinations."""
        return len(self._combos)

    def _iter_test_masks(
        self,
        X: np.ndarray | None = None,
        y: np.ndarray | None = None,
        groups: np.ndarray | None = None,
    ) -> Iterator[np.ndarray]:
        """Yield boolean test masks — required by BaseCrossValidator."""
        n = len(self.t1)
        fold_bounds = fold_boundaries(n, self.n_splits)
        for combo in self._combos:
            mask = np.zeros(n, dtype=bool)
            for fold_idx in combo:
                start, end = fold_bounds[fold_idx]
                mask[start:end] = True
            yield mask

    def split(
        self,
        X: np.ndarray,
        y: np.ndarray | None = None,
        groups: np.ndarray | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """
        Yield (train_idx, test_idx) for each combinatorial fold.

        For each combination of ``n_test_splits`` fold groups:

        - ``test_idx`` is the union of indices in the selected fold groups.
        - ``train_idx`` is the complement, with purge applied using the
          earliest test-group start timestamp, and embargo applied after
          the latest test-group end position.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
        y : ignored
        groups : ignored

        Yields
        ------
        train_idx : np.ndarray of int
        test_idx : np.ndarray of int
        """
        n = len(X)
        embargo_size = (
            max(1, int(self.embargo_frac * n)) if self.embargo_frac > 0 else 0
        )
        fold_bounds = fold_boundaries(n, self.n_splits)

        for combo in self._combos:
            # Build test index as union of selected fold groups
            test_parts = [
                np.arange(fold_bounds[k][0], fold_bounds[k][1]) for k in combo
            ]
            test_idx = np.concatenate(test_parts)

            # Earliest test start (for purge)
            test_start_pos = min(fold_bounds[k][0] for k in combo)
            test_start_ts = self.t1.index[test_start_pos]

            # Latest test end position (for embargo)
            test_end_pos = max(fold_bounds[k][1] - 1 for k in combo)

            # Complement indices
            test_set = set(test_idx.tolist())
            complement = np.array([i for i in range(n) if i not in test_set], dtype=int)

            # Purge — use pandas comparison to handle tz-aware timestamps correctly
            t1_complement = self.t1.iloc[complement]
            purge_mask = (t1_complement <= test_start_ts).to_numpy()

            # Embargo
            if embargo_size > 0:
                embargo_start = test_end_pos + 1
                embargo_end = min(test_end_pos + embargo_size, n - 1)
                embargo_mask = ~(
                    (complement >= embargo_start) & (complement <= embargo_end)
                )
            else:
                embargo_mask = np.ones(len(complement), dtype=bool)

            combined_mask = purge_mask & embargo_mask
            train_idx = complement[combined_mask].astype(np.intp)

            yield train_idx, test_idx.astype(np.intp)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _fold_sizes(n: int, n_splits: int) -> list[int]:
    """
    Compute fold sizes so that larger folds come first (sklearn convention).

    The first ``n % n_splits`` folds get one extra sample.
    """
    base, remainder = divmod(n, n_splits)
    return [base + (1 if i < remainder else 0) for i in range(n_splits)]


def fold_boundaries(n: int, n_splits: int) -> list[tuple[int, int]]:
    """
    Return list of (start, end) index pairs for each fold (end is exclusive).
    """
    sizes = _fold_sizes(n, n_splits)
    bounds: list[tuple[int, int]] = []
    current = 0
    for size in sizes:
        bounds.append((current, current + size))
        current += size
    return bounds
