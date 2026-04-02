"""
Standalone validation script: compare pandas vs polars paths for all feature sub-phases.

Usage:
    python -m tests.features.run_polars_validation --ids 1,1027,5426
    python -m tests.features.run_polars_validation --ids 1 --tf 1D
    python -m tests.features.run_polars_validation --ids 1 --skip-db-tests

Requires:
    - TARGET_DB_URL environment variable set
    - polars installed (pip install polars)

Produces a summary table:
    | Sub-phase     | Max Diff  | IC Regression | Status |
    |---------------|-----------|---------------|--------|
    | cycle_stats   | 0.00e+00  | 0.00%         | PASS   |
    | rolling_extr. | 0.00e+00  | 0.00%         | PASS   |
    | vol           | 8.88e-16  | 0.00%         | PASS   |
    | ta            | 1.42e-13  | 0.00%         | PASS   |
    | microstructure| 0.00e+00  | 0.00%         | PASS   |
    | ctf (align)   | 0.00e+00  | 0.00%         | PASS   |

Exit codes:
    0 = All sub-phases PASS
    1 = One or more sub-phases FAIL
    2 = No DB available (TARGET_DB_URL not set)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SubPhaseResult:
    name: str
    max_diff: float = 0.0
    ic_regression: float = 0.0  # max IC relative diff across columns
    status: str = "PASS"
    error: str = ""
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# IC helper
# ---------------------------------------------------------------------------


def _compute_rank_ic(
    features: pd.DataFrame, fwd_returns: pd.Series
) -> dict[str, float]:
    """Compute rank IC (Spearman correlation) between each feature and forward returns."""
    ic_scores: dict[str, float] = {}
    valid_mask = fwd_returns.notna()
    for col in features.columns:
        if (
            pd.api.types.is_datetime64_any_dtype(features[col])
            or features[col].dtype == object
        ):
            continue
        col_valid = valid_mask & features[col].notna()
        if col_valid.sum() < 10:
            continue
        rho, _ = stats.spearmanr(features.loc[col_valid, col], fwd_returns[col_valid])
        if not np.isnan(rho):
            ic_scores[col] = float(rho)
    return ic_scores


def _ic_regression(
    df_pandas: pd.DataFrame,
    df_polars: pd.DataFrame,
    numeric_cols: list[str],
) -> float:
    """Return max IC relative difference across all numeric columns."""
    if "close" not in df_pandas.columns:
        return 0.0

    fwd_ret = df_pandas.groupby("id")["close"].transform(
        lambda s: s.pct_change().shift(-1)
    )

    ic_pandas = _compute_rank_ic(df_pandas[numeric_cols], fwd_ret)
    ic_polars = _compute_rank_ic(df_polars[numeric_cols], fwd_ret)

    max_rel_diff = 0.0
    for col in ic_pandas:
        if col not in ic_polars:
            continue
        ic_p = abs(ic_pandas[col])
        ic_q = abs(ic_polars[col])
        if ic_p < 1e-6:
            continue
        rel_diff = abs(ic_p - ic_q) / ic_p
        max_rel_diff = max(max_rel_diff, rel_diff)

    return max_rel_diff


def _numeric_max_diff(df_pandas: pd.DataFrame, df_polars: pd.DataFrame) -> float:
    """Return the max absolute difference across all numeric columns."""
    sort_keys = [k for k in ["id", "venue_id", "ts", "tf"] if k in df_pandas.columns]
    df_p = df_pandas.sort_values(sort_keys).reset_index(drop=True)
    df_q = df_polars.sort_values(sort_keys).reset_index(drop=True)

    if df_p.shape != df_q.shape:
        return float("nan")

    max_diff = 0.0
    for col in df_p.columns:
        if pd.api.types.is_datetime64_any_dtype(df_p[col]) or df_p[col].dtype == object:
            continue
        if col in {"ts"} or col.endswith("_ts"):
            continue
        if df_p[col].dtype == bool or pd.api.types.is_bool_dtype(df_p[col]):
            mismatch = int((df_p[col].values ^ df_q[col].values).sum())
            max_diff = max(max_diff, float(mismatch))
            continue
        d = float(np.abs(df_p[col].values - df_q[col].values).max())
        max_diff = max(max_diff, d)

    return max_diff


# ---------------------------------------------------------------------------
# Per-sub-phase runners
# ---------------------------------------------------------------------------


def _run_cycle_stats(engine: Any, ids: list[int], tf: str) -> SubPhaseResult:
    from ta_lab2.scripts.features.cycle_stats_feature import (
        CycleStatsConfig,
        CycleStatsFeature,
    )

    t0 = time.perf_counter()
    try:
        feat_p = CycleStatsFeature(engine, CycleStatsConfig(tf=tf, use_polars=False))
        df_src = feat_p.load_source_data(ids)
        df_pandas = feat_p.compute_features(df_src)

        feat_q = CycleStatsFeature(engine, CycleStatsConfig(tf=tf, use_polars=True))
        df_polars = feat_q.compute_features(df_src)

        max_diff = _numeric_max_diff(df_pandas, df_polars)
        numeric_cols = [
            c
            for c in df_pandas.columns
            if c not in {"id", "venue_id", "ts", "tf", "alignment_source"}
            and not pd.api.types.is_datetime64_any_dtype(df_pandas[c])
            and df_pandas[c].dtype != object
        ]
        ic_reg = _ic_regression(df_pandas, df_polars, numeric_cols)
        return SubPhaseResult(
            "cycle_stats",
            max_diff,
            ic_reg,
            "PASS" if max_diff <= 1e-10 else "FAIL",
            duration_seconds=time.perf_counter() - t0,
        )
    except Exception as e:
        return SubPhaseResult(
            "cycle_stats",
            error=traceback.format_exc(limit=3),
            status="ERROR",
            duration_seconds=time.perf_counter() - t0,
        )


def _run_rolling_extremes(engine: Any, ids: list[int], tf: str) -> SubPhaseResult:
    from ta_lab2.scripts.features.rolling_extremes_feature import (
        RollingExtremesConfig,
        RollingExtremesFeature,
    )

    t0 = time.perf_counter()
    try:
        feat_p = RollingExtremesFeature(
            engine, RollingExtremesConfig(tf=tf, use_polars=False)
        )
        df_src = feat_p.load_source_data(ids)
        df_pandas = feat_p.compute_features(df_src)

        feat_q = RollingExtremesFeature(
            engine, RollingExtremesConfig(tf=tf, use_polars=True)
        )
        df_polars = feat_q.compute_features(df_src)

        max_diff = _numeric_max_diff(df_pandas, df_polars)
        numeric_cols = [
            c
            for c in df_pandas.columns
            if c not in {"id", "venue_id", "ts", "tf", "alignment_source"}
            and not pd.api.types.is_datetime64_any_dtype(df_pandas[c])
            and df_pandas[c].dtype != object
        ]
        ic_reg = _ic_regression(df_pandas, df_polars, numeric_cols)
        return SubPhaseResult(
            "rolling_extremes",
            max_diff,
            ic_reg,
            "PASS" if max_diff <= 1e-10 else "FAIL",
            duration_seconds=time.perf_counter() - t0,
        )
    except Exception as e:
        return SubPhaseResult(
            "rolling_extremes",
            error=traceback.format_exc(limit=3),
            status="ERROR",
            duration_seconds=time.perf_counter() - t0,
        )


def _run_vol(engine: Any, ids: list[int], tf: str) -> SubPhaseResult:
    from ta_lab2.scripts.features.vol_feature import VolatilityConfig, VolatilityFeature

    t0 = time.perf_counter()
    try:
        feat_p = VolatilityFeature(engine, VolatilityConfig(tf=tf, use_polars=False))
        df_src = feat_p.load_source_data(ids)
        df_pandas = feat_p.compute_features(df_src)

        feat_q = VolatilityFeature(engine, VolatilityConfig(tf=tf, use_polars=True))
        df_polars = feat_q.compute_features(df_src)

        max_diff = _numeric_max_diff(df_pandas, df_polars)
        numeric_cols = [
            c
            for c in df_pandas.columns
            if c not in {"id", "venue_id", "ts", "tf", "alignment_source"}
            and not pd.api.types.is_datetime64_any_dtype(df_pandas[c])
            and df_pandas[c].dtype != object
        ]
        ic_reg = _ic_regression(df_pandas, df_polars, numeric_cols)
        # Vol has floating-point EWM precision ~8.88e-16: use 1e-10 tolerance
        return SubPhaseResult(
            "vol",
            max_diff,
            ic_reg,
            "PASS" if max_diff <= 1e-10 else "FAIL",
            duration_seconds=time.perf_counter() - t0,
        )
    except Exception as e:
        return SubPhaseResult(
            "vol",
            error=traceback.format_exc(limit=3),
            status="ERROR",
            duration_seconds=time.perf_counter() - t0,
        )


def _run_ta(engine: Any, ids: list[int], tf: str) -> SubPhaseResult:
    from ta_lab2.scripts.features.ta_feature import TAConfig, TAFeature

    t0 = time.perf_counter()
    try:
        feat_p = TAFeature(engine, TAConfig(tf=tf, use_polars=False))
        df_src = feat_p.load_source_data(ids)
        df_pandas = feat_p.compute_features(df_src)

        feat_q = TAFeature(engine, TAConfig(tf=tf, use_polars=True))
        df_polars = feat_q.compute_features(df_src)

        max_diff = _numeric_max_diff(df_pandas, df_polars)
        numeric_cols = [
            c
            for c in df_pandas.columns
            if c not in {"id", "venue_id", "ts", "tf", "alignment_source"}
            and not pd.api.types.is_datetime64_any_dtype(df_pandas[c])
            and df_pandas[c].dtype != object
        ]
        ic_reg = _ic_regression(df_pandas, df_polars, numeric_cols)
        # TA has floating-point precision ~1.42e-13: use 1e-10 tolerance
        return SubPhaseResult(
            "ta",
            max_diff,
            ic_reg,
            "PASS" if max_diff <= 1e-10 else "FAIL",
            duration_seconds=time.perf_counter() - t0,
        )
    except Exception as e:
        return SubPhaseResult(
            "ta",
            error=traceback.format_exc(limit=3),
            status="ERROR",
            duration_seconds=time.perf_counter() - t0,
        )


def _run_microstructure(engine: Any, ids: list[int], tf: str) -> SubPhaseResult:
    from ta_lab2.scripts.features.microstructure_feature import (
        MicrostructureConfig,
        MicrostructureFeature,
    )

    t0 = time.perf_counter()
    try:
        feat_p = MicrostructureFeature(
            engine, MicrostructureConfig(tf=tf, use_polars=False)
        )
        df_src = feat_p.load_source_data(ids)
        df_pandas = feat_p.compute_features(df_src)

        feat_q = MicrostructureFeature(
            engine, MicrostructureConfig(tf=tf, use_polars=True)
        )
        df_polars = feat_q.compute_features(df_src)

        max_diff = _numeric_max_diff(df_pandas, df_polars)
        numeric_cols = [
            c
            for c in df_pandas.columns
            if c not in {"id", "venue_id", "ts", "tf", "alignment_source"}
            and not pd.api.types.is_datetime64_any_dtype(df_pandas[c])
            and df_pandas[c].dtype != object
        ]
        ic_reg = _ic_regression(df_pandas, df_polars, numeric_cols)
        return SubPhaseResult(
            "microstructure",
            max_diff,
            ic_reg,
            "PASS" if max_diff <= 1e-10 else "FAIL",
            duration_seconds=time.perf_counter() - t0,
        )
    except Exception as e:
        return SubPhaseResult(
            "microstructure",
            error=traceback.format_exc(limit=3),
            status="ERROR",
            duration_seconds=time.perf_counter() - t0,
        )


def _run_ctf_alignment(engine: Any, ids: list[int], tf: str) -> SubPhaseResult:
    """Run CTF alignment regression using synthetic indicator data."""
    from ta_lab2.features.cross_timeframe import _align_timeframes_polars
    from ta_lab2.regimes.comovement import build_alignment_frame

    t0 = time.perf_counter()
    try:
        # Use actual data from the DB if available
        from sqlalchemy import text

        n_ids = len(ids)
        with engine.connect() as conn:
            # Try to load actual TA data (rsi_14) for CTF alignment test
            rows = conn.execute(
                text(
                    """
                    SELECT id, ts, rsi_14
                    FROM public.ta
                    WHERE id = ANY(:ids) AND tf = :tf AND alignment_source = 'multi_tf'
                      AND venue_id = 1 AND rsi_14 IS NOT NULL
                    ORDER BY id, ts
                    LIMIT 2000
                    """
                ),
                {"ids": ids, "tf": tf},
            ).fetchall()

        if not rows:
            return SubPhaseResult(
                "ctf_alignment",
                status="SKIP",
                error="No TA data for ctf alignment test",
                duration_seconds=time.perf_counter() - t0,
            )

        df_all = pd.DataFrame(rows, columns=["id", "ts", "rsi_14"])
        df_all["ts"] = pd.to_datetime(df_all["ts"], utc=True)

        # Use first half as base, second half as ref (simulates different TFs)
        n = len(df_all)
        base_df = df_all.iloc[: n // 2].copy()
        ref_df = df_all.iloc[n // 4 :].copy()  # offset ref to test backward join

        # Polars path
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result_polars = _align_timeframes_polars(base_df, ref_df, "rsi_14")

        # Pandas path
        aligned_frames = []
        for asset_id in sorted(base_df["id"].unique()):
            b = base_df[base_df["id"] == asset_id].copy()
            r = ref_df[ref_df["id"] == asset_id].copy()
            if r.empty:
                continue
            aligned = build_alignment_frame(
                low_df=b[["ts", "rsi_14"]],
                high_df=r[["ts", "rsi_14"]],
                on="ts",
                low_cols=["rsi_14"],
                high_cols=["rsi_14"],
                suffix_low="",
                suffix_high="_ref",
                direction="backward",
            )
            aligned = aligned.rename(
                columns={"rsi_14": "base_value", "rsi_14_ref": "ref_value"}
            )
            aligned["id"] = asset_id
            aligned_frames.append(aligned[["id", "ts", "base_value", "ref_value"]])

        if not aligned_frames:
            return SubPhaseResult(
                "ctf_alignment",
                status="SKIP",
                error="Pandas path produced no aligned frames",
                duration_seconds=time.perf_counter() - t0,
            )

        result_pandas = pd.concat(aligned_frames, ignore_index=True)

        r_pol = result_polars.sort_values(["id", "ts"]).reset_index(drop=True)
        r_pan = result_pandas.sort_values(["id", "ts"]).reset_index(drop=True)

        if r_pol.shape != r_pan.shape:
            return SubPhaseResult(
                "ctf_alignment",
                error=f"Shape mismatch: polars={r_pol.shape} pandas={r_pan.shape}",
                status="FAIL",
                duration_seconds=time.perf_counter() - t0,
            )

        max_diff = float(
            max(
                (r_pol["base_value"] - r_pan["base_value"]).abs().max(),
                (r_pol["ref_value"] - r_pan["ref_value"]).abs().fillna(0).max(),
            )
        )

        return SubPhaseResult(
            "ctf_alignment",
            max_diff=max_diff,
            ic_regression=0.0,
            status="PASS" if max_diff <= 1e-10 else "FAIL",
            duration_seconds=time.perf_counter() - t0,
        )

    except Exception:
        return SubPhaseResult(
            "ctf_alignment",
            error=traceback.format_exc(limit=3),
            status="ERROR",
            duration_seconds=time.perf_counter() - t0,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _print_summary(results: list[SubPhaseResult]) -> None:
    """Print a formatted summary table."""
    print()
    print("=" * 70)
    print("POLARS VALIDATION SUMMARY")
    print("=" * 70)
    print(
        f"{'Sub-phase':<18} {'Max Diff':<12} {'IC Regression':<16} {'Duration':<10} {'Status'}"
    )
    print("-" * 70)
    for r in results:
        max_diff_str = f"{r.max_diff:.2e}" if r.max_diff > 0 else "0.00e+00"
        ic_str = f"{r.ic_regression:.2%}" if r.ic_regression > 0 else "0.00%"
        dur_str = f"{r.duration_seconds:.1f}s"
        status_str = r.status
        print(
            f"{r.name:<18} {max_diff_str:<12} {ic_str:<16} {dur_str:<10} {status_str}"
        )
        if r.error and r.status in {"FAIL", "ERROR"}:
            for line in r.error.splitlines()[:3]:
                print(f"  {line}")
    print("=" * 70)

    n_pass = sum(1 for r in results if r.status == "PASS")
    n_skip = sum(1 for r in results if r.status == "SKIP")
    n_fail = sum(1 for r in results if r.status in {"FAIL", "ERROR"})
    print(f"PASS: {n_pass}  SKIP: {n_skip}  FAIL: {n_fail}")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Standalone polars validation: compare pandas vs polars for all sub-phases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ids",
        default="1",
        help="Comma-separated asset IDs (default: 1)",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe to validate (default: 1D)",
    )
    parser.add_argument(
        "--skip-microstructure",
        action="store_true",
        default=False,
        help="Skip microstructure sub-phase (slow, requires full FFD computation)",
    )
    parser.add_argument(
        "--skip-ctf",
        action="store_true",
        default=False,
        help="Skip CTF alignment sub-phase",
    )
    args = parser.parse_args()

    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        print("ERROR: TARGET_DB_URL not set. Export it before running.")
        return 2

    import sqlalchemy as sa

    ids = [int(i.strip()) for i in args.ids.split(",")]
    engine = sa.create_engine(db_url)

    print(f"Running polars validation for ids={ids}, tf={args.tf}")
    print()

    results: list[SubPhaseResult] = []

    results.append(_run_cycle_stats(engine, ids, args.tf))
    print(
        f"  cycle_stats       ... {results[-1].status} (max_diff={results[-1].max_diff:.2e})"
    )

    results.append(_run_rolling_extremes(engine, ids, args.tf))
    print(
        f"  rolling_extremes  ... {results[-1].status} (max_diff={results[-1].max_diff:.2e})"
    )

    results.append(_run_vol(engine, ids, args.tf))
    print(
        f"  vol               ... {results[-1].status} (max_diff={results[-1].max_diff:.2e})"
    )

    results.append(_run_ta(engine, ids, args.tf))
    print(
        f"  ta                ... {results[-1].status} (max_diff={results[-1].max_diff:.2e})"
    )

    if not args.skip_microstructure:
        results.append(_run_microstructure(engine, ids, args.tf))
        print(
            f"  microstructure    ... {results[-1].status} (max_diff={results[-1].max_diff:.2e})"
        )
    else:
        print("  microstructure    ... SKIP (--skip-microstructure)")

    if not args.skip_ctf:
        results.append(_run_ctf_alignment(engine, ids, args.tf))
        print(
            f"  ctf_alignment     ... {results[-1].status} (max_diff={results[-1].max_diff:.2e})"
        )
    else:
        print("  ctf_alignment     ... SKIP (--skip-ctf)")

    _print_summary(results)

    n_fail = sum(1 for r in results if r.status in {"FAIL", "ERROR"})
    return 1 if n_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
