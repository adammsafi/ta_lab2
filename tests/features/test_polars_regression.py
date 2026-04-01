"""
Regression test harness: pandas vs polars paths for feature sub-phases.

Compares output of cycle_stats and rolling_extremes when computed via the
pandas groupby path (use_polars=False) against the polars-sorted path
(use_polars=True) and asserts they are numerically identical.

Tests that require a live DB are skipped when TARGET_DB_URL is not set.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from ta_lab2.features.polars_feature_ops import HAVE_POLARS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compare_feature_outputs(
    df_pandas: pd.DataFrame,
    df_polars: pd.DataFrame,
    float_tol: float = 1e-10,
) -> dict[str, float]:
    """
    Compare two feature DataFrames and return max absolute difference per column.

    Rows are aligned by (id, ts, tf, alignment_source) before comparison.
    Timestamp columns are excluded from numeric comparison.

    Args:
        df_pandas: Output from pandas path (use_polars=False).
        df_polars: Output from polars path (use_polars=True).
        float_tol: Tolerance for asserting equality (default 1e-10).

    Returns:
        Dict mapping column name to max absolute difference.
        An empty dict indicates perfect equality across all numeric columns.

    Raises:
        AssertionError: If any column exceeds float_tol.
    """
    # Align on shared sort key
    sort_keys = [
        k
        for k in ["id", "venue_id", "ts", "tf", "alignment_source", "lookback_bars"]
        if k in df_pandas.columns
    ]
    df_p = df_pandas.sort_values(sort_keys).reset_index(drop=True)
    df_q = df_polars.sort_values(sort_keys).reset_index(drop=True)

    assert df_p.shape == df_q.shape, (
        f"Shape mismatch: pandas={df_p.shape} polars={df_q.shape}"
    )

    diffs: dict[str, float] = {}
    for col in df_p.columns:
        # Skip non-numeric and timestamp columns
        if df_p[col].dtype == object or pd.api.types.is_datetime64_any_dtype(df_p[col]):
            continue
        if col.endswith("_ts") or col == "ts":
            continue

        if df_p[col].dtype == bool or pd.api.types.is_bool_dtype(df_p[col]):
            # Boolean: use XOR to find disagreements, treat count as max_diff
            mismatch_count = int((df_p[col].values ^ df_q[col].values).sum())
            diffs[col] = float(mismatch_count)
            assert mismatch_count == 0, (
                f"Column '{col}': {mismatch_count} boolean mismatches"
            )
            continue

        max_diff = float(np.abs(df_p[col].values - df_q[col].values).max())
        diffs[col] = max_diff
        assert max_diff <= float_tol, (
            f"Column '{col}': max absolute diff {max_diff:.2e} exceeds tolerance {float_tol:.2e}"
        )

    return diffs


# ---------------------------------------------------------------------------
# Infrastructure tests (no DB required)
# ---------------------------------------------------------------------------


class TestPolarsSortedGroupby:
    """Unit tests for polars_sorted_groupby without a database."""

    def test_import(self) -> None:
        from ta_lab2.features.polars_feature_ops import polars_sorted_groupby  # noqa: F401

    def test_have_polars_flag(self) -> None:
        """HAVE_POLARS should be True since polars is installed."""
        assert HAVE_POLARS is True

    def test_groupby_produces_correct_groups(self) -> None:
        """polars_sorted_groupby should call apply_fn once per group."""
        from ta_lab2.features.polars_feature_ops import polars_sorted_groupby

        df = pd.DataFrame(
            {
                "id": [1, 1, 2, 2, 1],
                "venue_id": [1, 1, 1, 1, 1],
                "ts": pd.to_datetime(
                    [
                        "2024-01-01",
                        "2024-01-03",
                        "2024-01-01",
                        "2024-01-02",
                        "2024-01-02",
                    ],
                    utc=True,
                ),
                "close": [10.0, 12.0, 20.0, 22.0, 11.0],
            }
        )

        groups_seen: list[tuple] = []

        def _apply(grp: pd.DataFrame) -> pd.DataFrame:
            id_val = grp["id"].iloc[0]
            venue_val = grp["venue_id"].iloc[0]
            groups_seen.append((id_val, venue_val))
            # Verify sorted by ts within group
            assert grp["ts"].is_monotonic_increasing, "Group not sorted by ts"
            return grp

        result = polars_sorted_groupby(df, ["id", "venue_id"], "ts", _apply)
        assert sorted(groups_seen) == [(1, 1), (2, 1)]
        assert len(result) == len(df)

    def test_groupby_empty_input(self) -> None:
        """polars_sorted_groupby should return empty DataFrame for empty input."""
        from ta_lab2.features.polars_feature_ops import polars_sorted_groupby

        df = pd.DataFrame(columns=["id", "venue_id", "ts", "close"])

        result = polars_sorted_groupby(df, ["id", "venue_id"], "ts", lambda g: g)
        assert result.empty

    def test_normalize_restore_roundtrip(self) -> None:
        """Timestamp normalization round-trip should preserve values."""
        from ta_lab2.features.polars_feature_ops import (
            normalize_timestamps_for_polars,
            restore_timestamps_from_polars,
        )

        ts = pd.to_datetime(["2024-01-01", "2024-06-15"], utc=True)
        df = pd.DataFrame({"ts": ts, "val": [1.0, 2.0]})

        df_no_tz = normalize_timestamps_for_polars(df)
        assert df_no_tz["ts"].dt.tz is None

        df_restored = restore_timestamps_from_polars(df_no_tz)
        assert str(df_restored["ts"].dt.tz) == "UTC"

        # Values must be identical
        pd.testing.assert_series_equal(
            df["ts"].dt.tz_localize(None),
            df_restored["ts"].dt.tz_localize(None),
            check_names=False,
        )


# ---------------------------------------------------------------------------
# DB regression tests (skipped without TARGET_DB_URL)
# ---------------------------------------------------------------------------

_SKIP_NO_DB = pytest.mark.skipif(
    not os.environ.get("TARGET_DB_URL"),
    reason="TARGET_DB_URL not set — skipping DB regression tests",
)


@_SKIP_NO_DB
def test_cycle_stats_regression() -> None:
    """
    Regression: cycle_stats pandas path == polars path for asset id=1, tf=1D.

    Computes ATH cycle metrics twice (use_polars=False then True) and asserts
    max absolute difference < 1e-10 across all numeric output columns.
    """
    import sqlalchemy as sa

    from ta_lab2.scripts.features.cycle_stats_feature import (
        CycleStatsConfig,
        CycleStatsFeature,
    )

    url = os.environ["TARGET_DB_URL"]
    engine = sa.create_engine(url)
    test_ids = [1]

    config_pandas = CycleStatsConfig(tf="1D", use_polars=False)
    feature_pandas = CycleStatsFeature(engine, config_pandas)
    df_source = feature_pandas.load_source_data(test_ids)
    df_out_pandas = feature_pandas.compute_features(df_source)

    config_polars = CycleStatsConfig(tf="1D", use_polars=True)
    feature_polars = CycleStatsFeature(engine, config_polars)
    df_out_polars = feature_polars.compute_features(df_source)

    assert not df_out_pandas.empty, "pandas path returned empty DataFrame"
    assert not df_out_polars.empty, "polars path returned empty DataFrame"

    diffs = compare_feature_outputs(df_out_pandas, df_out_polars)
    print(f"cycle_stats max diffs: {diffs}")


@_SKIP_NO_DB
def test_rolling_extremes_regression() -> None:
    """
    Regression: rolling_extremes pandas path == polars path for asset id=1, tf=1D.

    Computes rolling high/low twice (use_polars=False then True) and asserts
    max absolute difference < 1e-10 across all numeric output columns.
    """
    import sqlalchemy as sa

    from ta_lab2.scripts.features.rolling_extremes_feature import (
        RollingExtremesConfig,
        RollingExtremesFeature,
    )

    url = os.environ["TARGET_DB_URL"]
    engine = sa.create_engine(url)
    test_ids = [1]

    config_pandas = RollingExtremesConfig(tf="1D", use_polars=False)
    feature_pandas = RollingExtremesFeature(engine, config_pandas)
    df_source = feature_pandas.load_source_data(test_ids)
    df_out_pandas = feature_pandas.compute_features(df_source)

    config_polars = RollingExtremesConfig(tf="1D", use_polars=True)
    feature_polars = RollingExtremesFeature(engine, config_polars)
    df_out_polars = feature_polars.compute_features(df_source)

    assert not df_out_pandas.empty, "pandas path returned empty DataFrame"
    assert not df_out_polars.empty, "polars path returned empty DataFrame"

    diffs = compare_feature_outputs(df_out_pandas, df_out_polars)
    print(f"rolling_extremes max diffs: {diffs}")
