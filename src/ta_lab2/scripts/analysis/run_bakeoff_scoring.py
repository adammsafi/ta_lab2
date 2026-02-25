"""
CLI to run composite scoring on bake-off results.

Loads OOS metrics from strategy_bakeoff_results, applies V1 hard gates,
computes composite scores under 4 weighting schemes, and runs sensitivity
analysis to identify robust top-2 strategies.

Results saved to reports/bakeoff/composite_scores.csv and
reports/bakeoff/sensitivity_analysis.csv.

Usage
-----
    # Score BTC 1D (auto-selects baseline cost scenario):
    python -m ta_lab2.scripts.analysis.run_bakeoff_scoring --asset-id 1 --tf 1D

    # Specific cost scenario:
    python -m ta_lab2.scripts.analysis.run_bakeoff_scoring --asset-id 1 --tf 1D \\
        --cost-scenario spot_fee16_slip10

    # All cost scenarios in one run:
    python -m ta_lab2.scripts.analysis.run_bakeoff_scoring --asset-id 1 --tf 1D \\
        --all-scenarios

    # CPCV results:
    python -m ta_lab2.scripts.analysis.run_bakeoff_scoring --asset-id 1 --tf 1D \\
        --cv-method cpcv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from ta_lab2.backtests.composite_scorer import (
    WEIGHT_SCHEMES,
    V1_GATES,
    load_bakeoff_metrics,
    rank_strategies,
    sensitivity_analysis,
)
from ta_lab2.io import get_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Report output directory
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_REPORT_DIR = _PROJECT_ROOT / "reports" / "bakeoff"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_pct(v: float, decimals: int = 1) -> str:
    """Format float as percentage string."""
    if pd.isna(v):
        return "N/A"
    return f"{v * 100:.{decimals}f}%"


def _fmt_float(v: float, decimals: int = 3) -> str:
    if pd.isna(v):
        return "N/A"
    return f"{v:.{decimals}f}"


def _print_section(title: str) -> None:
    width = 80
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _print_composite_scores(scored_df: pd.DataFrame, scheme_name: str) -> None:
    """Print a formatted table of composite scores for one weighting scheme."""
    cols = [
        "strategy_name",
        "composite_score",
        "rank",
        "passes_v1_gates",
        "sharpe_mean",
        "max_drawdown_worst",
        "psr",
        "turnover",
    ]
    available = [c for c in cols if c in scored_df.columns]
    display = scored_df[available].copy()

    # Format for display
    if "sharpe_mean" in display.columns:
        display["sharpe_mean"] = display["sharpe_mean"].apply(
            lambda v: _fmt_float(v, 3)
        )
    if "max_drawdown_worst" in display.columns:
        display["max_drawdown_worst"] = display["max_drawdown_worst"].apply(
            lambda v: _fmt_pct(v, 1)
        )
    if "psr" in display.columns:
        display["psr"] = display["psr"].apply(lambda v: _fmt_float(v, 3))
    if "composite_score" in display.columns:
        display["composite_score"] = display["composite_score"].apply(
            lambda v: _fmt_float(v, 4)
        )
    if "turnover" in display.columns:
        display["turnover"] = display["turnover"].apply(lambda v: _fmt_float(v, 5))

    print(f"\n  Scheme: {scheme_name}")
    print(f"  Weights: {WEIGHT_SCHEMES[scheme_name]}")
    print()
    print(display.to_string(index=False))


def _print_sensitivity_table(sa_df: pd.DataFrame) -> None:
    """Print sensitivity analysis table."""
    rank_cols = [f"rank_{s}" for s in WEIGHT_SCHEMES if f"rank_{s}" in sa_df.columns]
    label_col = (
        "strategy_label" if "strategy_label" in sa_df.columns else "strategy_name"
    )
    display_cols = (
        [label_col] + rank_cols + ["n_times_top2", "robust", "passes_v1_gates"]
    )
    available = [c for c in display_cols if c in sa_df.columns]
    print(sa_df[available].to_string(index=False))


def _print_v1_gate_summary(metrics_df: pd.DataFrame) -> None:
    """Print V1 gate summary (which strategies pass/fail and why)."""
    from ta_lab2.backtests.composite_scorer import apply_v1_gates

    gated = apply_v1_gates(metrics_df)
    label_col = (
        "strategy_label" if "strategy_label" in gated.columns else "strategy_name"
    )

    print(
        f"  V1 Gates: Sharpe >= {V1_GATES['min_sharpe']:.1f}, "
        f"Max DD <= {V1_GATES['max_drawdown_pct']:.0f}%"
    )
    print()

    for _, row in gated.iterrows():
        label = row[label_col]
        passes = row["passes_v1_gates"]
        failures = row.get("gate_failures", [])
        status = "PASS" if passes else "FAIL"
        sharpe = row.get("sharpe_mean", float("nan"))
        dd = row.get("max_drawdown_worst", float("nan"))
        print(f"  [{status}] {label}")
        print(
            f"        Sharpe={_fmt_float(sharpe, 3)}, MaxDD={_fmt_pct(dd, 1)}", end=""
        )
        if failures:
            print(f"  -> {'; '.join(failures)}", end="")
        print()


# ---------------------------------------------------------------------------
# Main scoring pipeline
# ---------------------------------------------------------------------------


def run_scoring(
    asset_id: int,
    tf: str,
    cv_method: str = "purged_kfold",
    cost_scenario: str | None = None,
    all_scenarios: bool = False,
    output_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run composite scoring pipeline and return (composite_scores_df, sensitivity_df).

    Parameters
    ----------
    asset_id : int
        Asset to score (e.g., 1 for BTC).
    tf : str
        Timeframe (e.g., "1D").
    cv_method : str
        CV method for evaluation ("purged_kfold" or "cpcv").
    cost_scenario : str or None
        Specific cost scenario, or None for auto-selection.
    all_scenarios : bool
        If True, load and score all available cost scenarios.
    output_dir : Path or None
        Directory to save CSVs. Defaults to reports/bakeoff/.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (composite_scores_df, sensitivity_df)
    """
    out_dir = output_dir or _REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = get_engine()

    # Load metrics
    scenario_arg = "__all__" if all_scenarios else cost_scenario
    metrics_df = load_bakeoff_metrics(
        engine,
        asset_id=asset_id,
        tf=tf,
        cv_method=cv_method,
        cost_scenario=scenario_arg,
    )

    if metrics_df.empty:
        print(
            f"No bakeoff results found for asset_id={asset_id}, tf={tf}, "
            f"cv_method={cv_method}."
        )
        return pd.DataFrame(), pd.DataFrame()

    resolved_scenario = (
        metrics_df["cost_scenario"].iloc[0] if not metrics_df.empty else "N/A"
    )

    # --- Header ---
    _print_section(
        f"Strategy Bake-Off Composite Scoring | asset_id={asset_id} tf={tf} "
        f"cv_method={cv_method}"
    )
    print(f"  Cost scenario(s): {'ALL' if all_scenarios else resolved_scenario}")
    print(
        f"  Strategies loaded: {len(metrics_df)} rows "
        f"({metrics_df['strategy_name'].nunique()} distinct strategy names)"
    )
    print(f"  Output directory: {out_dir}")

    # --- V1 Gate Summary ---
    _print_section("V1 Hard Gate Status")
    _print_v1_gate_summary(metrics_df)

    # --- Composite Scores per Scheme ---
    _print_section("Composite Scores by Weighting Scheme")
    all_scored: list[pd.DataFrame] = []

    for scheme_name, weights in WEIGHT_SCHEMES.items():
        ranked = rank_strategies(metrics_df, weights)
        ranked["scheme"] = scheme_name
        all_scored.append(ranked)
        _print_composite_scores(ranked, scheme_name)

    composite_df = pd.concat(all_scored, ignore_index=True)

    # --- Sensitivity Analysis ---
    _print_section("Sensitivity Analysis (Ranking Robustness)")
    sa_df = sensitivity_analysis(metrics_df)
    print()
    _print_sensitivity_table(sa_df)

    # --- Robust top-2 summary ---
    robust_top2 = sa_df[sa_df["robust"] == True]  # noqa: E712
    gates_ok = sa_df[sa_df["passes_v1_gates"] == True]  # noqa: E712

    _print_section("Summary: Robust Top-2 Strategies")
    if not robust_top2.empty:
        label_col = (
            "strategy_label"
            if "strategy_label" in robust_top2.columns
            else "strategy_name"
        )
        print(
            f"  {len(robust_top2)} strategy/strategies rank top-2 under >= 3 of 4 schemes:"
        )
        for _, row in robust_top2.iterrows():
            lbl = row[label_col]
            n = row["n_times_top2"]
            passes = row["passes_v1_gates"]
            gate_str = "PASSES V1 gates" if passes else "FAILS V1 gates"
            print(f"    -> {lbl}  (top-2 in {n}/4 schemes, {gate_str})")
    else:
        print("  No strategy ranks top-2 under >= 3 of 4 weighting schemes.")
        print("  Consider ensemble/blending approach (see 42-CONTEXT.md).")

    print()
    if not gates_ok.empty:
        label_col = (
            "strategy_label"
            if "strategy_label" in gates_ok.columns
            else "strategy_name"
        )
        print(f"  {len(gates_ok)} strategy/strategies pass V1 hard gates:")
        for _, row in gates_ok.iterrows():
            print(f"    -> {row[label_col]}")
    else:
        print("  NOTE: No strategies pass BOTH V1 gates simultaneously.")
        print("  Best candidates by composite score (balanced scheme):")
        best = all_scored[0].head(3)
        label_col = (
            "strategy_label" if "strategy_label" in best.columns else "strategy_name"
        )
        for _, row in best.iterrows():
            print(
                f"    Rank {int(row['rank'])}: {row[label_col]} "
                f"(score={row['composite_score']:.4f}, "
                f"sharpe={row['sharpe_mean']:.3f}, "
                f"dd={_fmt_pct(row['max_drawdown_worst'], 1)})"
            )

    # --- Save CSVs ---
    composite_path = out_dir / "composite_scores.csv"
    sa_path = out_dir / "sensitivity_analysis.csv"

    composite_df.to_csv(composite_path, index=False)
    sa_df.to_csv(sa_path, index=False)

    print()
    print(f"  Saved: {composite_path}")
    print(f"  Saved: {sa_path}")

    return composite_df, sa_df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run composite scoring on bake-off results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--asset-id",
        type=int,
        default=1,
        help="Asset ID to score (default: 1 = BTC).",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe (default: 1D).",
    )
    parser.add_argument(
        "--cv-method",
        default="purged_kfold",
        choices=["purged_kfold", "cpcv"],
        help="CV method to score (default: purged_kfold).",
    )
    parser.add_argument(
        "--cost-scenario",
        default=None,
        help=(
            "Cost scenario label (e.g. spot_fee16_slip10). "
            "If omitted, auto-selects baseline. Ignored if --all-scenarios."
        ),
    )
    parser.add_argument(
        "--all-scenarios",
        action="store_true",
        default=False,
        help="Score all available cost scenarios (overrides --cost-scenario).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        type=Path,
        help=(f"Directory to save output CSVs (default: {_REPORT_DIR})."),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    composite_df, sa_df = run_scoring(
        asset_id=args.asset_id,
        tf=args.tf,
        cv_method=args.cv_method,
        cost_scenario=args.cost_scenario,
        all_scenarios=args.all_scenarios,
        output_dir=args.output_dir,
    )

    if composite_df.empty:
        sys.exit(1)


if __name__ == "__main__":
    main()
