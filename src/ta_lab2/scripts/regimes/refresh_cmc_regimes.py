"""
refresh_cmc_regimes.py - Core regime refresh script.

Orchestrates regime labeling from DB data, including proxy fallback for
young assets. Loads bars + EMAs, runs L0-L2 labeling, resolves policy via
tighten-only semantics, applies hysteresis to smooth labels, detects regime
flips, computes regime stats, computes EMA comovement, and writes results to
all 4 regime tables (cmc_regimes, cmc_regime_flips, cmc_regime_stats,
cmc_regime_comovement).

Young assets without enough bar history use proxy inference
(infer_cycle_proxy, infer_weekly_macro_proxy) rather than leaving labels
as None.

NOTE: Incremental refresh with watermarks is deferred to a future phase.
For v0.7.0 this script performs full-recompute per asset on each run.
Regime computation is fast enough (< 1 second per asset) that watermarks
are not a bottleneck for daily refresh.

Exports:
    compute_regimes_for_id: Per-asset computation returning cmc_regimes-shaped DataFrame
    write_regimes_to_db:    Scoped DELETE + INSERT write to cmc_regimes
    main:                   CLI entrypoint
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from typing import Any, Dict, Mapping, Optional

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from ta_lab2.regimes.data_budget import assess_data_budget
from ta_lab2.regimes.hysteresis import HysteresisTracker, is_tightening_change
from ta_lab2.regimes.labels import (
    label_layer_daily,
    label_layer_monthly,
    label_layer_weekly,
)
from ta_lab2.regimes.policy_loader import load_policy_table
from ta_lab2.regimes.proxies import (
    ProxyInputs,
    ProxyOutcome,
    infer_cycle_proxy,
    infer_weekly_macro_proxy,
)
from ta_lab2.regimes.resolver import DEFAULT_POLICY_TABLE, resolve_policy_from_table
from ta_lab2.scripts.regimes.regime_comovement import (
    compute_and_write_comovement,
)
from ta_lab2.scripts.regimes.regime_data_loader import (
    load_and_pivot_emas,
    load_bars_for_tf,
    load_regime_input_data,
)
from ta_lab2.scripts.regimes.regime_flips import detect_regime_flips, write_flips_to_db
from ta_lab2.scripts.regimes.regime_stats import compute_regime_stats, write_stats_to_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version string — bump when regime logic changes to invalidate stale labels
# ---------------------------------------------------------------------------
_REGIME_CODE_VERSION = "v0.7.0"

# BTC asset ID used as broad market proxy for young assets
_MARKET_PROXY_ID = 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_version_hash(policy_table: Mapping[str, Any]) -> str:
    """
    Compute a stable SHA-256 hash over sorted policy_table keys + code version.

    Allows detecting stale regime rows when policy or code changes.
    """
    payload = {
        "version": _REGIME_CODE_VERSION,
        "policy_keys": sorted(policy_table.keys()),
    }
    serialised = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


def _forward_fill_labels(
    sparse_labels: pd.Series,
    sparse_ts: pd.Series,
    daily_ts: pd.Series,
) -> pd.Series:
    """
    Forward-fill sparse (monthly or weekly) labels onto daily timestamps.

    Uses pd.merge_asof (merge on nearest past key) to align labels.

    Args:
        sparse_labels: Series of string labels (e.g. L0 monthly values).
        sparse_ts:     Corresponding timestamps (tz-aware UTC, sorted ascending).
        daily_ts:      Daily timestamp Series (tz-aware UTC, sorted ascending).

    Returns:
        Series aligned to daily_ts index, with label forward-filled from
        the most recent sparse_ts that is <= each daily_ts. NaN where no
        prior sparse timestamp exists.
    """
    if sparse_labels.empty or daily_ts.empty:
        return pd.Series([None] * len(daily_ts), dtype=object)

    label_df = pd.DataFrame({"ts": sparse_ts.values, "label": sparse_labels.values})
    label_df = label_df.sort_values("ts").reset_index(drop=True)

    daily_df = pd.DataFrame({"ts": daily_ts.values})
    daily_df = daily_df.sort_values("ts").reset_index(drop=True)

    # merge_asof requires both sides sorted and same tz
    # Ensure tz-aware
    label_df["ts"] = pd.to_datetime(label_df["ts"], utc=True)
    daily_df["ts"] = pd.to_datetime(daily_df["ts"], utc=True)

    merged = pd.merge_asof(
        daily_df,
        label_df,
        on="ts",
        direction="backward",
    )
    return merged["label"]


def _load_proxy_weekly(
    engine: Engine,
    proxy_id: int,
    cal_scheme: str,
) -> pd.DataFrame:
    """
    Load BTC (or other proxy) weekly bars + EMAs merged into one DataFrame.

    Returns a wide DataFrame with columns: id, ts, close, close_ema_20,
    close_ema_50, close_ema_200. Used by both proxy functions.
    """
    bars = load_bars_for_tf(engine, proxy_id, tf="1W", cal_scheme=cal_scheme)
    emas = load_and_pivot_emas(
        engine, proxy_id, tf="1W", periods=[20, 50, 200], cal_scheme=cal_scheme
    )
    if bars.empty:
        return pd.DataFrame()
    if emas.empty:
        return bars

    merged = pd.merge(bars, emas, on=["id", "ts"], how="left")
    return merged.sort_values("ts").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_regimes_for_id(
    engine: Engine,
    asset_id: int,
    policy_table: Optional[Mapping[str, Any]] = None,
    cal_scheme: str = "iso",
    min_bars_overrides: Optional[Dict[str, int]] = None,
    hysteresis_tracker: Optional[HysteresisTracker] = None,
) -> pd.DataFrame:
    """
    Compute regime labels and resolved policy for a single asset.

    Loads bars + EMAs from DB, runs L0-L2 labelers, resolves policy via
    tighten-only semantics, applies optional hysteresis to smooth labels,
    applies proxy fallback for young assets, and returns a DataFrame matching
    the cmc_regimes schema.

    Args:
        engine:              SQLAlchemy engine connected to PostgreSQL.
        asset_id:            Integer asset ID (matches id in dim_assets).
        policy_table:        Regime policy lookup table. Defaults to
                             DEFAULT_POLICY_TABLE from resolver.py.
        cal_scheme:          Calendar scheme for weekly/monthly bars.
                             'iso' (default) or 'us'.
        min_bars_overrides:  Optional dict to override data budget thresholds,
                             e.g. {"L0": 30, "L1": 26}. Not yet wired to
                             assess_data_budget (reserved for future use).
        hysteresis_tracker:  Optional HysteresisTracker to smooth label
                             transitions. If provided, per-layer hysteresis is
                             applied before policy resolution. Pass None to
                             skip hysteresis (raw labels used directly).

    Returns:
        DataFrame with columns matching cmc_regimes schema, one row per
        daily bar. Returns empty DataFrame if no daily data exists.
    """
    if policy_table is None:
        policy_table = DEFAULT_POLICY_TABLE

    version_hash = _compute_version_hash(policy_table)

    logger.info(
        "compute_regimes_for_id: asset_id=%s cal_scheme=%s hysteresis=%s",
        asset_id,
        cal_scheme,
        "ON" if hysteresis_tracker is not None else "OFF",
    )

    # ------------------------------------------------------------------
    # 1. Load bars + EMAs for all TFs
    # ------------------------------------------------------------------
    data = load_regime_input_data(engine, asset_id, cal_scheme=cal_scheme)
    monthly = data["monthly"]
    weekly = data["weekly"]
    daily = data["daily"]

    if daily.empty:
        logger.warning(
            "compute_regimes_for_id: no daily data for asset_id=%s, returning empty",
            asset_id,
        )
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # 2. Assess data budget -> determine enabled layers and feature tier
    # ------------------------------------------------------------------
    ctx = assess_data_budget(monthly=monthly, weekly=weekly, daily=daily)
    mode = ctx.feature_tier  # "full" or "lite"

    logger.info(
        "  data_budget: bars M=%d W=%d D=%d | tier=%s | layers=%s",
        ctx.bars_by_tf["M"],
        ctx.bars_by_tf["W"],
        ctx.bars_by_tf["D"],
        mode,
        {k: v for k, v in ctx.enabled_layers.items() if k in ("L0", "L1", "L2")},
    )

    # ------------------------------------------------------------------
    # 3. Label each enabled layer
    # ------------------------------------------------------------------
    l0_series: Optional[pd.Series] = None
    l1_series: Optional[pd.Series] = None
    l2_series: Optional[pd.Series] = None

    if ctx.enabled_layers["L0"] and not monthly.empty:
        try:
            l0_series = label_layer_monthly(monthly, mode=mode)
            logger.info("  L0 labeler: %d labels", len(l0_series))
        except Exception as exc:
            logger.warning("  L0 labeler failed: %s", exc)

    if ctx.enabled_layers["L1"] and not weekly.empty:
        try:
            l1_series = label_layer_weekly(weekly, mode=mode)
            logger.info("  L1 labeler: %d labels", len(l1_series))
        except Exception as exc:
            logger.warning("  L1 labeler failed: %s", exc)

    if ctx.enabled_layers["L2"] and not daily.empty:
        try:
            l2_series = label_layer_daily(daily, mode=mode)
            logger.info("  L2 labeler: %d labels", len(l2_series))
        except Exception as exc:
            logger.warning("  L2 labeler failed: %s", exc)

    # ------------------------------------------------------------------
    # 4. Proxy fallback for young assets (disabled layers)
    # ------------------------------------------------------------------
    proxy_out: Optional[ProxyOutcome] = None
    proxy_out_l1: Optional[ProxyOutcome] = None

    # L0 proxy: if L0 disabled, use BTC weekly as broad market proxy
    if not ctx.enabled_layers["L0"]:
        if asset_id != _MARKET_PROXY_ID:
            try:
                market_weekly = _load_proxy_weekly(engine, _MARKET_PROXY_ID, cal_scheme)
                proxy_inp = ProxyInputs(child_daily=daily, market_weekly=market_weekly)
                proxy_out = infer_cycle_proxy(proxy_inp)
                logger.info("  L0 proxy: l0_cap=%.2f", proxy_out.l0_cap)
            except Exception as exc:
                logger.warning("  L0 proxy failed: %s", exc)
                proxy_out = None
        else:
            logger.debug("  L0 proxy: skipped for market proxy asset (id=1)")

    # L1 proxy: if L1 disabled, use BTC weekly as parent proxy
    if not ctx.enabled_layers["L1"]:
        if asset_id != _MARKET_PROXY_ID:
            try:
                parent_weekly = _load_proxy_weekly(engine, _MARKET_PROXY_ID, cal_scheme)
                proxy_inp_l1 = ProxyInputs(
                    child_daily=daily, parent_weekly=parent_weekly
                )
                proxy_out_l1 = infer_weekly_macro_proxy(proxy_inp_l1)
                logger.info("  L1 proxy: l1_size_mult=%.2f", proxy_out_l1.l1_size_mult)
            except Exception as exc:
                logger.warning("  L1 proxy failed: %s", exc)
                proxy_out_l1 = None
        else:
            logger.debug("  L1 proxy: skipped for market proxy asset (id=1)")

    # ------------------------------------------------------------------
    # 5. Forward-fill sparse (monthly/weekly) labels to daily index
    # ------------------------------------------------------------------
    daily_ts = daily["ts"]

    if l0_series is not None:
        l0_ts = monthly.loc[l0_series.index, "ts"] if "ts" in monthly.columns else None
        if l0_ts is not None:
            l0_daily = _forward_fill_labels(l0_series, l0_ts, daily_ts)
        else:
            l0_daily = pd.Series([None] * len(daily), dtype=object)
    else:
        l0_daily = pd.Series([None] * len(daily), dtype=object)

    if l1_series is not None:
        l1_ts = weekly.loc[l1_series.index, "ts"] if "ts" in weekly.columns else None
        if l1_ts is not None:
            l1_daily = _forward_fill_labels(l1_series, l1_ts, daily_ts)
        else:
            l1_daily = pd.Series([None] * len(daily), dtype=object)
    else:
        l1_daily = pd.Series([None] * len(daily), dtype=object)

    if l2_series is not None:
        # L2 is already daily -- align by resetting index to match daily
        l2_daily = l2_series.reset_index(drop=True)
    else:
        l2_daily = pd.Series([None] * len(daily), dtype=object)

    # Reset daily index to ensure positional alignment
    daily_reset = daily.reset_index(drop=True)

    # ------------------------------------------------------------------
    # 6. Resolve policy row-by-row, applying hysteresis and proxy tightening
    # ------------------------------------------------------------------
    # Reset hysteresis tracker between assets if one is provided
    if hysteresis_tracker is not None:
        hysteresis_tracker.reset()

    rows = []
    for i in range(len(daily_reset)):
        row_ts = daily_reset.loc[i, "ts"]

        l0_raw = l0_daily.iloc[i] if i < len(l0_daily) else None
        l1_raw = l1_daily.iloc[i] if i < len(l1_daily) else None
        l2_raw = l2_daily.iloc[i] if i < len(l2_daily) else None

        # Convert NaN to None for cleaner handling
        l0_raw = l0_raw if pd.notna(l0_raw) else None
        l1_raw = l1_raw if pd.notna(l1_raw) else None
        l2_raw = l2_raw if pd.notna(l2_raw) else None

        # Apply per-layer hysteresis before policy resolution
        if hysteresis_tracker is not None:
            # L0 layer
            if l0_raw is not None:
                l0_current = hysteresis_tracker.get_current("L0")
                l0_tightening = is_tightening_change(
                    l0_current, str(l0_raw), policy_table
                )
                l0_val = hysteresis_tracker.update(
                    "L0", str(l0_raw), is_tightening=l0_tightening
                )
            else:
                l0_val = None

            # L1 layer
            if l1_raw is not None:
                l1_current = hysteresis_tracker.get_current("L1")
                l1_tightening = is_tightening_change(
                    l1_current, str(l1_raw), policy_table
                )
                l1_val = hysteresis_tracker.update(
                    "L1", str(l1_raw), is_tightening=l1_tightening
                )
            else:
                l1_val = None

            # L2 layer
            if l2_raw is not None:
                l2_current = hysteresis_tracker.get_current("L2")
                l2_tightening = is_tightening_change(
                    l2_current, str(l2_raw), policy_table
                )
                l2_val = hysteresis_tracker.update(
                    "L2", str(l2_raw), is_tightening=l2_tightening
                )
            else:
                l2_val = None
        else:
            # No hysteresis — use raw labels directly
            l0_val = l0_raw
            l1_val = l1_raw
            l2_val = l2_raw

        # Resolve policy from effective (hysteresis-filtered) labels
        policy = resolve_policy_from_table(
            policy_table,
            L0=l0_val,
            L1=l1_val,
            L2=l2_val,
            L3=None,
            L4=None,
        )

        # Apply proxy tightening (proxies can only reduce, never increase)
        if proxy_out is not None and proxy_out.l0_cap < 1.0:
            policy.gross_cap = min(policy.gross_cap, proxy_out.l0_cap)

        if proxy_out_l1 is not None and proxy_out_l1.l1_size_mult < 1.0:
            policy.size_mult = min(policy.size_mult, proxy_out_l1.l1_size_mult)

        # Build regime_key: L2 is primary, fallback to L1, then L0
        if l2_val is not None:
            regime_key = str(l2_val)
        elif l1_val is not None:
            regime_key = str(l1_val)
        elif l0_val is not None:
            regime_key = str(l0_val)
        else:
            regime_key = "Unknown"

        rows.append(
            {
                "id": asset_id,
                "ts": row_ts,
                "tf": "1D",
                "l0_label": l0_val,
                "l1_label": l1_val,
                "l2_label": l2_val,
                "l3_label": None,
                "l4_label": None,
                "regime_key": regime_key,
                "size_mult": policy.size_mult,
                "stop_mult": policy.stop_mult,
                "orders": policy.orders,
                "gross_cap": policy.gross_cap,
                "pyramids": policy.pyramids,
                "feature_tier": ctx.feature_tier,
                "l0_enabled": ctx.enabled_layers["L0"],
                "l1_enabled": ctx.enabled_layers["L1"],
                "l2_enabled": ctx.enabled_layers["L2"],
                "regime_version_hash": version_hash,
                "updated_at": pd.Timestamp.now(tz="UTC"),
            }
        )

    result = pd.DataFrame(rows)

    if not result.empty:
        unique_keys = result["regime_key"].nunique()
        logger.info(
            "  result: %d rows, %d unique regime_keys: %s",
            len(result),
            unique_keys,
            result["regime_key"].value_counts().head(5).to_dict(),
        )

    return result


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------


def write_regimes_to_db(
    engine: Engine,
    df: pd.DataFrame,
    tf: str = "1D",
) -> int:
    """
    Write regime rows to cmc_regimes using scoped DELETE + INSERT.

    Deletes all existing rows for (ids, tf), then inserts the new DataFrame.
    This matches the scoped DELETE + INSERT pattern used by the feature pipeline
    (BaseFeature.write_to_db).

    Args:
        engine: SQLAlchemy engine.
        df:     DataFrame with columns matching cmc_regimes schema.
        tf:     Timeframe being written (default '1D').

    Returns:
        Number of rows written.
    """
    if df.empty:
        logger.info("write_regimes_to_db: empty DataFrame, nothing to write")
        return 0

    ids = df["id"].unique().tolist()

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.cmc_regimes WHERE id = ANY(:ids) AND tf = :tf"),
            {"ids": ids, "tf": tf},
        )

    # Drop columns not in the cmc_regimes schema (defensive)
    _SCHEMA_COLS = {
        "id",
        "ts",
        "tf",
        "l0_label",
        "l1_label",
        "l2_label",
        "l3_label",
        "l4_label",
        "regime_key",
        "size_mult",
        "stop_mult",
        "orders",
        "gross_cap",
        "pyramids",
        "feature_tier",
        "l0_enabled",
        "l1_enabled",
        "l2_enabled",
        "regime_version_hash",
        "updated_at",
    }
    write_df = df[[c for c in df.columns if c in _SCHEMA_COLS]].copy()

    write_df.to_sql(
        "cmc_regimes",
        engine,
        schema="public",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=5000,
    )

    n_rows = len(write_df)
    logger.info(
        "write_regimes_to_db: wrote %d rows for ids=%s tf=%s",
        n_rows,
        ids,
        tf,
    )
    return n_rows


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _get_all_asset_ids(engine: Engine) -> list[int]:
    """
    Return all active asset IDs.

    Tries dim_assets WHERE is_active = TRUE first, falls back to DISTINCT id
    from cmc_price_bars_multi_tf WHERE tf = '1D' if is_active column missing.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT DISTINCT id FROM public.dim_assets "
                    "WHERE is_active = TRUE ORDER BY id"
                )
            )
            ids = [row[0] for row in result]
            if ids:
                return ids
    except Exception as exc:
        logger.debug("dim_assets query failed (%s), falling back to bars table", exc)

    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT DISTINCT id FROM public.cmc_price_bars_multi_tf "
                "WHERE tf = '1D' ORDER BY id"
            )
        )
        return [row[0] for row in result]


def _load_returns_for_id(engine: Engine, asset_id: int) -> Optional[pd.DataFrame]:
    """
    Load 1D forward returns for an asset from cmc_returns.

    Returns DataFrame with (id, ts, tf, ret_1d) or None on failure.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT id, ts, '1D' AS tf, ret_1d "
                    "FROM public.cmc_returns "
                    "WHERE id = :id AND tf = '1D' "
                    "ORDER BY ts"
                ),
                {"id": asset_id},
            )
            rows = result.fetchall()
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["id", "ts", "tf", "ret_1d"])
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            return df
    except Exception as exc:
        logger.debug(
            "_load_returns_for_id: failed for id=%s (%s), returns will be NULL",
            asset_id,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Main / CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """
    CLI entrypoint for regime refresh.

    Example usage:
        python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 --dry-run -v
        python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --all --cal-scheme iso
        python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 --no-hysteresis
        python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 --min-hold-bars 5
    """
    parser = argparse.ArgumentParser(
        description="Refresh cmc_regimes: compute regime labels for all assets.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        type=str,
        metavar="ID[,ID...]",
        help="Comma-separated asset IDs to process (e.g. '1,2,5').",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Process all active asset IDs from dim_assets.",
    )

    parser.add_argument(
        "--cal-scheme",
        choices=["iso", "us"],
        default="iso",
        help="Calendar scheme for weekly/monthly bars.",
    )
    parser.add_argument(
        "--policy-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to YAML policy overlay. Defaults to configs/regime_policies.yaml.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute regimes but do not write to DB.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        metavar="URL",
        help="PostgreSQL connection URL. Defaults to TARGET_DB_URL env var.",
    )
    parser.add_argument(
        "--min-bars-l0",
        type=int,
        default=None,
        metavar="N",
        help="Override minimum monthly bars required to enable L0 labeler.",
    )
    parser.add_argument(
        "--min-bars-l1",
        type=int,
        default=None,
        metavar="N",
        help="Override minimum weekly bars required to enable L1 labeler.",
    )
    parser.add_argument(
        "--min-bars-l2",
        type=int,
        default=None,
        metavar="N",
        help="Override minimum daily bars required to enable L2 labeler.",
    )
    parser.add_argument(
        "--no-hysteresis",
        action="store_true",
        help="Disable hysteresis filtering (raw labels used directly).",
    )
    parser.add_argument(
        "--min-hold-bars",
        type=int,
        default=3,
        metavar="N",
        help="Minimum consecutive bars before a loosening regime change is accepted (hysteresis).",
    )

    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # ------------------------------------------------------------------
    # DB connection
    # ------------------------------------------------------------------
    import os

    db_url = args.db_url or os.environ.get("TARGET_DB_URL")
    if not db_url:
        logger.error("No DB URL provided. Set TARGET_DB_URL or pass --db-url.")
        return 1

    engine = create_engine(db_url)

    # ------------------------------------------------------------------
    # Policy table
    # ------------------------------------------------------------------
    policy_table = load_policy_table(args.policy_file)
    logger.info("Policy table loaded: %d rules", len(policy_table))

    # ------------------------------------------------------------------
    # Version hash for this run
    # ------------------------------------------------------------------
    version_hash = _compute_version_hash(policy_table)
    logger.info("Version hash: %s", version_hash)

    # ------------------------------------------------------------------
    # Hysteresis setup
    # ------------------------------------------------------------------
    use_hysteresis = not args.no_hysteresis
    if use_hysteresis:
        hysteresis_tracker = HysteresisTracker(min_bars_hold=args.min_hold_bars)
        logger.info("Hysteresis: ON (min_hold_bars=%d)", args.min_hold_bars)
    else:
        hysteresis_tracker = None
        logger.info("Hysteresis: OFF (--no-hysteresis)")

    # ------------------------------------------------------------------
    # Resolve asset IDs
    # ------------------------------------------------------------------
    if args.ids:
        asset_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    else:
        logger.info("Querying all active asset IDs...")
        asset_ids = _get_all_asset_ids(engine)

    logger.info("Processing %d assets: %s", len(asset_ids), asset_ids[:10])

    # ------------------------------------------------------------------
    # min_bars overrides (reserved for future integration with assess_data_budget)
    # ------------------------------------------------------------------
    min_bars_overrides: Dict[str, int] = {}
    if args.min_bars_l0 is not None:
        min_bars_overrides["L0"] = args.min_bars_l0
    if args.min_bars_l1 is not None:
        min_bars_overrides["L1"] = args.min_bars_l1
    if args.min_bars_l2 is not None:
        min_bars_overrides["L2"] = args.min_bars_l2

    # ------------------------------------------------------------------
    # Per-asset processing
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    total_regime_rows = 0
    total_flip_rows = 0
    total_stat_rows = 0
    total_como_rows = 0
    assets_ok = 0
    assets_empty = 0
    assets_err = 0
    failed_assets: list[tuple[int, str]] = []

    for asset_id in asset_ids:
        try:
            # ---- 1. Compute regimes ----
            regime_df = compute_regimes_for_id(
                engine,
                asset_id,
                policy_table=policy_table,
                cal_scheme=args.cal_scheme,
                min_bars_overrides=min_bars_overrides if min_bars_overrides else None,
                hysteresis_tracker=hysteresis_tracker,
            )

            if regime_df.empty:
                logger.warning("  [id=%d] empty regime result, skipping", asset_id)
                assets_empty += 1
                continue

            # ---- 2. Detect flips ----
            flips_df = detect_regime_flips(regime_df)
            n_flips = len(flips_df)

            # ---- 3. Compute stats ----
            # Optionally load returns data for enriched stats
            returns_df = _load_returns_for_id(engine, asset_id)
            stats_df = compute_regime_stats(regime_df, returns_df=returns_df)
            n_stats = len(stats_df)

            # ---- 4. Load daily data for comovement (bars + EMAs) ----
            data = load_regime_input_data(engine, asset_id, cal_scheme=args.cal_scheme)
            daily_df = data["daily"]
            n_como = 0

            # ---- 5. Log per-asset summary ----
            unique_keys = regime_df["regime_key"].nunique()
            logger.info(
                "  [id=%d] %d regime rows | %d unique keys | %d flips | "
                "%d stat rows | tier=%s | L0=%s L1=%s L2=%s",
                asset_id,
                len(regime_df),
                unique_keys,
                n_flips,
                n_stats,
                regime_df["feature_tier"].iloc[0],
                regime_df["l0_enabled"].iloc[0],
                regime_df["l1_enabled"].iloc[0],
                regime_df["l2_enabled"].iloc[0],
            )

            if args.verbose:
                dist = regime_df["regime_key"].value_counts().head(5).to_dict()
                logger.debug("    regime_key distribution: %s", dist)
                logger.debug("    version_hash: %s", version_hash)

            # ---- 6. Write to DB or dry-run ----
            if not args.dry_run:
                # Write cmc_regimes
                n_regime = write_regimes_to_db(engine, regime_df, tf="1D")
                total_regime_rows += n_regime

                # Write cmc_regime_flips
                if not flips_df.empty:
                    n_flips_written = write_flips_to_db(
                        engine, flips_df, ids=[asset_id], tf="1D"
                    )
                    total_flip_rows += n_flips_written

                # Write cmc_regime_stats
                if not stats_df.empty:
                    n_stats_written = write_stats_to_db(
                        engine, stats_df, ids=[asset_id], tf="1D"
                    )
                    total_stat_rows += n_stats_written

                # Write cmc_regime_comovement (compute + write)
                if not daily_df.empty:
                    n_como = compute_and_write_comovement(
                        engine, asset_id, daily_df, tf="1D"
                    )
                    total_como_rows += n_como

                logger.info(
                    "  [id=%d] wrote: regimes=%d flips=%d stats=%d comovement=%d",
                    asset_id,
                    n_regime,
                    n_flips_written if not flips_df.empty else 0,
                    n_stats_written if not stats_df.empty else 0,
                    n_como,
                )
            else:
                # Dry run — compute comovement but don't write
                from ta_lab2.scripts.regimes.regime_comovement import (
                    compute_comovement_records,
                )

                como_df = compute_comovement_records(
                    asset_id=asset_id, daily_df=daily_df, tf="1D"
                )
                n_como = len(como_df)
                total_regime_rows += len(regime_df)
                total_flip_rows += n_flips
                total_stat_rows += n_stats
                total_como_rows += n_como
                logger.info(
                    "  [id=%d] DRY RUN: would write regimes=%d flips=%d stats=%d comovement=%d",
                    asset_id,
                    len(regime_df),
                    n_flips,
                    n_stats,
                    n_como,
                )

            assets_ok += 1

        except Exception as exc:
            logger.error("  [id=%d] FAILED: %s", asset_id, exc, exc_info=args.verbose)
            assets_err += 1
            failed_assets.append((asset_id, str(exc)))

    elapsed = time.perf_counter() - t0

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    mode_str = "[DRY RUN] " if args.dry_run else ""
    print(
        f"\n{mode_str}Regime refresh complete in {elapsed:.1f}s\n"
        f"  Assets processed  : {assets_ok}\n"
        f"  Assets empty      : {assets_empty}\n"
        f"  Assets errored    : {assets_err}\n"
        f"  Regime rows       : {total_regime_rows}\n"
        f"  Flip rows         : {total_flip_rows}\n"
        f"  Stat rows         : {total_stat_rows}\n"
        f"  Comovement rows   : {total_como_rows}\n"
        f"  Hysteresis        : {'ON (min_hold_bars=' + str(args.min_hold_bars) + ')' if use_hysteresis else 'OFF'}\n"
        f"  Version hash      : {version_hash}\n"
    )

    if failed_assets:
        print("  Failed assets:")
        for aid, err in failed_assets:
            print(f"    id={aid}: {err}")

    return 0 if assets_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
