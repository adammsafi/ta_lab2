"""
Resume-safe mass backtest orchestrator.

Wraps BakeoffOrchestrator with mass_backtest_state table for tracking
completion of each (strategy, asset, params_hash, tf, cost_bps) combination.
Uses expanded grids from configs/mass_backtest_grids.yaml.

Usage:
    # Dry run: show planned combinations
    python -m ta_lab2.scripts.backtests.run_mass_backtest --dry-run

    # Full run with 4 workers
    python -m ta_lab2.scripts.backtests.run_mass_backtest --workers 4

    # Resume interrupted run (skip completed rows)
    python -m ta_lab2.scripts.backtests.run_mass_backtest --resume --workers 4

    # Run specific strategies only
    python -m ta_lab2.scripts.backtests.run_mass_backtest --strategies ema_trend rsi_mean_revert

    # CTF threshold strategies only (uses CTF data loader)
    python -m ta_lab2.scripts.backtests.run_mass_backtest --strategies ctf_threshold

    # All assets discovered from features table
    python -m ta_lab2.scripts.backtests.run_mass_backtest --all-assets --workers 4

    # Specific exchange cost matrix
    python -m ta_lab2.scripts.backtests.run_mass_backtest --exchange all --workers 4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from functools import partial
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from sqlalchemy import NullPool, create_engine, text

from ta_lab2.backtests.bakeoff_orchestrator import (
    BakeoffConfig,
    BakeoffOrchestrator,
    load_strategy_data_with_ctf,
    parse_active_features,
)
from ta_lab2.backtests.costs import COST_MATRIX_REGISTRY
from ta_lab2.config import TARGET_DB_URL
from ta_lab2.signals.registry import get_strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AMA strategy names (require AMA data loader)
# ---------------------------------------------------------------------------

_AMA_STRATEGY_NAMES: frozenset[str] = frozenset(
    {"ama_momentum", "ama_mean_reversion", "ama_regime_conditional"}
)

# CTF strategy names (require CTF data loader)
_CTF_STRATEGY_NAMES: frozenset[str] = frozenset({"ctf_threshold"})


# ---------------------------------------------------------------------------
# Grid loading
# ---------------------------------------------------------------------------


def _load_mass_grids(
    yaml_path: str = "configs/mass_backtest_grids.yaml",
) -> Dict[str, List[Dict[str, Any]]]:
    """Load expanded param grids from YAML.

    Returns dict: strategy_name -> list of param dicts.
    """
    import os

    if not os.path.isabs(yaml_path):
        candidate = yaml_path
        if not os.path.exists(candidate):
            cwd = os.getcwd()
            parts = cwd.replace("\\", "/").split("/")
            for i in range(len(parts), 0, -1):
                root = "/".join(parts[:i])
                candidate = os.path.join(root, yaml_path)
                if os.path.exists(candidate):
                    break
            else:
                candidate = yaml_path

    with open(candidate, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    grids: Dict[str, List[Dict[str, Any]]] = {}
    for strategy_name, strategy_cfg in data.items():
        if isinstance(strategy_cfg, dict) and "params" in strategy_cfg:
            grids[strategy_name] = strategy_cfg["params"]
        else:
            logger.warning(
                f"_load_mass_grids: skipping '{strategy_name}' (no 'params' key)"
            )

    return grids


# ---------------------------------------------------------------------------
# Params hash
# ---------------------------------------------------------------------------


def compute_params_hash(params: dict) -> str:
    """Compute stable 16-char hex hash of sorted params JSON."""
    return hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# State table helpers
# ---------------------------------------------------------------------------


def _load_completed_keys(engine: Any) -> Set[Tuple]:
    """Load all (strategy_name, asset_id, params_hash, tf, cost_bps) tuples with status='done'."""
    sql = text(
        """
        SELECT strategy_name, asset_id, params_hash, tf, cost_bps
        FROM public.mass_backtest_state
        WHERE status = 'done'
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return {(r[0], int(r[1]), r[2], r[3], float(r[4])) for r in rows}


def _mark_running(engine: Any, key_tuple: Tuple) -> None:
    """Upsert (strategy_name, asset_id, params_hash, tf, cost_bps) with status='running'."""
    strategy_name, asset_id, params_hash, tf, cost_bps = key_tuple
    sql = text(
        """
        INSERT INTO public.mass_backtest_state (
            strategy_name, asset_id, params_hash, tf, cost_bps,
            status, started_at
        )
        VALUES (
            :strategy_name, :asset_id, :params_hash, :tf, :cost_bps,
            'running', now()
        )
        ON CONFLICT (strategy_name, asset_id, params_hash, tf, cost_bps)
        DO UPDATE SET
            status = 'running',
            started_at = now(),
            error_msg = NULL
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "strategy_name": strategy_name,
                "asset_id": asset_id,
                "params_hash": params_hash,
                "tf": tf,
                "cost_bps": cost_bps,
            },
        )


def _mark_done(engine: Any, key_tuple: Tuple) -> None:
    """UPDATE status='done', completed_at=now() for the given key."""
    strategy_name, asset_id, params_hash, tf, cost_bps = key_tuple
    sql = text(
        """
        UPDATE public.mass_backtest_state
        SET status = 'done', completed_at = now()
        WHERE strategy_name = :strategy_name
          AND asset_id = :asset_id
          AND params_hash = :params_hash
          AND tf = :tf
          AND cost_bps = :cost_bps
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "strategy_name": strategy_name,
                "asset_id": asset_id,
                "params_hash": params_hash,
                "tf": tf,
                "cost_bps": cost_bps,
            },
        )


def _mark_error(engine: Any, key_tuple: Tuple, error_msg: str) -> None:
    """UPDATE status='error', error_msg=msg for the given key."""
    strategy_name, asset_id, params_hash, tf, cost_bps = key_tuple
    sql = text(
        """
        INSERT INTO public.mass_backtest_state (
            strategy_name, asset_id, params_hash, tf, cost_bps,
            status, started_at, error_msg
        )
        VALUES (
            :strategy_name, :asset_id, :params_hash, :tf, :cost_bps,
            'error', now(), :error_msg
        )
        ON CONFLICT (strategy_name, asset_id, params_hash, tf, cost_bps)
        DO UPDATE SET
            status = 'error',
            error_msg = :error_msg,
            completed_at = now()
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "strategy_name": strategy_name,
                "asset_id": asset_id,
                "params_hash": params_hash,
                "tf": tf,
                "cost_bps": cost_bps,
                "error_msg": error_msg[:2000],  # truncate to fit TEXT
            },
        )


# ---------------------------------------------------------------------------
# Asset discovery
# ---------------------------------------------------------------------------


def _get_asset_ids_from_db(engine: Any, tf: str) -> List[int]:
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


# ---------------------------------------------------------------------------
# Dry-run display
# ---------------------------------------------------------------------------


def _print_dry_run(
    strategies: Dict[str, List[Dict[str, Any]]],
    asset_ids: List[int],
    tf: str,
    cost_matrix_len: int,
    n_cv_methods: int = 2,
    completed_keys: Optional[Set[Tuple]] = None,
) -> None:
    """Print dry-run summary of planned combinations."""
    print("\n=== DRY RUN: Mass Backtest Combinations ===\n")
    print(
        f"Assets: {len(asset_ids)} ({asset_ids[:5]}{'...' if len(asset_ids) > 5 else ''})"
    )
    print(f"Timeframe: {tf}")
    print(f"Cost scenarios: {cost_matrix_len}")
    print(f"CV methods: {n_cv_methods} (purged_kfold + cpcv)")
    print()

    total = 0
    for strategy_name, param_grid in strategies.items():
        n_combos = len(param_grid) * len(asset_ids) * cost_matrix_len * n_cv_methods
        total += n_combos

        # Count skipped if resume mode
        n_skip = 0
        if completed_keys:
            for params in param_grid:
                ph = compute_params_hash(params)
                # Approximate: count by params_hash + strategy, ignore per-cost
                for aid in asset_ids:
                    for cost_bps in [0.0]:  # placeholder for dry-run skip estimate
                        key = (strategy_name, aid, ph, tf, cost_bps)
                        if key in completed_keys:
                            n_skip += cost_matrix_len * n_cv_methods

        loader_note = ""
        if strategy_name in _CTF_STRATEGY_NAMES:
            ctf_cols = list({p.get("feature_col", "") for p in param_grid})
            loader_note = f" [CTF loader: {ctf_cols}]"
        elif strategy_name in _AMA_STRATEGY_NAMES:
            loader_note = " [AMA loader]"

        print(
            f"Strategy '{strategy_name}': {len(param_grid)} params x {len(asset_ids)} assets "
            f"x {cost_matrix_len} costs x {n_cv_methods} CV = {n_combos} runs{loader_note}"
        )
        for i, params in enumerate(param_grid[:3]):
            param_str = ", ".join(f"{k}={v}" for k, v in list(params.items())[:4])
            print(f"  Params[{i}]: {param_str}{'...' if len(params) > 4 else ''}")
        if len(param_grid) > 3:
            print(f"  ... ({len(param_grid) - 3} more param sets)")

    print(f"\nTotal: {total} result rows planned")
    if completed_keys:
        print(
            f"Note: Resume mode enabled. {len(completed_keys)} state rows already done."
        )
    print()

    # Rough time estimate
    secs_per_fold = 3
    n_folds_total = 10 + 45  # pkf folds + cpcv combos
    total_secs = (
        sum(len(grid) for grid in strategies.values())
        * len(asset_ids)
        * cost_matrix_len
        * n_folds_total
        * secs_per_fold
    )
    print(
        f"Estimated runtime: ~{total_secs / 60:.0f} min ({total_secs / 3600:.1f} hours)"
    )
    print()


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _run_mass_backtest(engine: Any, args: Any) -> None:
    """
    Orchestrate mass backtesting with resume-safe state tracking.

    Iterates over strategies from the YAML grid. For each strategy x asset pair:
    - Checks mass_backtest_state for completed combinations (if --resume)
    - Calls BakeoffOrchestrator.run() with appropriate data loader
    - Marks combinations done/error in mass_backtest_state

    DSR limitation note: At 460K+ runs, DSR deflation benchmark is very high
    (inflated N makes E[max SR] converge to unreasonable values). Per-asset-group
    DSR computed by BakeoffOrchestrator is still meaningful within each (strategy,
    asset, cost) group.
    """
    logger.warning(
        "DSR computation is limited at scale (>1000 runs per group). "
        "DSR values may be inflated for large mass runs. "
        "See Phase 99 research notes (Pitfall 1)."
    )

    # --- Load YAML grids ---
    all_grids = _load_mass_grids(args.grids_yaml)
    if not all_grids:
        print("ERROR: No grids loaded from YAML.", file=sys.stderr)
        sys.exit(1)

    # --- Filter to requested strategies ---
    if args.strategies:
        grids = {k: v for k, v in all_grids.items() if k in args.strategies}
        missing = set(args.strategies) - set(grids)
        if missing:
            logger.warning(f"Strategies not found in YAML: {missing}")
    else:
        grids = all_grids

    if not grids:
        print(
            f"ERROR: No strategies available after filtering. "
            f"Check --strategies and {args.grids_yaml}",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Resolve asset IDs ---
    if args.all_assets:
        asset_ids = _get_asset_ids_from_db(engine, args.tf)
        logger.info(f"Discovered {len(asset_ids)} assets with {args.tf} features data")
    elif args.assets:
        asset_ids = args.assets
    else:
        asset_ids = [1, 1027]
        logger.info(f"Using default assets: {asset_ids} (BTC, ETH)")

    if not asset_ids:
        print(f"ERROR: No assets found for tf={args.tf}.", file=sys.stderr)
        sys.exit(1)

    # --- Resolve cost matrix ---
    exchange = args.exchange.lower()
    if exchange == "all":
        combined_matrix = list(COST_MATRIX_REGISTRY["kraken"]) + list(
            COST_MATRIX_REGISTRY["hyperliquid"]
        )
        logger.info(
            f"Exchange=all: {len(combined_matrix)} cost scenarios "
            f"({len(COST_MATRIX_REGISTRY['kraken'])} Kraken + "
            f"{len(COST_MATRIX_REGISTRY['hyperliquid'])} Hyperliquid)"
        )
    else:
        if exchange not in COST_MATRIX_REGISTRY:
            print(
                f"ERROR: Exchange '{exchange}' not in COST_MATRIX_REGISTRY. "
                f"Available: {list(COST_MATRIX_REGISTRY.keys())}",
                file=sys.stderr,
            )
            sys.exit(1)
        combined_matrix = list(COST_MATRIX_REGISTRY[exchange])
        logger.info(f"Exchange={exchange}: {len(combined_matrix)} cost scenarios")

    # --- Load completed keys for resume ---
    completed_keys: Set[Tuple] = set()
    if args.resume:
        completed_keys = _load_completed_keys(engine)
        logger.info(f"Resume mode: {len(completed_keys)} combinations already done")

    # --- Dry run ---
    if args.dry_run:
        _print_dry_run(
            grids,
            asset_ids,
            args.tf,
            cost_matrix_len=len(combined_matrix),
            completed_keys=completed_keys if args.resume else None,
        )
        return

    # --- Pre-load AMA features once (reused across all AMA strategies) ---
    ama_features = None
    if any(s in _AMA_STRATEGY_NAMES for s in grids):
        ama_features = parse_active_features()
        logger.info(f"AMA data loader enabled: {len(ama_features)} active features")

    # --- Build BakeoffConfig ---
    config = BakeoffConfig(
        cost_matrix=combined_matrix,
        exchange=exchange if exchange != "all" else "kraken",  # registry key for label
        overwrite=args.overwrite,
        cpcv_top_n=args.cpcv_top_n,
    )

    # --- Iterate strategies ---
    total_results = 0
    total_strategies_run = 0

    for strategy_name, param_grid in grids.items():
        logger.info(
            f"--- Strategy '{strategy_name}': {len(param_grid)} params, "
            f"{len(asset_ids)} assets ---"
        )

        # Get signal function from registry
        try:
            signal_fn = get_strategy(strategy_name)
        except KeyError:
            logger.warning(f"Strategy '{strategy_name}' not in registry; skipping")
            continue

        # Determine data loader for this strategy
        is_ctf = strategy_name in _CTF_STRATEGY_NAMES
        is_ama = strategy_name in _AMA_STRATEGY_NAMES

        data_loader_fn = None
        data_loader_type = None
        data_loader_kwargs = None
        strategy_ama_features = None

        if is_ctf:
            # Extract unique CTF feature columns from param grid
            ctf_cols = list(
                {p["feature_col"] for p in param_grid if "feature_col" in p}
            )
            logger.info(f"CTF strategy detected. Feature columns: {ctf_cols}")
            data_loader_fn = partial(load_strategy_data_with_ctf, ctf_cols=ctf_cols)
            # Serializable form for parallel workers
            data_loader_type = "ctf"
            data_loader_kwargs = {"ctf_cols": ctf_cols}
        elif is_ama:
            strategy_ama_features = ama_features

        # Build orchestrator
        orchestrator = BakeoffOrchestrator(engine=engine, config=config)

        # Iterate assets (mark state per asset)
        strategy_results = 0
        for asset_id in asset_ids:
            # Build state keys for this (strategy, asset) pair: one per param combo
            # We track at the (strategy, asset, params_hash) level in mass_backtest_state.
            # The cost_bps dimension is aggregated into a single run (orchestrator handles all costs).
            # We use cost_bps=0.0 as a sentinel to represent "all costs" for this combo.
            params_hashes = [compute_params_hash(p) for p in param_grid]
            sentinel_cost_bps = 0.0

            # Check if this (strategy, asset) is already fully done
            if args.resume:
                all_done = all(
                    (strategy_name, asset_id, ph, args.tf, sentinel_cost_bps)
                    in completed_keys
                    for ph in params_hashes
                )
                if all_done:
                    logger.info(
                        f"  asset_id={asset_id}: all {len(param_grid)} param combos "
                        f"already done; skipping"
                    )
                    continue

            # Mark all combos as running
            for ph in params_hashes:
                key = (strategy_name, asset_id, ph, args.tf, sentinel_cost_bps)
                try:
                    _mark_running(engine, key)
                except Exception as exc:
                    logger.warning(f"  Failed to mark running for {key}: {exc}")

            # Run backtest for this asset
            try:
                results = orchestrator.run(
                    strategies={strategy_name: (signal_fn, param_grid)},
                    asset_ids=[asset_id],
                    tf=args.tf,
                    ama_features=strategy_ama_features,
                    data_loader_fn=data_loader_fn,
                    data_loader_type=data_loader_type,
                    data_loader_kwargs=data_loader_kwargs,
                    experiment_name=args.experiment_name,
                    workers=args.workers,
                )
                n_results = len(results)
                strategy_results += n_results

                # Mark all combos as done
                for ph in params_hashes:
                    key = (strategy_name, asset_id, ph, args.tf, sentinel_cost_bps)
                    try:
                        _mark_done(engine, key)
                    except Exception as exc:
                        logger.warning(f"  Failed to mark done for {key}: {exc}")

                logger.info(f"  asset_id={asset_id}: {n_results} results persisted")

            except Exception as exc:
                logger.error(f"  asset_id={asset_id}: backtest failed: {exc}")
                for ph in params_hashes:
                    key = (strategy_name, asset_id, ph, args.tf, sentinel_cost_bps)
                    try:
                        _mark_error(engine, key, str(exc))
                    except Exception as mark_exc:
                        logger.warning(f"  Failed to mark error for {key}: {mark_exc}")

        logger.info(
            f"[{strategy_name}] Completed: {len(asset_ids)} assets, "
            f"{strategy_results} results persisted"
        )
        total_results += strategy_results
        total_strategies_run += 1

    logger.info(
        f"Mass backtest complete: {total_strategies_run}/{len(grids)} strategies run, "
        f"{total_results} total results persisted"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Resume-safe mass backtest orchestrator with state tracking.",
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
        help=(
            "Strategy names to run (must exist in --grids-yaml). "
            "Default: all strategies in the YAML."
        ),
    )

    # Resume / state
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Skip combinations with status='done' in mass_backtest_state. "
            "Use to resume an interrupted run without re-computing."
        ),
    )

    # Grid config
    parser.add_argument(
        "--grids-yaml",
        default="configs/mass_backtest_grids.yaml",
        metavar="PATH",
        help="Path to YAML param grids file (default: configs/mass_backtest_grids.yaml).",
    )

    # Cost matrix
    parser.add_argument(
        "--exchange",
        default="all",
        choices=["kraken", "hyperliquid", "lean", "all"],
        help=(
            "Cost matrix exchange (default: all). "
            "'kraken' uses 12 Kraken scenarios. "
            "'hyperliquid' uses 6 HL scenarios. "
            "'lean' uses 3 representative costs (fast screening). "
            "'all' runs both kraken+hyperliquid (18 total)."
        ),
    )

    # Experiment lineage
    parser.add_argument(
        "--experiment-name",
        default="phase99-mass-v1",
        metavar="NAME",
        help=(
            "Experiment lineage tag stored in strategy_bakeoff_results.experiment_name. "
            "Default: 'phase99-mass-v1'."
        ),
    )

    # CPCV control
    parser.add_argument(
        "--cpcv-top-n",
        type=int,
        default=3,
        help=(
            "Run CPCV only on top N param sets by PKF Sharpe "
            "(0=all, -1=skip CPCV, default=3)."
        ),
    )

    # Overwrite
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing results in strategy_bakeoff_results.",
    )

    # Performance
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel worker processes (default: 1 = sequential). "
        "Each worker creates its own DB connection via NullPool. "
        "Use maxtasksperchild=1 (built into BakeoffOrchestrator for Windows safety).",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned combination counts and exit without running.",
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

    _run_mass_backtest(engine, args)


if __name__ == "__main__":
    main()
