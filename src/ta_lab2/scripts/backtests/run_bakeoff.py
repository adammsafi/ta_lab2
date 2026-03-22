"""
CLI entry point for running the strategy bake-off.

Runs all signal strategies through purged K-fold CV and CPCV with the full
Kraken cost matrix, producing out-of-sample metrics for composite scoring.
Results are persisted to strategy_bakeoff_results.

Usage
-----
    # Dry run: list combinations without computing
    python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D

    # Full bake-off on BTC/ETH 1D (all 12 cost scenarios)
    python -m ta_lab2.scripts.backtests.run_bakeoff --assets 1 1027 --tf 1D

    # Spot-only (6 scenarios) for faster runs
    python -m ta_lab2.scripts.backtests.run_bakeoff --assets 1 1027 --tf 1D --spot-only

    # Single strategy for debugging
    python -m ta_lab2.scripts.backtests.run_bakeoff --assets 1 --tf 1D --strategies ema_trend --spot-only

    # Overwrite existing results
    python -m ta_lab2.scripts.backtests.run_bakeoff --assets 1 1027 --tf 1D --overwrite

    # Hyperliquid cost matrix (6 tighter scenarios)
    python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D --exchange hyperliquid

    # Both exchanges (18 scenarios: 12 Kraken + 6 HL)
    python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D --exchange all

    # AMA strategies with AMA data loader
    python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D --strategies ama_momentum

    # Expression engine experiments from YAML
    python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D \\
        --experiments-yaml configs/experiments/signals_phase82.yaml

    # Tag results with experiment name for lineage tracking
    python -m ta_lab2.scripts.backtests.run_bakeoff --assets 1 1027 --tf 1D \\
        --experiments-yaml configs/experiments/signals_phase82.yaml \\
        --experiment-name phase82-ama-v1

NOTE: Expanding-window re-optimization is DELIBERATELY DEFERRED.
This script implements fixed-parameter walk-forward only (standard baseline).
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from sqlalchemy import NullPool, create_engine, text

from ta_lab2.backtests.bakeoff_orchestrator import (
    BakeoffConfig,
    BakeoffOrchestrator,
    StrategyResult,
    cost_scenario_label,
    parse_active_features,
)
from ta_lab2.backtests.costs import COST_MATRIX_REGISTRY
from ta_lab2.config import TARGET_DB_URL
from ta_lab2.signals.registry import REGISTRY, get_strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategy configurations
# ---------------------------------------------------------------------------

# Per-strategy default param grids (small grids for V1 baseline)
# grid_for() from registry provides baseline grids; we use a small subset
# for walk-forward to keep runtime manageable.
_BAKEOFF_PARAM_GRIDS: Dict[str, List[Dict[str, Any]]] = {
    "ema_trend": [
        # Core EMA crossover configs: fast/slow pairs
        {"fast_ema": "ema_21", "slow_ema": "ema_50"},
        {"fast_ema": "ema_10", "slow_ema": "ema_50"},
        {"fast_ema": "ema_21", "slow_ema": "ema_100"},
        {"fast_ema": "ema_17", "slow_ema": "ema_77"},
    ],
    "rsi_mean_revert": [
        # RSI mean-reversion configs
        {
            "rsi_col": "rsi_14",
            "lower": 30.0,
            "upper": 70.0,
            "confirm_cross": True,
            "allow_shorts": False,
            "atr_col": "atr_14",
            "risk_pct": 0.5,
            "atr_mult_stop": 1.5,
            "max_leverage": 1.0,
        },
        {
            "rsi_col": "rsi_14",
            "lower": 25.0,
            "upper": 65.0,
            "confirm_cross": True,
            "allow_shorts": False,
            "atr_col": "atr_14",
            "risk_pct": 0.5,
            "atr_mult_stop": 1.5,
            "max_leverage": 1.0,
        },
        {
            "rsi_col": "rsi_14",
            "lower": 35.0,
            "upper": 75.0,
            "confirm_cross": True,
            "allow_shorts": False,
            "atr_col": "atr_14",
            "risk_pct": 0.5,
            "atr_mult_stop": 1.5,
            "max_leverage": 1.0,
        },
    ],
    "breakout_atr": [
        # ATR breakout configs
        {
            "lookback": 20,
            "atr_col": "atr_14",
            "confirm_close": True,
            "exit_on_channel_crossback": True,
            "use_trailing_atr_stop": True,
            "trail_atr_mult": 2.0,
            "risk_pct": 0.5,
            "max_leverage": 1.0,
        },
        {
            "lookback": 20,
            "atr_col": "atr_14",
            "confirm_close": True,
            "exit_on_channel_crossback": True,
            "use_trailing_atr_stop": True,
            "trail_atr_mult": 3.0,
            "risk_pct": 0.5,
            "max_leverage": 1.0,
        },
        {
            "lookback": 40,
            "atr_col": "atr_14",
            "confirm_close": True,
            "exit_on_channel_crossback": True,
            "use_trailing_atr_stop": True,
            "trail_atr_mult": 2.0,
            "risk_pct": 0.5,
            "max_leverage": 1.0,
        },
    ],
    # ---------------------------------------------------------------------------
    # Phase 82: AMA-based strategies (require AMA columns pre-loaded from DB)
    # ---------------------------------------------------------------------------
    "ama_momentum": [
        {"holding_bars": 5, "threshold": 0.0},
        {"holding_bars": 7, "threshold": 0.0},
        {"holding_bars": 10, "threshold": 0.5},
    ],
    "ama_mean_reversion": [
        {
            "ama_col": "KAMA_de1106d5_ama",
            "entry_zscore": -1.5,
            "exit_zscore": 0.0,
            "holding_bars": 10,
        },
        {
            "ama_col": "KAMA_de1106d5_ama",
            "entry_zscore": -2.0,
            "exit_zscore": 0.0,
            "holding_bars": 7,
        },
        {
            "ama_col": "KAMA_987fc105_ama",
            "entry_zscore": -1.5,
            "exit_zscore": 0.0,
            "holding_bars": 10,
        },
    ],
    "ama_regime_conditional": [
        {"adx_threshold": 20.0, "holding_bars": 7},
        {"adx_threshold": 15.0, "holding_bars": 5},
        {"adx_threshold": 25.0, "holding_bars": 10},
    ],
}

# V1 hard gates for strategy selection
V1_SHARPE_GATE = 1.0  # Minimum OOS Sharpe
V1_MAX_DD_GATE = 0.15  # Maximum acceptable drawdown (15%)

# AMA strategy names: strategies that require AMA columns pre-loaded from DB.
# When any of these is requested, load_strategy_data_with_ama() is used.
_AMA_STRATEGY_NAMES: frozenset[str] = frozenset(
    {"ama_momentum", "ama_mean_reversion", "ama_regime_conditional"}
)


def _make_expression_signal(
    expression: str,
    holding_bars: int,
) -> Callable:
    """
    Create a bake-off signal function from an expression engine expression.

    The returned function has signature:
        (df: pd.DataFrame, **params) -> (entries, exits, size)

    Signal logic:
        entries = expression_value > 0
        exits   = expression_value < 0
        size    = None (equal-weight sizing)

    The expression is evaluated via evaluate_expression() against the full
    DataFrame (which must include all $col columns referenced). The holding_bars
    parameter is used by the bake-off orchestrator via t1_series (not enforced
    here -- t1_series length is set externally per experiment).

    Parameters
    ----------
    expression : str
        Expression engine $col-syntax expression string.
    holding_bars : int
        Holding period in bars (informational; used to key param grids).

    Returns
    -------
    Callable
        Signal function for use in strategies dict.
    """
    from ta_lab2.ml.expression_engine import evaluate_expression

    def signal_fn(
        df: Any,
        **params: Any,
    ) -> Tuple[Any, Any, None]:
        signal_series = evaluate_expression(expression, df)
        entries = signal_series > 0
        exits = signal_series < 0
        return entries.fillna(False), exits.fillna(False), None

    signal_fn.__name__ = f"expression_signal_hb{holding_bars}"
    return signal_fn


def _load_experiments_yaml(
    yaml_path: str,
) -> Dict[str, Tuple[Callable, List[Dict[str, Any]]]]:
    """
    Load expression engine experiments from YAML and build strategies dict.

    Each experiment in the YAML becomes a strategy entry:
        strategy_name -> (signal_fn, [{"holding_bars": hb} for hb in holding_bars])

    Parameters
    ----------
    yaml_path : str
        Path to YAML experiments file (e.g. configs/experiments/signals_phase82.yaml).

    Returns
    -------
    dict
        {experiment_name: (signal_fn, param_grid)} mapping ready for bake-off.
    """
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    experiments: Dict[str, Tuple[Callable, List[Dict[str, Any]]]] = {}
    exp_dict = data.get("experiments", {})

    for exp_name, exp_cfg in exp_dict.items():
        expression = exp_cfg["compute"]["expression"]
        holding_bars_list = exp_cfg.get("holding_bars", [5])

        # Build param grid: one entry per holding period
        param_grid = [{"holding_bars": hb} for hb in holding_bars_list]

        # Create signal function for this expression
        # Use the first holding_bars as the label for __name__
        signal_fn = _make_expression_signal(expression, holding_bars_list[0])

        experiments[exp_name] = (signal_fn, param_grid)
        logger.info(
            f"Loaded expression experiment '{exp_name}': "
            f"{len(param_grid)} holding period(s) -> {holding_bars_list}"
        )

    return experiments


def _build_strategies(
    strategy_names: Optional[List[str]] = None,
    experiments_yaml: Optional[str] = None,
) -> Dict[str, Tuple[Callable, List[Dict[str, Any]]]]:
    """
    Build strategies dict: {name: (signal_fn, param_grid)}.

    Filters to available strategies (those in REGISTRY with a callable).
    If experiments_yaml is provided, also loads expression engine experiments
    from the YAML file and adds them to the strategies dict.

    Parameters
    ----------
    strategy_names : list of str, optional
        Strategy names to include from REGISTRY. Default: all available.
    experiments_yaml : str, optional
        Path to YAML experiments file (e.g. configs/experiments/signals_phase82.yaml).
        Experiments are added to the strategies dict under their YAML name.
    """
    # Determine which strategies to run
    if strategy_names is None:
        names_to_run = [k for k, v in REGISTRY.items() if v is not None]
    else:
        names_to_run = strategy_names

    strategies: Dict[str, Tuple[Callable, List[Dict[str, Any]]]] = {}

    for name in names_to_run:
        # Check if strategy is available
        try:
            signal_fn = get_strategy(name)
        except KeyError:
            logger.warning(f"Strategy '{name}' not available, skipping")
            continue

        # Get param grid
        if name in _BAKEOFF_PARAM_GRIDS and _BAKEOFF_PARAM_GRIDS[name]:
            param_grid = _BAKEOFF_PARAM_GRIDS[name]
        else:
            logger.warning(
                f"No param grid for '{name}' in _BAKEOFF_PARAM_GRIDS, skipping"
            )
            continue

        strategies[name] = (signal_fn, param_grid)
        logger.info(f"Strategy '{name}': {len(param_grid)} param set(s)")

    # Load expression engine experiments from YAML (Phase 82+)
    if experiments_yaml:
        exp_strategies = _load_experiments_yaml(experiments_yaml)
        strategies.update(exp_strategies)
        logger.info(
            f"Loaded {len(exp_strategies)} expression experiments from {experiments_yaml}"
        )

    return strategies


def _print_dry_run(
    strategies: Dict[str, Tuple[Callable, List[Dict[str, Any]]]],
    asset_ids: List[int],
    tf: str,
    config: BakeoffConfig,
) -> None:
    """Print dry-run summary of planned combinations."""
    cost_matrix = config.get_cost_matrix()
    n_cv_methods = 2  # purged_kfold + cpcv

    total = 0
    print("\n=== DRY RUN: Planned Bake-Off Combinations ===\n")
    print(f"Assets: {asset_ids}")
    print(f"Timeframe: {tf}")
    print(
        f"CV methods: purged_kfold ({config.n_folds} folds, {config.embargo_bars}-bar embargo) + cpcv"
    )
    print(f"Cost scenarios: {len(cost_matrix)}")
    for cost in cost_matrix:
        print(f"  - {cost_scenario_label(cost)}: {cost.describe()}")
    print()

    for strategy_name, (_, param_grid) in strategies.items():
        n_combos = len(param_grid) * len(asset_ids) * len(cost_matrix) * n_cv_methods
        total += n_combos
        print(
            f"Strategy '{strategy_name}': {len(param_grid)} params x {len(asset_ids)} assets "
            f"x {len(cost_matrix)} costs x {n_cv_methods} CV = {n_combos} runs"
        )
        for i, params in enumerate(param_grid):
            param_str = ", ".join(f"{k}={v}" for k, v in list(params.items())[:3])
            print(f"  Params[{i}]: {param_str}{'...' if len(params) > 3 else ''}")

    print(f"\nTotal: {total} result rows")

    # Rough time estimate
    secs_per_run = 3  # rough estimate per (strategy x cost x CV fold)
    n_folds_total = config.n_folds + (45 if not config.spot_only else 45)  # pkf + cpcv
    total_secs = (
        sum(len(grid) for _, (_, grid) in strategies.items())
        * len(asset_ids)
        * len(cost_matrix)
        * n_folds_total
        * secs_per_run
    )
    print(
        f"Estimated runtime: ~{total_secs / 60:.0f} min ({total_secs / 3600:.1f} hours)"
    )
    print()


def _print_summary(results: List[StrategyResult]) -> None:
    """Print post-run summary of OOS metrics per strategy."""
    if not results:
        print("\nNo results to summarize.")
        return

    print("\n=== BAKE-OFF SUMMARY ===\n")

    # Group by strategy name + cv_method, pick best Sharpe param set
    from collections import defaultdict

    by_strategy_cv: Dict[Tuple, List[StrategyResult]] = defaultdict(list)
    for sr in results:
        key = (sr.strategy_name, sr.cv_method, sr.asset_id)
        by_strategy_cv[key].append(sr)

    print(
        f"{'Strategy':<20} {'CV':<16} {'Asset':>7} {'Sharpe':>8} {'MaxDD':>8} {'PSR':>6} {'DSR':>6} {'Gate':>6}"
    )
    print("-" * 85)

    for (strategy_name, cv_method, asset_id), srs in sorted(by_strategy_cv.items()):
        # Best params by Sharpe
        valid = [
            sr
            for sr in srs
            if not (isinstance(sr.sharpe_mean, float) and math.isnan(sr.sharpe_mean))
        ]
        if not valid:
            continue

        best = max(valid, key=lambda x: x.sharpe_mean)
        sharpe = best.sharpe_mean
        max_dd = best.max_drawdown_worst
        psr = best.psr
        dsr = best.dsr

        # V1 gate check
        passes_sharpe = sharpe >= V1_SHARPE_GATE
        passes_dd = abs(max_dd) <= V1_MAX_DD_GATE
        gate = "PASS" if (passes_sharpe and passes_dd) else "FAIL"

        psr_str = (
            f"{psr:.3f}"
            if not (isinstance(psr, float) and math.isnan(psr))
            else "  NaN"
        )
        dsr_str = (
            f"{dsr:.3f}"
            if not (isinstance(dsr, float) and math.isnan(dsr))
            else "  NaN"
        )

        print(
            f"{strategy_name:<20} {cv_method:<16} {asset_id:>7} "
            f"{sharpe:>8.3f} {max_dd:>8.3f} {psr_str:>6} {dsr_str:>6} {gate:>6}"
        )

    # V1 gate summary
    print()
    passed = []
    for (strategy_name, cv_method, asset_id), srs in by_strategy_cv.items():
        if cv_method != "purged_kfold":
            continue
        valid = [
            sr
            for sr in srs
            if not (isinstance(sr.sharpe_mean, float) and math.isnan(sr.sharpe_mean))
        ]
        if not valid:
            continue
        best = max(valid, key=lambda x: x.sharpe_mean)
        if (
            best.sharpe_mean >= V1_SHARPE_GATE
            and abs(best.max_drawdown_worst) <= V1_MAX_DD_GATE
        ):
            passed.append((strategy_name, asset_id, best.sharpe_mean))

    print(f"V1 Gate (Sharpe >= {V1_SHARPE_GATE}, MaxDD <= {V1_MAX_DD_GATE:.0%}):")
    if passed:
        for strategy_name, asset_id, sharpe in sorted(passed, key=lambda x: -x[2]):
            print(f"  PASS: {strategy_name} (asset_id={asset_id}, sharpe={sharpe:.3f})")
    else:
        print("  No strategies passed V1 gate on purged_kfold OOS metrics.")
        print("  Consider ensemble/blending of top signals (per CONTEXT.md).")

    print()


def _get_asset_ids_from_db(engine, tf: str) -> List[int]:
    """Discover all asset IDs that have features data for the given TF."""
    sql = text(
        """
        SELECT DISTINCT id FROM public.features
        WHERE tf = :tf
        ORDER BY id
        """
    )
    with engine.connect() as conn:
        result = conn.execute(sql, {"tf": tf})
        return [row[0] for row in result.fetchall()]


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run walk-forward strategy bake-off with purged K-fold CV and CPCV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Data selection
    parser.add_argument(
        "--assets",
        nargs="+",
        type=int,
        default=None,
        help="Asset IDs to evaluate. Default: BTC (1) and ETH (1027).",
    )
    parser.add_argument(
        "--all-assets",
        action="store_true",
        help="Run on all assets with features data for the given TF.",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe to evaluate (default: 1D).",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=None,
        help="Strategy names to run. Default: all available (ema_trend, rsi_mean_revert, breakout_atr).",
    )

    # CV configuration
    parser.add_argument(
        "--n-folds",
        type=int,
        default=10,
        help="Number of K-fold splits (default: 10).",
    )
    parser.add_argument(
        "--embargo-bars",
        type=int,
        default=20,
        help="Embargo bars between train/test (default: 20).",
    )

    # Cost matrix
    parser.add_argument(
        "--spot-only",
        action="store_true",
        help="Run only spot cost scenarios (6 instead of 12). Overridden by --exchange.",
    )
    parser.add_argument(
        "--exchange",
        default="kraken",
        choices=["kraken", "hyperliquid", "all"],
        help=(
            "Cost matrix exchange (default: kraken). "
            "'hyperliquid' uses 6 tighter HL scenarios. "
            "'all' runs both Kraken (12) and Hyperliquid (6) = 18 total scenarios."
        ),
    )

    # Expression engine experiments
    parser.add_argument(
        "--experiments-yaml",
        default=None,
        metavar="PATH",
        help=(
            "Path to YAML experiments file with expression engine signal definitions "
            "(e.g. configs/experiments/signals_phase82.yaml). "
            "Each experiment is added to the strategies dict under its YAML name."
        ),
    )
    parser.add_argument(
        "--experiment-name",
        default=None,
        metavar="NAME",
        help=(
            "Experiment lineage tag stored in strategy_bakeoff_results.experiment_name "
            "(e.g. 'phase82-ama-v1'). All results from this run get this tag."
        ),
    )

    # Run control
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List planned combinations without computing.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing results in strategy_bakeoff_results.",
    )

    # Logging
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Engine
    if not TARGET_DB_URL:
        print(
            "ERROR: TARGET_DB_URL not set. Check db_config.env or environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    # Resolve asset IDs
    if args.all_assets:
        asset_ids = _get_asset_ids_from_db(engine, args.tf)
        logger.info(f"Discovered {len(asset_ids)} assets with {args.tf} data")
    elif args.assets:
        asset_ids = args.assets
    else:
        asset_ids = [1, 1027]  # BTC, ETH
        logger.info(f"Using default assets: {asset_ids} (BTC, ETH)")

    if not asset_ids:
        print(f"ERROR: No assets found for tf={args.tf}.", file=sys.stderr)
        sys.exit(1)

    # Build strategies (includes YAML experiments if --experiments-yaml provided)
    strategies = _build_strategies(
        strategy_names=args.strategies,
        experiments_yaml=args.experiments_yaml,
    )
    if not strategies:
        print("ERROR: No strategies available to run.", file=sys.stderr)
        sys.exit(1)

    logger.info(f"Strategies: {list(strategies.keys())}")
    logger.info(f"Assets: {asset_ids}")
    logger.info(f"Timeframe: {args.tf}")

    # Resolve cost matrix from --exchange flag
    # 'all' concatenates both Kraken and Hyperliquid matrices
    if args.exchange == "all":
        combined_matrix = list(COST_MATRIX_REGISTRY["kraken"]) + list(
            COST_MATRIX_REGISTRY["hyperliquid"]
        )
        logger.info(
            f"Exchange=all: using {len(combined_matrix)} cost scenarios "
            f"({len(COST_MATRIX_REGISTRY['kraken'])} Kraken + "
            f"{len(COST_MATRIX_REGISTRY['hyperliquid'])} Hyperliquid)"
        )
    else:
        combined_matrix = list(COST_MATRIX_REGISTRY[args.exchange])
        logger.info(
            f"Exchange={args.exchange}: using {len(combined_matrix)} cost scenarios"
        )

    # Build config
    config = BakeoffConfig(
        n_folds=args.n_folds,
        embargo_bars=args.embargo_bars,
        cost_matrix=combined_matrix,
        spot_only=args.spot_only,
        exchange=args.exchange,
        overwrite=args.overwrite,
    )

    # Detect whether AMA data loader is needed:
    # Required when any AMA strategy is requested OR experiments-yaml is provided
    # (expression engine experiments use AMA columns from load_strategy_data_with_ama)
    requested_strategy_names = set(strategies.keys())
    needs_ama = bool(
        requested_strategy_names & _AMA_STRATEGY_NAMES or args.experiments_yaml
    )

    ama_features: Optional[List[Dict[str, Any]]] = None
    if needs_ama:
        ama_features = parse_active_features()
        logger.info(
            f"AMA data loader enabled: {len(ama_features)} active features "
            f"(AMA strategies or expression experiments detected)"
        )

    # Dry run
    if args.dry_run:
        _print_dry_run(strategies, asset_ids, args.tf, config)
        return

    # Run bake-off
    logger.info("Starting bake-off execution...")
    orchestrator = BakeoffOrchestrator(engine=engine, config=config)

    results = orchestrator.run(
        strategies=strategies,
        asset_ids=asset_ids,
        tf=args.tf,
        ama_features=ama_features,
        experiment_name=args.experiment_name,
    )

    logger.info(f"Bake-off complete: {len(results)} result rows generated")

    # Print summary
    _print_summary(results)

    # Final DB verification
    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM public.strategy_bakeoff_results WHERE tf = :tf",
            ),
            {"tf": args.tf},
        ).scalar()
    logger.info(f"strategy_bakeoff_results now has {count} rows for tf={args.tf}")


if __name__ == "__main__":
    main()
