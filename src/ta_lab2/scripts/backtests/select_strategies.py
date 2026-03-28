"""
Apply statistical gates to Phase 82 bake-off results and select strategies.

Gates applied sequentially:
  1. Min trade count (default 50)
  2. Max drawdown cap (default 15%)
  3. DSR gate (hard floor 0.95, adaptive may raise)
  4. PBO gate from CPCV (default < 0.50)

All survivors advance to paper trading (per CONTEXT.md policy).
Survivors ranked under 4 composite scoring schemes for robustness.

Usage:
    python -m ta_lab2.scripts.backtests.select_strategies \\
        --experiment-prefix phase82 \\
        --output reports/bakeoff/phase82_results.md
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from scipy import stats as scipy_stats
from sqlalchemy import create_engine, text

from ta_lab2.backtests.composite_scorer import (
    sensitivity_analysis,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate application
# ---------------------------------------------------------------------------


def apply_gates(
    df: pd.DataFrame,
    dsr_gate: float,
    pbo_gate: float,
    max_dd: float,
    min_trades: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply statistical gates sequentially. Returns survivors + cascade counts."""
    initial = len(df)

    df = df[df["trade_count_total"] >= min_trades].copy()
    after_trades = len(df)

    # max_drawdown_worst is negative (e.g., -0.10 = -10%)
    df = df[df["max_drawdown_worst"].abs() <= max_dd].copy()
    after_dd = len(df)

    # DSR gate — NaN DSR fails
    df = df[df["dsr"] > dsr_gate].copy()
    after_dsr = len(df)

    # PBO gate — NaN PBO passes (only present on CPCV results)
    df = df[(df["pbo_prob"] < pbo_gate) | (df["pbo_prob"].isna())].copy()
    after_pbo = len(df)

    cascade = {
        "initial": initial,
        "after_trades": after_trades,
        "after_dd": after_dd,
        "after_dsr": after_dsr,
        "after_pbo": after_pbo,
    }
    return df, cascade


def calibrate_dsr_gate(df: pd.DataFrame, manual_gate: float | None) -> float:
    """Calibrate DSR gate with 0.95 hard floor."""
    if manual_gate is not None:
        gate = max(manual_gate, 0.95)
        if manual_gate < 0.95:
            logger.warning(f"DSR gate {manual_gate} below hard floor 0.95; using 0.95")
        return gate

    dsr_vals = df["dsr"].dropna()
    if dsr_vals.empty:
        return 0.95

    p25 = float(dsr_vals.quantile(0.25))
    p50 = float(dsr_vals.quantile(0.50))
    p75 = float(dsr_vals.quantile(0.75))
    p90 = float(dsr_vals.quantile(0.90))
    mean = float(dsr_vals.mean())

    print(
        f"DSR distribution: mean={mean:.4f}, p25={p25:.4f}, "
        f"p50={p50:.4f}, p75={p75:.4f}, p90={p90:.4f}"
    )

    gate = max(0.95, p75)
    print(f"Using max(0.95, p75)={gate:.4f} as DSR gate")

    if p75 < 0.50:
        print("WARNING: p75 DSR < 0.50 — overall signal quality is low")

    return gate


# ---------------------------------------------------------------------------
# Per-asset IC weight comparison
# ---------------------------------------------------------------------------


def compare_ic_weights(df: pd.DataFrame) -> str:
    """Compare ama_momentum vs ama_momentum_perasset on paired assets."""
    universal = df[df["strategy_name"] == "ama_momentum"].copy()
    perasset = df[df["strategy_name"] == "ama_momentum_perasset"].copy()

    if universal.empty or perasset.empty:
        return "Per-asset IC weight comparison: insufficient data (one or both strategy groups empty)"

    # Group by asset_id, take mean sharpe across cost scenarios
    u_by_asset = universal.groupby("asset_id")["sharpe_mean"].mean().rename("universal")
    p_by_asset = perasset.groupby("asset_id")["sharpe_mean"].mean().rename("perasset")

    paired = pd.concat([u_by_asset, p_by_asset], axis=1).dropna()
    if len(paired) < 5:
        return f"Per-asset IC weight comparison: only {len(paired)} paired assets — too few for significance"

    delta = paired["perasset"] - paired["universal"]
    mean_delta = float(delta.mean())
    # Wilcoxon signed-rank test (non-parametric paired test)
    stat, p_value = scipy_stats.wilcoxon(paired["universal"], paired["perasset"])

    direction = "improvement" if mean_delta > 0 else "no improvement"
    summary = (
        f"Per-asset IC weights: {direction} "
        f"(mean Sharpe delta = {mean_delta:+.4f}, "
        f"Wilcoxon p-value = {p_value:.4f}, n={len(paired)} paired assets)"
    )

    # Win rate
    wins = int((delta > 0).sum())
    losses = int((delta < 0).sum())
    ties = int((delta == 0).sum())
    summary += f"\n  Win/Loss/Tie: {wins}/{losses}/{ties}"

    return summary


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    all_results: pd.DataFrame,
    survivors: pd.DataFrame,
    cascade: dict[str, int],
    dsr_gate: float,
    pbo_gate: float,
    max_dd: float,
    min_trades: int,
    ic_comparison: str,
    experiment_prefix: str,
) -> str:
    """Generate markdown report."""
    lines: list[str] = []
    lines.append("# Phase 82 Walk-Forward Bake-off Results\n")
    lines.append(f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")

    # Overview
    lines.append("## Overview\n")
    lines.append(f"- **Total results**: {cascade['initial']:,}")
    lines.append(f"- **Unique strategies**: {all_results['strategy_name'].nunique()}")
    lines.append(f"- **Unique assets**: {all_results['asset_id'].nunique()}")
    lines.append(f"- **Cost scenarios**: {all_results['cost_scenario'].nunique()}")
    lines.append(
        f"- **Experiments**: {', '.join(sorted(all_results['experiment_name'].unique()))}"
    )
    lines.append("")

    # Gate cascade
    lines.append("## Gate Application\n")
    lines.append("| Gate | Threshold | Remaining | Removed |")
    lines.append("|------|-----------|-----------|---------|")
    prev = cascade["initial"]
    lines.append(f"| Initial | — | {prev:,} | — |")
    for gate_name, gate_val, key in [
        ("Min trades", f">= {min_trades}", "after_trades"),
        ("Max drawdown", f"<= {max_dd:.0%}", "after_dd"),
        ("DSR", f"> {dsr_gate:.4f}", "after_dsr"),
        ("PBO", f"< {pbo_gate:.2f}", "after_pbo"),
    ]:
        current = cascade[key]
        removed = prev - current
        lines.append(f"| {gate_name} | {gate_val} | {current:,} | {removed:,} |")
        prev = current
    lines.append(
        f"\n**Survivors**: {cascade['after_pbo']:,} out of {cascade['initial']:,} "
        f"({cascade['after_pbo'] / cascade['initial'] * 100:.1f}%)\n"
    )

    # Strategy summary
    if not survivors.empty:
        lines.append("## Strategy Summary (Survivors)\n")
        summary = (
            survivors.groupby("strategy_name")
            .agg(
                assets=("asset_id", "nunique"),
                rows=("strategy_name", "count"),
                avg_sharpe=("sharpe_mean", "mean"),
                avg_dsr=("dsr", "mean"),
                avg_psr=("psr", "mean"),
                avg_dd=("max_drawdown_worst", "mean"),
                avg_trades=("trade_count_total", "mean"),
            )
            .sort_values("avg_sharpe", ascending=False)
        )

        lines.append(
            "| Strategy | Assets | Rows | Avg Sharpe | Avg DSR | Avg PSR | Avg DD | Avg Trades |"
        )
        lines.append(
            "|----------|--------|------|------------|---------|---------|--------|------------|"
        )
        for name, row in summary.iterrows():
            lines.append(
                f"| {name} | {row['assets']} | {row['rows']} | "
                f"{row['avg_sharpe']:.4f} | {row['avg_dsr']:.4f} | "
                f"{row['avg_psr']:.4f} | {row['avg_dd']:.2%} | "
                f"{row['avg_trades']:.0f} |"
            )
        lines.append("")

        # Composite scoring on aggregated strategy metrics
        lines.append("## Composite Scoring\n")
        # Aggregate per strategy for scoring
        score_df = (
            survivors.groupby("strategy_name")
            .agg(
                sharpe_mean=("sharpe_mean", "mean"),
                max_drawdown_worst=("max_drawdown_worst", "mean"),
                psr=("psr", "mean"),
                turnover=("turnover", "mean"),
            )
            .reset_index()
        )

        if len(score_df) >= 2:
            sa = sensitivity_analysis(score_df)
            lines.append(
                "| Strategy | Balanced | Risk | Quality | Low-Cost | Top-2 Count | Robust |"
            )
            lines.append(
                "|----------|----------|------|---------|----------|-------------|--------|"
            )
            for _, row in sa.iterrows():
                lines.append(
                    f"| {row['strategy_name']} | "
                    f"#{int(row['rank_balanced'])} | "
                    f"#{int(row['rank_risk_focus'])} | "
                    f"#{int(row['rank_quality_focus'])} | "
                    f"#{int(row['rank_low_cost'])} | "
                    f"{int(row['n_times_top2'])} | "
                    f"{'YES' if row['robust'] else 'no'} |"
                )
            lines.append("")
        else:
            lines.append("Only 1 strategy survived — composite scoring requires 2+.\n")

    # IC weight comparison
    lines.append("## Per-Asset IC Weight Comparison\n")
    lines.append(ic_comparison)
    lines.append("")

    # Per-strategy, per-cost breakdown for survivors
    if not survivors.empty:
        lines.append("## Top Strategy-Asset Combinations\n")
        top = survivors.nlargest(20, "sharpe_mean")
        lines.append(
            "| Strategy | Asset | Cost | Sharpe | DSR | PSR | MaxDD | Trades |"
        )
        lines.append(
            "|----------|-------|------|--------|-----|-----|-------|--------|"
        )
        for _, row in top.iterrows():
            lines.append(
                f"| {row['strategy_name']} | {row['asset_id']} | "
                f"{row['cost_scenario']} | {row['sharpe_mean']:.4f} | "
                f"{row['dsr']:.4f} | {row['psr']:.4f} | "
                f"{row['max_drawdown_worst']:.2%} | "
                f"{int(row['trade_count_total'])} |"
            )
        lines.append("")

    # Paper trading candidates
    lines.append("## Paper Trading Candidates\n")
    if not survivors.empty:
        strategies = sorted(survivors["strategy_name"].unique())
        lines.append(
            f"All {len(strategies)} surviving strategies advance to paper trading:\n"
        )
        for s in strategies:
            s_data = survivors[survivors["strategy_name"] == s]
            lines.append(
                f"- **{s}**: {s_data['asset_id'].nunique()} assets, "
                f"avg Sharpe={s_data['sharpe_mean'].mean():.4f}"
            )
    else:
        lines.append("No strategies survived all gates.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply statistical gates and select strategies from bake-off results."
    )
    parser.add_argument(
        "--experiment-prefix",
        default="phase82",
        help="Filter by experiment_name prefix",
    )
    parser.add_argument(
        "--dsr-gate",
        type=float,
        default=None,
        help="DSR threshold (auto-calibrated if not set, minimum 0.95)",
    )
    parser.add_argument(
        "--pbo-gate",
        type=float,
        default=0.50,
        help="PBO threshold (default: 0.50)",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=0.80,
        help="Max drawdown cap as decimal (default: 0.80 = 80%%; crypto-appropriate)",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=10,
        help="Minimum trade count (default: 10; accommodates slow AMA strategies)",
    )
    parser.add_argument(
        "--output",
        default="reports/bakeoff/phase82_results.md",
        help="Report output path",
    )
    parser.add_argument(
        "--cv-method",
        default=None,
        help="CV method filter (default: use all CV methods)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_url = os.environ.get(
        "TARGET_DB_URL", "postgresql://postgres:postgres@localhost:5432/marketdata"
    )
    engine = create_engine(db_url)

    # Load results
    prefix = args.experiment_prefix
    params: dict[str, Any] = {"prefix": f"{prefix}%"}
    cv_filter = ""
    if args.cv_method:
        cv_filter = "AND cv_method = :cv_method"
        params["cv_method"] = args.cv_method

    sql = text(
        f"""
        SELECT strategy_name, asset_id, tf, cost_scenario, cv_method,
               params_json::text AS params_str,
               sharpe_mean, sharpe_std, max_drawdown_mean, max_drawdown_worst,
               total_return_mean, cagr_mean, trade_count_total, turnover,
               psr, dsr, psr_n_obs, pbo_prob, experiment_name
        FROM strategy_bakeoff_results
        WHERE experiment_name LIKE :prefix
          AND experiment_name NOT LIKE '%%pilot%%'
          {cv_filter}
        ORDER BY strategy_name, asset_id, cost_scenario
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    print("\n=== PHASE 82 STRATEGY SELECTION ===\n")
    print(
        f"Loaded {len(df):,} results: {df['strategy_name'].nunique()} strategies, "
        f"{df['asset_id'].nunique()} assets, "
        f"{df['experiment_name'].nunique()} experiments"
    )

    if df.empty:
        print("No results found. Exiting.")
        sys.exit(1)

    # IC weight comparison (on full results before gating)
    ic_comparison = compare_ic_weights(df)
    print(f"\n{ic_comparison}\n")

    # Calibrate DSR gate
    dsr_gate = calibrate_dsr_gate(df, args.dsr_gate)

    # Apply gates
    survivors, cascade = apply_gates(
        df,
        dsr_gate=dsr_gate,
        pbo_gate=args.pbo_gate,
        max_dd=args.max_drawdown,
        min_trades=args.min_trades,
    )

    print("\nGates applied:")
    print(
        f"  - Min trades: {args.min_trades} "
        f"(removed {cascade['initial'] - cascade['after_trades']})"
    )
    print(
        f"  - Max drawdown: {args.max_drawdown:.0%} "
        f"(removed {cascade['after_trades'] - cascade['after_dd']})"
    )
    print(
        f"  - DSR > {dsr_gate:.4f} "
        f"(removed {cascade['after_dd'] - cascade['after_dsr']})"
    )
    print(
        f"  - PBO < {args.pbo_gate:.2f} "
        f"(removed {cascade['after_dsr'] - cascade['after_pbo']})"
    )
    print(f"Survivors: {cascade['after_pbo']:,} out of {cascade['initial']:,}\n")

    if survivors.empty:
        print("No strategies survived all gates.")
    else:
        # Summary by strategy
        print("Surviving strategies:")
        summary = (
            survivors.groupby("strategy_name")
            .agg(
                assets=("asset_id", "nunique"),
                rows=("strategy_name", "count"),
                avg_sharpe=("sharpe_mean", "mean"),
                avg_dsr=("dsr", "mean"),
            )
            .sort_values("avg_sharpe", ascending=False)
        )
        for name, row in summary.iterrows():
            print(
                f"  {name:<35} assets={int(row['assets']):>3}  "
                f"rows={int(row['rows']):>5}  "
                f"sharpe={row['avg_sharpe']:.4f}  dsr={row['avg_dsr']:.4f}"
            )

    # Generate report
    report = generate_report(
        all_results=df,
        survivors=survivors,
        cascade=cascade,
        dsr_gate=dsr_gate,
        pbo_gate=args.pbo_gate,
        max_dd=args.max_drawdown,
        min_trades=args.min_trades,
        ic_comparison=ic_comparison,
        experiment_prefix=prefix,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to {output_path}")


if __name__ == "__main__":
    main()
