# -*- coding: utf-8 -*-
"""
CLI runner for Phase 105 parameter sweeps.

Discovers FDR-surviving indicators from dim_feature_registry (Phases 103-104),
maps each to its parameter space definition, runs IC-based Optuna sweeps,
and persists results to trial_registry.

Usage::

    # Dry run: list parameter spaces without sweeping
    python -m ta_lab2.scripts.analysis.run_param_sweep --dry-run --tf 1D

    # Sweep a single indicator for a single asset
    python -m ta_lab2.scripts.analysis.run_param_sweep --indicator rsi --asset-id 1 --tf 1D

    # Sweep all FDR survivors for asset 1
    python -m ta_lab2.scripts.analysis.run_param_sweep --asset-id 1 --tf 1D

    # Full sweep: all survivors, top-20 IC assets, 100 TPE trials
    python -m ta_lab2.scripts.analysis.run_param_sweep --tf 1D --tpe-trials 100

    # Quick exploration: skip stability and DSR
    python -m ta_lab2.scripts.analysis.run_param_sweep --indicator cci --asset-id 1 --skip-stability --skip-dsr

Design notes:
- PARAM_SPACE_REGISTRY maps indicator name -> feature_fn_path + param_space_def + constraints
- Parameter names are matched to ACTUAL function signatures (indicators.py / indicators_extended.py).
- Phase 104 crypto-native indicators require 'oi', 'funding_rate' columns; guarded with ImportError catch.
- DB engine uses NullPool (project convention for scripts).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import time
from math import prod
from typing import Any, Callable, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.param_optimizer import run_sweep, select_best_from_sweep
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter Space Registry
# ---------------------------------------------------------------------------
# Each entry maps indicator_name -> dict with:
#   feature_fn_path: dotted import path to the indicator function
#   param_space_def: list of param spec dicts for run_sweep/_suggest_params
#   constraints:     optional list of constraint strings (informational -- not
#                    enforced by Optuna; use TrialPruned in feature_fn if needed)
#
# Parameter names MUST match actual function keyword argument names.
# Verified against indicators.py, indicators_extended.py, indicators_derivatives.py
# ---------------------------------------------------------------------------

PARAM_SPACE_REGISTRY: dict[str, dict[str, Any]] = {
    # -----------------------------------------------------------------------
    # Phase 103: Traditional TA (indicators.py)
    # -----------------------------------------------------------------------
    # rsi(obj, window=14, ...) -- 'window' is the param name
    "rsi": {
        "feature_fn_path": "ta_lab2.features.indicators.rsi",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 5, "high": 30},
        ],
        "constraints": [],
    },
    # macd(obj, *, fast=12, slow=26, signal=9, ...)
    "macd": {
        "feature_fn_path": "ta_lab2.features.indicators.macd",
        "param_space_def": [
            {"name": "fast", "type": "int", "low": 2, "high": 15},
            {"name": "slow", "type": "int", "low": 10, "high": 50},
            {"name": "signal", "type": "int", "low": 3, "high": 12},
        ],
        "constraints": ["fast < slow"],
    },
    # stoch_kd(obj, *, k=14, d=3, ...) -- params are 'k' and 'd'
    "stochastic": {
        "feature_fn_path": "ta_lab2.features.indicators.stoch_kd",
        "param_space_def": [
            {"name": "k", "type": "int", "low": 5, "high": 25},
            {"name": "d", "type": "int", "low": 2, "high": 6},
        ],
        "constraints": [],
    },
    # bollinger(obj, window=20, *, n_sigma=2.0, ...) -- 'window' and 'n_sigma'
    "bbands": {
        "feature_fn_path": "ta_lab2.features.indicators.bollinger",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 5, "high": 50},
            {"name": "n_sigma", "type": "float", "low": 1.0, "high": 3.0, "step": 0.25},
        ],
        "constraints": [],
    },
    # atr(obj, window=14, ...) -- 'window' is the param name
    "atr": {
        "feature_fn_path": "ta_lab2.features.indicators.atr",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 5, "high": 28},
        ],
        "constraints": [],
    },
    # adx(obj, window=14, ...) -- 'window' is the param name
    "adx": {
        "feature_fn_path": "ta_lab2.features.indicators.adx",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 7, "high": 28},
        ],
        "constraints": [],
    },
    # mfi(obj, window=14, ...) -- 'window' is the param name
    "mfi": {
        "feature_fn_path": "ta_lab2.features.indicators.mfi",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 7, "high": 28},
        ],
        "constraints": [],
    },
    # -----------------------------------------------------------------------
    # Phase 103: Traditional TA (indicators_extended.py)
    # -----------------------------------------------------------------------
    # williams_r(obj, window=14, ...) -- 'window' is the param name
    "williams_pct_r": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.williams_r",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 7, "high": 28},
        ],
        "constraints": [],
    },
    # cci(obj, window=20, ...) -- 'window' is the param name
    "cci": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.cci",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 10, "high": 30, "step": 2},
        ],
        "constraints": [],
    },
    # elder_ray(obj, *, period=13, ...) -- 'period' is the param name
    "elder_ray": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.elder_ray",
        "param_space_def": [
            {"name": "period", "type": "int", "low": 8, "high": 21},
        ],
        "constraints": [],
    },
    # force_index(obj, *, smooth=13, ...) -- 'smooth' is the param name
    "force_index": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.force_index",
        "param_space_def": [
            {"name": "smooth", "type": "int", "low": 5, "high": 20},
        ],
        "constraints": [],
    },
    # vwap(obj, window=14, ...) -- 'window' is the param name
    "vwap_ratio": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.vwap",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 7, "high": 28},
        ],
        "constraints": [],
    },
    # cmf(obj, window=20, ...) -- 'window' is the param name
    "cmf": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.cmf",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 10, "high": 30, "step": 2},
        ],
        "constraints": [],
    },
    # chaikin_osc(obj, *, fast=3, slow=10, ...) -- 'fast' and 'slow'
    "chaikin_oscillator": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.chaikin_osc",
        "param_space_def": [
            {"name": "fast", "type": "int", "low": 3, "high": 6},
            {"name": "slow", "type": "int", "low": 8, "high": 15},
        ],
        "constraints": ["fast < slow"],
    },
    # hurst(obj, window=100, ...) -- 'window' is the param name
    "hurst": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.hurst",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 60, "high": 150, "step": 10},
        ],
        "constraints": [],
    },
    # vidya(obj, *, cmo_period=9, vidya_period=9, ...) -- both are params
    "vidya": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.vidya",
        "param_space_def": [
            {"name": "cmo_period", "type": "int", "low": 5, "high": 20},
            {"name": "vidya_period", "type": "int", "low": 5, "high": 20},
        ],
        "constraints": [],
    },
    # frama(obj, *, period=16, ...) -- 'period' is the param name (must be even)
    "frama": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.frama",
        "param_space_def": [
            {"name": "period", "type": "int", "low": 8, "high": 26, "step": 2},
        ],
        "constraints": [],
    },
    # keltner(obj, *, ema_period=20, atr_period=10, ...) -- both are params
    "keltner_channel": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.keltner",
        "param_space_def": [
            {"name": "ema_period", "type": "int", "low": 10, "high": 30},
            {"name": "atr_period", "type": "int", "low": 5, "high": 20},
        ],
        "constraints": [],
    },
    # ichimoku(obj, *, tenkan=9, kijun=26, senkou_b=52, ...)
    "ichimoku": {
        "feature_fn_path": "ta_lab2.features.indicators_extended.ichimoku",
        "param_space_def": [
            {"name": "tenkan", "type": "int", "low": 6, "high": 15},
            {"name": "kijun", "type": "int", "low": 18, "high": 35},
            {"name": "senkou_b", "type": "int", "low": 42, "high": 62},
        ],
        "constraints": ["tenkan < kijun", "kijun < senkou_b"],
    },
    # -----------------------------------------------------------------------
    # Phase 104: Crypto-Native Indicators (indicators_derivatives.py)
    # These require 'oi', 'funding_rate' columns. Guarded via ImportError.
    # -----------------------------------------------------------------------
    # vol_oi_regime(df, ...) -- no window param (instantaneous classification)
    # Placeholder: window param controls oi_zscore pre-computation step
    "volume_oi_regime": {
        "feature_fn_path": "ta_lab2.features.indicators_derivatives.vol_oi_regime",
        "param_space_def": [
            # vol_oi_regime has no tunable window; include oi_momentum window
            # as a proxy (used to pre-smooth OI before regime classification).
            # NOTE: vol_oi_regime itself is windowless -- this entry is a
            # placeholder for the sweep runner to register the indicator.
            # The actual param is passed to the wrapper in _make_feature_fn.
        ],
        "constraints": [],
        "_crypto_native": True,  # Requires oi, funding_rate columns
    },
    # funding_zscore(df, window=14, ...) -- 'window' is the param name
    "oi_zscore": {
        "feature_fn_path": "ta_lab2.features.indicators_derivatives.funding_zscore",
        "param_space_def": [
            {"name": "window", "type": "int", "low": 10, "high": 50, "step": 5},
        ],
        "constraints": [],
        "_crypto_native": True,
    },
    # liquidation_pressure(df, ...) -- composite, no window param
    # Registered for tracking; requires pre-computed component columns.
    "liquidation_pressure": {
        "feature_fn_path": "ta_lab2.features.indicators_derivatives.liquidation_pressure",
        "param_space_def": [],
        "constraints": [],
        "_crypto_native": True,
    },
}


# ---------------------------------------------------------------------------
# Helper: compute grid size for display in dry-run
# ---------------------------------------------------------------------------


def _grid_size(param_space_def: list[dict]) -> int:
    """Cartesian product of all param range sizes."""
    sizes = []
    for spec in param_space_def:
        ptype = spec["type"]
        low = spec["low"]
        high = spec["high"]
        if ptype == "int":
            step = spec.get("step", 1)
            sizes.append(max(1, (int(high) - int(low)) // int(step) + 1))
        elif ptype == "float":
            step = spec.get("step")
            if step and step > 0:
                sizes.append(int(round((float(high) - float(low)) / float(step))) + 1)
            else:
                sizes.append(1)
        else:
            sizes.append(1)
    return prod(sizes) if sizes else 1


def _sampler_type(grid_size: int, threshold: int = 200) -> str:
    return "Grid" if grid_size <= threshold else "TPE"


# ---------------------------------------------------------------------------
# _resolve_feature_fn
# ---------------------------------------------------------------------------


def _resolve_feature_fn(fn_path: str) -> Optional[Callable]:
    """
    Import and return the callable at *fn_path* (dotted module.attribute path).

    Returns None (with a warning log) if the import fails (e.g., missing
    dependency for Phase 104 crypto-native indicators).
    """
    parts = fn_path.rsplit(".", 1)
    if len(parts) != 2:
        logger.warning("_resolve_feature_fn: invalid fn_path '%s' (no dot)", fn_path)
        return None

    module_path, fn_name = parts
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        logger.warning(
            "_resolve_feature_fn: ImportError for module '%s': %s -- skipping indicator",
            module_path,
            exc,
        )
        return None

    fn = getattr(mod, fn_name, None)
    if fn is None:
        logger.warning(
            "_resolve_feature_fn: '%s' not found in module '%s'", fn_name, module_path
        )
        return None

    return fn


# ---------------------------------------------------------------------------
# _load_survivors
# ---------------------------------------------------------------------------


def _load_survivors(
    conn: Any, source_phases: tuple[str, ...] = ("103", "104")
) -> list[str]:
    """
    Query dim_feature_registry for FDR-surviving indicators from Phases 103-104.

    Falls back gracefully if:
    - dim_feature_registry doesn't exist
    - no FDR survivors exist yet

    Returns list of indicator names (strings).
    """
    # Try dim_feature_registry first
    try:
        rows = conn.execute(
            text("""
            SELECT DISTINCT indicator_name
            FROM public.dim_feature_registry
            WHERE lifecycle = 'promoted'
              AND source_phase IN :phases
            ORDER BY indicator_name
            """),
            {"phases": source_phases},
        ).fetchall()
        if rows:
            names = [r[0] for r in rows]
            logger.info(
                "_load_survivors: found %d FDR survivors in dim_feature_registry",
                len(names),
            )
            return names
        logger.info(
            "_load_survivors: dim_feature_registry has no promoted rows for phases %s",
            source_phases,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_load_survivors: dim_feature_registry query failed (%s) -- trying ic_results fallback",
            exc,
        )

    # Fallback: distinct indicator names from trial_registry (any Phase 103/104 sweep)
    try:
        rows = conn.execute(
            text("""
            SELECT DISTINCT indicator_name
            FROM public.trial_registry
            ORDER BY indicator_name
            """)
        ).fetchall()
        if rows:
            names = [r[0] for r in rows]
            logger.info(
                "_load_survivors: trial_registry fallback found %d indicators",
                len(names),
            )
            return names
    except Exception as exc2:  # noqa: BLE001
        logger.warning(
            "_load_survivors: trial_registry fallback also failed (%s)", exc2
        )

    logger.info("_load_survivors: no survivors found in any table")
    return []


# ---------------------------------------------------------------------------
# _load_data_for_asset
# ---------------------------------------------------------------------------


def _load_data_for_asset(
    conn: Any,
    asset_id: int,
    tf: str,
    venue_id: int = 1,
) -> Optional[dict[str, pd.Series]]:
    """
    Load OHLCV + forward returns for a single asset/tf combination.

    Queries price_bars_multi_tf_u for OHLCV and returns_bars_multi_tf_u for fwd_ret.
    Returns dict with keys: close, high, low, volume, fwd_ret (all pd.Series, UTC-indexed).
    Returns None if insufficient data (< 100 rows).
    """
    try:
        bars_df = pd.read_sql(
            text("""
            SELECT ts, open, high, low, close, volume
            FROM public.price_bars_multi_tf_u
            WHERE id = :asset_id
              AND tf = :tf
              AND venue_id = :venue_id
            ORDER BY ts
            """),
            conn,
            params={"asset_id": asset_id, "tf": tf, "venue_id": venue_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_load_data_for_asset: price_bars query failed for id=%d tf=%s: %s",
            asset_id,
            tf,
            exc,
        )
        return None

    if bars_df.empty or len(bars_df) < 100:
        logger.debug(
            "_load_data_for_asset: insufficient bars for id=%d tf=%s (%d rows)",
            asset_id,
            tf,
            len(bars_df),
        )
        return None

    # Ensure UTC-aware timestamps (project gotcha: load manually + pd.to_datetime(utc=True))
    bars_df["ts"] = pd.to_datetime(bars_df["ts"], utc=True)
    bars_df = bars_df.set_index("ts").sort_index()

    # Load forward returns
    try:
        rets_df = pd.read_sql(
            text("""
            SELECT ts, ret_arith
            FROM public.returns_bars_multi_tf_u
            WHERE id = :asset_id
              AND tf = :tf
              AND venue_id = :venue_id
            ORDER BY ts
            """),
            conn,
            params={"asset_id": asset_id, "tf": tf, "venue_id": venue_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_load_data_for_asset: returns query failed for id=%d tf=%s: %s",
            asset_id,
            tf,
            exc,
        )
        # Fallback: compute from close
        rets_df = pd.DataFrame()

    if not rets_df.empty:
        rets_df["ts"] = pd.to_datetime(rets_df["ts"], utc=True)
        rets_df = rets_df.set_index("ts").sort_index()
        # Forward return = shift(-1): return available at bar T predicts bar T+1
        fwd_ret = rets_df["ret_arith"].shift(-1)
    else:
        # Compute arithmetic return from close as fallback
        close_s = bars_df["close"].astype(float)
        fwd_ret = close_s.pct_change().shift(-1)

    return {
        "close": bars_df["close"].astype(float),
        "high": bars_df["high"].astype(float),
        "low": bars_df["low"].astype(float),
        "volume": bars_df["volume"].astype(float),
        "fwd_ret": fwd_ret,
    }


# ---------------------------------------------------------------------------
# _get_tf_days_nominal
# ---------------------------------------------------------------------------


def _get_tf_days_nominal(conn: Any, tf: str) -> float:
    """
    Look up tf_days_nominal from dim_timeframe for the given tf string.
    Falls back to 1.0 if not found.
    """
    try:
        row = conn.execute(
            text("""
            SELECT tf_days_nominal
            FROM public.dim_timeframe
            WHERE tf = :tf
            LIMIT 1
            """),
            {"tf": tf},
        ).fetchone()
        if row:
            return float(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_get_tf_days_nominal: query failed (%s) -- defaulting to 1.0", exc
        )
    return 1.0


# ---------------------------------------------------------------------------
# _query_asset_ids
# ---------------------------------------------------------------------------


def _query_asset_ids(conn: Any, tf: str, limit: int = 20) -> list[int]:
    """
    Query top assets by IC data availability from ic_results.
    Falls back to price_bars_multi_tf_u if ic_results is empty or missing.
    """
    try:
        rows = conn.execute(
            text("""
            SELECT DISTINCT id
            FROM public.ic_results
            WHERE regime_col = 'all'
              AND tf = :tf
            ORDER BY id
            LIMIT :lim
            """),
            {"tf": tf, "lim": limit},
        ).fetchall()
        if rows:
            return [r[0] for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_query_asset_ids: ic_results query failed (%s) -- fallback", exc
        )

    # Fallback: assets with price data for this tf
    try:
        rows = conn.execute(
            text("""
            SELECT DISTINCT id
            FROM public.price_bars_multi_tf_u
            WHERE tf = :tf
            ORDER BY id
            LIMIT :lim
            """),
            {"tf": tf, "lim": limit},
        ).fetchall()
        return [r[0] for r in rows]
    except Exception as exc2:  # noqa: BLE001
        logger.error("_query_asset_ids: fallback also failed (%s)", exc2)
        return []


# ---------------------------------------------------------------------------
# _print_dry_run_table
# ---------------------------------------------------------------------------


def _print_dry_run_table(indicators: list[str]) -> None:
    """Print a formatted table of indicator parameter spaces."""
    header = f"{'Indicator':<25} {'Grid Size':>10} {'Sampler':<8} {'Param Space'}"
    print("\n" + "=" * 90)
    print("  Parameter Space Registry (dry-run)")
    print("=" * 90)
    print(header)
    print("-" * 90)

    for name in sorted(indicators):
        if name not in PARAM_SPACE_REGISTRY:
            print(f"  {'!! ' + name + ' (not in registry)'}")
            continue
        entry = PARAM_SPACE_REGISTRY[name]
        psd = entry["param_space_def"]
        gs = _grid_size(psd)
        sampler = _sampler_type(gs)
        crypto_tag = " [crypto]" if entry.get("_crypto_native") else ""
        param_str = (
            ", ".join(
                f"{p['name']}[{p['low']}..{p['high']}]"
                + (f" step={p['step']}" if p.get("step") else "")
                for p in psd
            )
            if psd
            else "(no params)"
        )
        print(f"  {name + crypto_tag:<25} {gs:>10} {sampler:<8} {param_str}")

    print("=" * 90)
    print(f"  Total: {len(indicators)} indicator(s)\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for Phase 105 parameter sweeps."""
    parser = argparse.ArgumentParser(
        description="Run IC-based parameter sweeps for FDR-surviving indicators (Phase 105).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--indicator",
        metavar="NAME",
        help="Sweep a single indicator by name (must be in PARAM_SPACE_REGISTRY). "
        "If omitted, sweeps all FDR survivors.",
    )
    parser.add_argument(
        "--asset-id",
        type=int,
        metavar="ID",
        dest="asset_id",
        help="Sweep a single asset by id. If omitted, queries top-20 assets from ic_results.",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        metavar="TF",
        help="Timeframe string (default: 1D).",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        dest="venue_id",
        metavar="ID",
        help="Venue ID (default: 1 = CMC_AGG).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="List indicators and parameter spaces without running sweeps.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        dest="top_n",
        metavar="N",
        help="Number of top-IC candidates for plateau ranking (default: 5).",
    )
    parser.add_argument(
        "--tpe-trials",
        type=int,
        default=100,
        dest="tpe_trials",
        metavar="N",
        help="Number of TPE trials for large parameter spaces (default: 100).",
    )
    parser.add_argument(
        "--skip-stability",
        action="store_true",
        dest="skip_stability",
        help="Skip rolling_stability_test (faster exploration).",
    )
    parser.add_argument(
        "--skip-dsr",
        action="store_true",
        dest="skip_dsr",
        help="Skip DSR computation.",
    )
    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    t0 = time.monotonic()

    # -----------------------------------------------------------------------
    # Dry-run: print table and exit
    # -----------------------------------------------------------------------
    if args.dry_run:
        if args.indicator:
            indicators = [args.indicator]
        else:
            indicators = list(PARAM_SPACE_REGISTRY.keys())
        _print_dry_run_table(indicators)
        return

    # -----------------------------------------------------------------------
    # Create DB engine (NullPool -- project convention for scripts)
    # -----------------------------------------------------------------------
    try:
        db_url = resolve_db_url()
    except RuntimeError as exc:
        logger.error("Cannot resolve DB URL: %s", exc)
        raise SystemExit(1) from exc

    engine = create_engine(db_url, poolclass=NullPool)
    logger.info("DB engine created (NullPool)")

    # -----------------------------------------------------------------------
    # Determine indicator list
    # -----------------------------------------------------------------------
    if args.indicator:
        if args.indicator not in PARAM_SPACE_REGISTRY:
            logger.error(
                "Indicator '%s' not in PARAM_SPACE_REGISTRY. Available: %s",
                args.indicator,
                sorted(PARAM_SPACE_REGISTRY.keys()),
            )
            raise SystemExit(1)
        indicators = [args.indicator]
    else:
        with engine.connect() as conn:
            survivors = _load_survivors(conn)

        if not survivors:
            logger.info(
                "No FDR survivors found in dim_feature_registry or trial_registry. "
                "Use --indicator to sweep a specific indicator."
            )
            raise SystemExit(0)

        # Intersect with registry
        indicators = [s for s in survivors if s in PARAM_SPACE_REGISTRY]
        if not indicators:
            logger.warning(
                "FDR survivors %s have no matching entries in PARAM_SPACE_REGISTRY. "
                "Use --indicator to sweep specific indicators.",
                survivors,
            )
            raise SystemExit(0)
        logger.info(
            "Sweep targets: %d indicators (from %d survivors intersected with registry)",
            len(indicators),
            len(survivors),
        )

    # -----------------------------------------------------------------------
    # Determine asset list
    # -----------------------------------------------------------------------
    if args.asset_id:
        asset_ids = [args.asset_id]
    else:
        with engine.connect() as conn:
            asset_ids = _query_asset_ids(conn, args.tf, limit=20)
        if not asset_ids:
            logger.error(
                "No assets found for tf=%s. Use --asset-id to specify one.", args.tf
            )
            raise SystemExit(1)
        logger.info(
            "Asset sweep universe: %d assets for tf=%s", len(asset_ids), args.tf
        )

    # -----------------------------------------------------------------------
    # Resolve tf_days_nominal
    # -----------------------------------------------------------------------
    with engine.connect() as conn:
        tf_days_nominal = _get_tf_days_nominal(conn, args.tf)
    logger.info("tf=%s tf_days_nominal=%.4f", args.tf, tf_days_nominal)

    # -----------------------------------------------------------------------
    # Sweep loop
    # -----------------------------------------------------------------------
    sweep_count = 0
    total_trials = 0
    results: list[dict] = []

    for indicator_name in indicators:
        entry = PARAM_SPACE_REGISTRY[indicator_name]

        # Skip crypto-native indicators with empty param spaces (placeholders)
        if entry.get("_crypto_native") and not entry["param_space_def"]:
            logger.info(
                "Skipping '%s' (crypto-native placeholder with no param space)",
                indicator_name,
            )
            continue

        # Resolve feature function
        feature_fn = _resolve_feature_fn(entry["feature_fn_path"])
        if feature_fn is None:
            logger.warning(
                "Skipping '%s': could not resolve feature function", indicator_name
            )
            continue

        for asset_id in asset_ids:
            logger.info(
                "--- Sweeping indicator=%s asset_id=%d tf=%s ---",
                indicator_name,
                asset_id,
                args.tf,
            )

            try:
                with engine.connect() as conn:
                    data = _load_data_for_asset(conn, asset_id, args.tf, args.venue_id)

                if data is None:
                    logger.info(
                        "Skipping id=%d tf=%s: insufficient data", asset_id, args.tf
                    )
                    continue

                close = data["close"]
                high = data["high"]
                low = data["low"]
                volume = data["volume"]
                fwd_ret = data["fwd_ret"]

                train_start = close.index.min()
                # train_end: all but last period (prevent lookahead)
                train_end = close.index.max() - pd.Timedelta(days=tf_days_nominal)

                with engine.begin() as conn:
                    sweep_result = run_sweep(
                        indicator_name=indicator_name,
                        feature_fn=feature_fn,
                        param_space_def=entry["param_space_def"],
                        close=close,
                        high=high,
                        low=low,
                        volume=volume,
                        fwd_ret=fwd_ret,
                        train_start=train_start,
                        train_end=train_end,
                        asset_id=asset_id,
                        tf=args.tf,
                        tf_days_nominal=tf_days_nominal,
                        venue_id=args.venue_id,
                        tpe_n_trials=args.tpe_trials,
                        conn=conn,
                    )

                sweep_count += 1
                total_trials += sweep_result.get("n_trials", 0)

                # Select best (unless both skip flags are set)
                selection: Optional[dict] = None
                if not (args.skip_stability and args.skip_dsr):
                    with engine.begin() as conn:
                        selection = select_best_from_sweep(
                            sweep_result=sweep_result,
                            feature_fn=feature_fn,
                            close=close,
                            high=high,
                            low=low,
                            volume=volume,
                            fwd_ret=fwd_ret,
                            train_start=train_start,
                            train_end=train_end,
                            tf_days_nominal=tf_days_nominal,
                            conn=conn,
                            top_n=args.top_n,
                        )

                # Collect result row
                row: dict[str, Any] = {
                    "indicator": indicator_name,
                    "asset_id": asset_id,
                    "tf": args.tf,
                    "best_ic": sweep_result.get("best_ic"),
                    "n_trials": sweep_result.get("n_trials"),
                    "n_complete": sweep_result.get("n_complete"),
                    "best_params": sweep_result.get("best_params"),
                }
                if selection:
                    row.update(
                        {
                            "selected_params": selection.get("selected_params"),
                            "plateau_score": selection.get("plateau_score"),
                            "stability_passes": selection.get("stability", {}).get(
                                "passes"
                            ),
                            "dsr": selection.get("dsr", {}).get("dsr"),
                        }
                    )
                results.append(row)

                # Log row summary
                ic_str = (
                    f"{row['best_ic']:.4f}" if row.get("best_ic") is not None else "NaN"
                )
                ps_str = f"{row.get('plateau_score', float('nan')):.3f}"
                dsr_str = (
                    f"{row.get('dsr', float('nan')):.4f}"
                    if row.get("dsr") is not None
                    else "NaN"
                )
                logger.info(
                    "DONE indicator=%s id=%d tf=%s IC=%s plateau=%s DSR=%s",
                    indicator_name,
                    asset_id,
                    args.tf,
                    ic_str,
                    ps_str,
                    dsr_str,
                )

            except KeyboardInterrupt:
                logger.warning(
                    "KeyboardInterrupt -- stopping sweep loop. Partial results logged."
                )
                _print_summary(results, sweep_count, total_trials, t0)
                raise SystemExit(0)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Sweep failed for indicator=%s id=%d tf=%s: %s",
                    indicator_name,
                    asset_id,
                    args.tf,
                    exc,
                )
                continue

    # -----------------------------------------------------------------------
    # Summary table
    # -----------------------------------------------------------------------
    _print_summary(results, sweep_count, total_trials, t0)


def _print_summary(
    results: list[dict],
    sweep_count: int,
    total_trials: int,
    t0: float,
) -> None:
    """Print summary table of sweep results."""
    elapsed = time.monotonic() - t0
    minutes, seconds = divmod(int(elapsed), 60)

    print("\n" + "=" * 100)
    print("  Phase 105 Parameter Sweep Summary")
    print("=" * 100)
    print(
        f"  Completed: {sweep_count} sweep(s) | Total trials: {total_trials} | "
        f"Elapsed: {minutes}m {seconds}s"
    )
    print("-" * 100)

    if not results:
        print("  No results.")
    else:
        hdr = f"  {'Indicator':<25} {'ID':>6} {'TF':<5} {'Best IC':>9} {'Plateau':>8} {'Stability':<11} {'DSR':>8}"
        print(hdr)
        print("  " + "-" * 96)
        for r in results:
            ic = f"{r['best_ic']:.4f}" if r.get("best_ic") is not None else "    NaN"
            ps = (
                f"{r.get('plateau_score', float('nan')):.3f}"
                if r.get("plateau_score") is not None
                else "    NaN"
            )
            stab = str(r.get("stability_passes", "N/A"))
            dsr = f"{r['dsr']:.4f}" if r.get("dsr") is not None else "    NaN"
            print(
                f"  {r['indicator']:<25} {r['asset_id']:>6} {r['tf']:<5} "
                f"{ic:>9} {ps:>8} {stab:<11} {dsr:>8}"
            )

    print("=" * 100 + "\n")


if __name__ == "__main__":
    main()
