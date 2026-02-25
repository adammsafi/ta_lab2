"""
CLI to run VaR simulation on backtest trade returns.

Loads trade-level returns from cmc_backtest_trades (with fallback to daily bar
returns from cmc_returns_bars_multi_tf_u), runs the full VaR suite at 95% and 99%
confidence levels, generates VAR_REPORT.md and var_comparison.html chart.

Purpose: connects the var_simulator library (Phase 48 Plan 01) to real DB data
and produces the LOSS-01 deliverables.

Usage
-----
    # All default strategies (ema_trend_17_77, ema_trend_21_50, rsi_mean_revert,
    # breakout_atr) for BTC and ETH:
    python -m ta_lab2.scripts.analysis.run_var_simulation

    # Specific strategies:
    python -m ta_lab2.scripts.analysis.run_var_simulation \\
        --strategies ema_trend_17_77 ema_trend_21_50 --asset-ids 1

    # Dry-run (print config only):
    python -m ta_lab2.scripts.analysis.run_var_simulation --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy import create_engine

from ta_lab2.analysis.var_simulator import (
    VaRResult,
    compute_var_suite,
    var_to_daily_cap,
)
from ta_lab2.config import TARGET_DB_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project layout
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "reports" / "loss_limits"

# Default strategy/asset sets (all 4 bakeoff strategies, BTC+ETH)
_DEFAULT_STRATEGIES = [
    "ema_trend_17_77",
    "ema_trend_21_50",
    "rsi_mean_revert",
    "breakout_atr",
]
_DEFAULT_ASSET_IDS = [1, 2]
_DEFAULT_CONFIDENCE_LEVELS = [0.95, 0.99]

# Signal type -> backtest signal_type mapping (exact values in cmc_backtest_runs)
_SIGNAL_TYPE_MAP = {
    "ema_trend_17_77": "ema_trend_17_77",
    "ema_trend_21_50": "ema_trend_21_50",
    "rsi_mean_revert": "rsi_mean_revert",
    "breakout_atr": "breakout_atr",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_pct(v: float, decimals: int = 2) -> str:
    """Format float as percentage string (e.g., -0.05 -> '-5.00%')."""
    if pd.isna(v) or v is None:
        return "N/A"
    return f"{v * 100:.{decimals}f}%"


def _fmt_float(v: float, decimals: int = 4) -> str:
    if pd.isna(v) or v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def _fmt_bool(v: bool) -> str:
    return "Yes" if v else "No"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_backtest_returns(
    engine,
    signal_type: str,
    asset_id: int,
) -> tuple[np.ndarray, str]:
    """
    Load trade-level returns for (signal_type, asset_id).

    Returns (returns_array, source_description).
    Falls back to daily bar returns if no backtest trades found.
    """
    try:
        # Column is pnl_pct (not return_pct) in cmc_backtest_trades
        sql = text(
            """
            SELECT bt.pnl_pct
            FROM public.cmc_backtest_trades bt
            JOIN public.cmc_backtest_runs r ON bt.run_id = r.run_id
            WHERE r.signal_type = :signal_type
              AND r.asset_id = :asset_id
            ORDER BY bt.exit_ts
            """
        )
        with engine.connect() as conn:
            df = pd.read_sql(
                sql, conn, params={"signal_type": signal_type, "asset_id": asset_id}
            )
    except Exception as exc:
        logger.warning(
            "Could not query cmc_backtest_trades for %s/asset_id=%d: %s. "
            "Falling back to bar returns.",
            signal_type,
            asset_id,
            exc,
        )
        df = pd.DataFrame()

    if not df.empty and len(df) >= 10:
        returns = df["pnl_pct"].dropna().values.astype(float) / 100.0
        source = "cmc_backtest_trades"
        logger.info(
            "Loaded %d trade returns for %s/asset_id=%d",
            len(returns),
            signal_type,
            asset_id,
        )
        return returns, source

    # Fallback to daily bar returns
    logger.warning(
        "No backtest data found for %s/asset_id=%d; using raw bar returns as proxy.",
        signal_type,
        asset_id,
    )
    try:
        # Timestamp column is 'timestamp' (not 'ts') in cmc_returns_bars_multi_tf_u
        sql = text(
            """
            SELECT ret_arith
            FROM public.cmc_returns_bars_multi_tf_u
            WHERE id = :asset_id AND tf = '1D'
            ORDER BY timestamp
            """
        )
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"asset_id": asset_id})
    except Exception as exc:
        logger.error(
            "Fallback bar returns query failed for asset_id=%d: %s",
            asset_id,
            exc,
        )
        return np.array([]), "error"

    if df.empty:
        logger.error("No bar returns found for asset_id=%d either.", asset_id)
        return np.array([]), "empty"

    returns = df["ret_arith"].dropna().values.astype(float)
    source = "cmc_returns_bars_multi_tf_u"
    logger.info(
        "Loaded %d bar returns for asset_id=%d (fallback proxy)",
        len(returns),
        asset_id,
    )
    return returns, source


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def run_var_simulation(
    strategies: list[str],
    asset_ids: list[int],
    confidence_levels: list[float],
    output_dir: Path,
) -> list[VaRResult]:
    """
    Run VaR simulation for all (strategy, asset_id, confidence_level) combinations.

    Returns list of VaRResult instances.
    """
    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    all_results: list[VaRResult] = []

    for strategy in strategies:
        signal_type = _SIGNAL_TYPE_MAP.get(strategy, strategy)
        for asset_id in asset_ids:
            returns, _source = _load_backtest_returns(engine, signal_type, asset_id)

            if len(returns) < 5:
                logger.warning(
                    "Insufficient data (%d obs) for %s/asset_id=%d -- skipping.",
                    len(returns),
                    strategy,
                    asset_id,
                )
                continue

            for confidence in confidence_levels:
                result = compute_var_suite(
                    returns=returns,
                    strategy=strategy,
                    asset_id=asset_id,
                    confidence=confidence,
                )
                all_results.append(result)
                logger.info(
                    "VaR[%s, asset=%d, %.0f%%]: hist=%.4f, cf=%.4f, normal=%.4f, cvar=%.4f",
                    strategy,
                    asset_id,
                    confidence * 100,
                    result.historical_var,
                    result.cornish_fisher_var,
                    result.parametric_var_normal,
                    result.historical_cvar,
                )

    engine.dispose()
    return all_results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _build_var_report(
    results: list[VaRResult],
    data_source: str,
    output_dir: Path,
) -> Path:
    """Write VAR_REPORT.md to output_dir. Returns the path."""
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = []
    lines.append("# VaR Analysis Report")
    lines.append("")
    lines.append(f"Generated: {timestamp}  ")
    lines.append(f"Data source: {data_source}")
    lines.append("")

    # --- Summary table ---
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Strategy | Asset | Confidence | Hist VaR | CF VaR | Normal VaR | CVaR | "
        "CF Reliable | Skew | Excess Kurt |"
    )
    lines.append(
        "|----------|-------|------------|----------|--------|------------|------|"
        "-------------|------|-------------|"
    )

    for r in results:
        lines.append(
            f"| {r.strategy} | {r.asset_id} | {r.confidence:.0%} | "
            f"{_fmt_pct(r.historical_var)} | "
            f"{_fmt_pct(r.cornish_fisher_var)} | "
            f"{_fmt_pct(r.parametric_var_normal)} | "
            f"{_fmt_pct(r.historical_cvar)} | "
            f"{_fmt_bool(r.cf_reliable)} | "
            f"{_fmt_float(r.skewness, 3)} | "
            f"{_fmt_float(r.excess_kurtosis, 3)} |"
        )

    lines.append("")

    # --- Key Finding: Historical vs CF Divergence ---
    lines.append("## Key Finding: Historical vs Cornish-Fisher Divergence")
    lines.append("")

    # Focus on 99% confidence for maximum tail divergence visibility
    results_99 = [r for r in results if abs(r.confidence - 0.99) < 1e-6]

    divergences_found = False
    for r in results_99:
        hist = r.historical_var
        cf = r.cornish_fisher_var
        if hist == 0:
            continue
        divergence_pct = abs(cf - hist) / abs(hist)
        if divergence_pct > 0.20:
            divergences_found = True
            lines.append(
                f"- **{r.strategy}** (asset {r.asset_id}): At 99%, historical VaR = "
                f"{_fmt_pct(hist)}, CF VaR = {_fmt_pct(cf)}, "
                f"divergence = {divergence_pct * 100:.1f}%"
            )
            if not r.cf_reliable:
                lines.append(
                    f"  - WARNING: Excess kurtosis = {r.excess_kurtosis:.2f} > 8; "
                    "CF VaR is unreliable for this strategy."
                )

    if not divergences_found:
        lines.append(
            "No strategies show >20% divergence between historical and CF VaR at 99%. "
            "Historical and CF methods are in agreement."
        )

    lines.append("")

    # --- Recommended Daily Loss Cap ---
    lines.append("## Recommended Daily Loss Cap")
    lines.append("")

    # Prefer CF if reliable for majority, else historical
    results_95 = [r for r in results if abs(r.confidence - 0.95) < 1e-6]
    if results_95:
        cf_reliable_count = sum(1 for r in results_95 if r.cf_reliable)
        if cf_reliable_count >= len(results_95) // 2:
            method = "cf_95"
            method_label = "Cornish-Fisher (95%)"
        else:
            method = "historical_95"
            method_label = "Historical (95%)"

        try:
            cap = var_to_daily_cap(results_95, method=method)
            lines.append(f"Based on {method_label} VaR:")
            lines.append(
                f"- **Recommended daily_loss_pct_threshold: {cap * 100:.1f}%**"
            )
            lines.append(
                f"- Derivation: median of {method_label} VaR across strategies, capped at 15%"
            )
        except Exception as exc:
            lines.append(f"Could not compute daily cap: {exc}")
    else:
        lines.append("No 95% confidence results available for cap computation.")

    lines.append("")

    report_path = output_dir / "VAR_REPORT.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("VAR_REPORT.md written to %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------


def _build_var_chart(results: list[VaRResult], output_dir: Path) -> Path:
    """Generate var_comparison.html grouped bar chart."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        logger.warning("plotly not available -- skipping chart generation.")
        return output_dir / "charts" / "var_comparison.html"

    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    # Build X labels: "strategy (asset_id) @ confidence%"
    labels = [
        f"{r.strategy[:20]}\nasset={r.asset_id} @{r.confidence:.0%}" for r in results
    ]

    # VaR values (flip sign: show as positive loss magnitude)
    hist_vals = [abs(r.historical_var) * 100 for r in results]
    cf_vals = [abs(r.cornish_fisher_var) * 100 for r in results]
    normal_vals = [abs(r.parametric_var_normal) * 100 for r in results]
    cvar_vals = [abs(r.historical_cvar) * 100 for r in results]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(name="Historical VaR", x=labels, y=hist_vals, marker_color="#2196F3")
    )
    fig.add_trace(
        go.Bar(name="Cornish-Fisher VaR", x=labels, y=cf_vals, marker_color="#FF9800")
    )
    fig.add_trace(
        go.Bar(
            name="Parametric Normal VaR",
            x=labels,
            y=normal_vals,
            marker_color="#4CAF50",
        )
    )
    fig.add_trace(
        go.Bar(
            name="CVaR (Expected Shortfall)",
            x=labels,
            y=cvar_vals,
            marker_color="#F44336",
        )
    )

    fig.update_layout(
        title="VaR Comparison by Strategy, Asset, and Confidence Level",
        xaxis_title="Strategy / Asset / Confidence",
        yaxis_title="VaR Loss Magnitude (%)",
        barmode="group",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=600,
        margin=dict(l=60, r=60, t=100, b=120),
    )

    chart_path = charts_dir / "var_comparison.html"
    fig.write_html(str(chart_path))
    logger.info("var_comparison.html written to %s", chart_path)
    return chart_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run VaR simulation on backtest trade returns.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=_DEFAULT_STRATEGIES,
        help=(
            "Strategy names to analyze "
            "(default: ema_trend_17_77 ema_trend_21_50 rsi_mean_revert breakout_atr)."
        ),
    )
    parser.add_argument(
        "--asset-ids",
        nargs="+",
        type=int,
        default=_DEFAULT_ASSET_IDS,
        help="Asset IDs to analyze (default: 1 2 for BTC/ETH).",
    )
    parser.add_argument(
        "--confidence-levels",
        nargs="+",
        type=float,
        default=_DEFAULT_CONFIDENCE_LEVELS,
        help="Confidence levels (default: 0.95 0.99).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Report output directory (default: {_DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print configuration and exit without running.",
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
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print()
    print("=" * 70)
    print("  VaR Simulation")
    print("=" * 70)
    print(f"  Strategies:        {args.strategies}")
    print(f"  Asset IDs:         {args.asset_ids}")
    print(f"  Confidence levels: {[f'{c:.0%}' for c in args.confidence_levels]}")
    print(f"  Output directory:  {args.output_dir}")
    print()

    if args.dry_run:
        print("  [dry-run] Configuration printed. Exiting.")
        return

    # Run simulation
    results = run_var_simulation(
        strategies=args.strategies,
        asset_ids=args.asset_ids,
        confidence_levels=args.confidence_levels,
        output_dir=args.output_dir,
    )

    if not results:
        print(
            "  No VaR results computed -- check DB connectivity and data availability."
        )
        sys.exit(1)

    print(f"  Computed {len(results)} VaR results.")

    # Determine data source for report header
    # (approximate: if we got lots of obs it's likely from bar returns)
    data_source = "cmc_backtest_trades (with bar returns fallback where needed)"

    # Generate report
    report_path = _build_var_report(results, data_source, args.output_dir)
    print(f"  Saved: {report_path}")

    # Generate chart
    chart_path = _build_var_chart(results, args.output_dir)
    print(f"  Saved: {chart_path}")

    print()
    print("  Done.")


if __name__ == "__main__":
    main()
