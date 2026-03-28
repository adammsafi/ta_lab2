#!/usr/bin/env python
"""
Refresh portfolio allocations.

Loads price history, runs PortfolioOptimizer (+ optional BL and bet-sizing),
and persists results to portfolio_allocations.

CRITICAL: price_bars_multi_tf_u uses 'timestamp' column (NOT 'ts').
CRITICAL: dim_timeframe column is tf_days_nominal. DimTimeframe().tf_days(tf) returns it.
CRITICAL: Use NullPool for engines in batch scripts.
ASCII-only file -- no UTF-8 box-drawing characters.

Usage:
    python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids all --tf 1D
    python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids 1,52,825 --dry-run
    python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids all --no-bl --no-sizing
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _make_engine(db_url: str):
    """Create a NullPool SQLAlchemy engine (batch script pattern)."""
    return create_engine(db_url, poolclass=NullPool)


def _resolve_db_url(db_url_arg: Optional[str]) -> str:
    """Resolve DB URL from argument, env, or config file."""
    import os

    if db_url_arg:
        return db_url_arg

    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url

    # Fall back to db_config.env file pattern
    config_path = "db_config.env"
    try:
        from pathlib import Path

        p = Path(config_path)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("TARGET_DB_URL=") or line.startswith(
                    "DATABASE_URL="
                ):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

    raise RuntimeError(
        "No database URL found. Set TARGET_DB_URL env var or pass --db-url."
    )


# ---------------------------------------------------------------------------
# Asset ID resolution
# ---------------------------------------------------------------------------


def _resolve_asset_ids(ids_arg: str, tf: str, engine) -> list[int]:
    """Resolve asset IDs from 'all' or comma-separated list."""
    if ids_arg.lower() == "all":
        # Query distinct asset IDs from the unified price bars table for this TF
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT id FROM price_bars_multi_tf_u "
                    "WHERE tf = :tf ORDER BY id"
                ),
                {"tf": tf},
            ).fetchall()
        ids = [r[0] for r in rows]
        logger.info(
            "Resolved %d asset IDs from price_bars_multi_tf_u (tf=%s)", len(ids), tf
        )
        return ids

    # Comma-separated integers
    try:
        return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]
    except ValueError as exc:
        raise ValueError(
            f"Invalid --ids value {ids_arg!r}. "
            "Use 'all' or a comma-separated list of integers."
        ) from exc


# ---------------------------------------------------------------------------
# Price matrix loader
# ---------------------------------------------------------------------------


def _load_price_matrix(asset_ids: list[int], tf: str, engine) -> pd.DataFrame:
    """
    Load close prices from price_bars_multi_tf_u and pivot to wide format.

    CRITICAL: uses 'timestamp' column (NOT 'ts').

    Returns
    -------
    pd.DataFrame
        DatetimeIndex x asset_id columns, values = close price.
        Columns are integer asset IDs.
    """
    if not asset_ids:
        return pd.DataFrame()

    ids_tuple = tuple(asset_ids)
    # Use ANY(:ids) so we can pass a list via psycopg2/asyncpg without dynamic SQL
    query = text(
        "SELECT id, timestamp, close "
        "FROM price_bars_multi_tf_u "
        "WHERE tf = :tf AND id = ANY(:ids) "
        "ORDER BY timestamp"
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"tf": tf, "ids": list(ids_tuple)})

    if df.empty:
        logger.warning("No price data found for tf=%s, ids=%s", tf, asset_ids[:5])
        return pd.DataFrame()

    # Convert timestamp to tz-aware UTC
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Pivot: rows = timestamp, columns = asset id
    prices = df.pivot(index="timestamp", columns="id", values="close")
    prices.index.name = "ts"
    prices.columns = [int(c) for c in prices.columns]

    logger.info(
        "Loaded price matrix: %d rows x %d assets (tf=%s)",
        len(prices),
        len(prices.columns),
        tf,
    )
    return prices


# ---------------------------------------------------------------------------
# Market cap loader
# ---------------------------------------------------------------------------


def _load_market_caps(asset_ids: list[int], engine) -> pd.Series:
    """
    Load latest market cap (market_cap_usd) from the most recent 1D bar per asset.

    Returns pd.Series index=asset_id, values=market_cap_usd.
    Falls back to uniform caps if market_cap_usd column is missing.
    """
    if not asset_ids:
        return pd.Series(dtype=float)

    query = text(
        """
        SELECT DISTINCT ON (id) id, market_cap_usd
        FROM price_bars_multi_tf_u
        WHERE tf = '1D'
          AND id = ANY(:ids)
          AND market_cap_usd IS NOT NULL
        ORDER BY id, timestamp DESC
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"ids": list(asset_ids)})
        if df.empty:
            logger.warning("No market cap data available; using uniform caps.")
            return pd.Series(1.0, index=asset_ids)
        result = df.set_index("id")["market_cap_usd"].astype(float)
        # Fill missing ids with the median
        median_cap = result.median()
        full = pd.Series(median_cap, index=asset_ids)
        full.update(result)
        return full
    except Exception as exc:
        logger.warning("Could not load market caps (%s); using uniform caps.", exc)
        return pd.Series(1.0, index=asset_ids)


# ---------------------------------------------------------------------------
# Regime loader
# ---------------------------------------------------------------------------


def _load_regime(regime_arg: Optional[str], engine) -> Optional[str]:
    """Load the current regime label from DB or return the override."""
    if regime_arg:
        logger.info("Using regime override: %s", regime_arg)
        return regime_arg

    try:
        query = text(
            """
            SELECT regime_label
            FROM regimes
            WHERE id = 1
            ORDER BY ts DESC
            LIMIT 1
            """
        )
        with engine.connect() as conn:
            row = conn.execute(query).fetchone()
        if row:
            label = row[0]
            logger.info("Loaded current regime from DB: %s", label)
            return label
    except Exception as exc:
        logger.debug(
            "Could not load regime from DB (%s); proceeding without regime.", exc
        )

    return None


# ---------------------------------------------------------------------------
# IC weight overrides
# ---------------------------------------------------------------------------


def load_ic_weight_overrides(engine) -> dict:
    """
    Load active IC weight override multipliers from dim_ic_weight_overrides.

    Returns dict of (feature, asset_id) -> multiplier.
    asset_id=None means override applies to all assets for that feature.

    Excludes:
    - Cleared overrides (cleared_at IS NOT NULL)
    - Expired overrides (expires_at IS NOT NULL AND expires_at < now())

    Handles gracefully when dim_ic_weight_overrides table does not exist
    (migration pending).
    """
    sql = text(
        """
        SELECT feature, asset_id, multiplier
        FROM dim_ic_weight_overrides
        WHERE cleared_at IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        """
    )
    overrides: dict = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        for row in rows:
            mapping = dict(row._mapping)
            key = (mapping["feature"], mapping["asset_id"])
            overrides[key] = float(mapping["multiplier"])
        if overrides:
            logger.info("Loaded %d active IC weight overrides", len(overrides))
        else:
            logger.info("Loaded 0 active IC weight overrides")
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "dim_ic_weight_overrides not accessible (migration pending?): %s", exc
        )
    except Exception as exc:
        logger.error("Failed to load IC weight overrides: %s", exc)
    return overrides


def apply_ic_weight_overrides(
    ic_weights,
    overrides: dict,
    asset_id: Optional[int] = None,
):
    """
    Apply IC weight override multipliers to feature weights.

    For each feature in ic_weights:
    1. Check for asset-specific override (feature, asset_id)
    2. Fall back to global override (feature, None)
    3. Default multiplier = 1.0 (no change)

    Accepts both dict[str, float] and pd.Series inputs.
    Returns modified copy (does not mutate input).
    """
    if not overrides:
        return ic_weights

    is_series = isinstance(ic_weights, pd.Series)
    result = dict(ic_weights)

    for feature in list(result.keys()):
        # Asset-specific override takes precedence over global
        multiplier = overrides.get((feature, asset_id))
        if multiplier is None:
            # Fall back to global override (asset_id=None)
            multiplier = overrides.get((feature, None), 1.0)
        result[feature] = result[feature] * multiplier

    if is_series:
        return pd.Series(result)
    return result


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_allocations(
    ts: datetime,
    optimizer_name: str,
    weights: dict,
    final_weights: dict,
    condition_number: Optional[float],
    regime_label: Optional[str],
    config_snapshot: dict,
    engine,
    dry_run: bool,
) -> int:
    """
    Upsert rows into portfolio_allocations.

    ON CONFLICT (ts, optimizer, asset_id) DO UPDATE SET weight, final_weight,
    condition_number, regime_label, config_snapshot, created_at.

    Returns number of rows written.
    """
    if not weights:
        logger.warning("No weights to persist for optimizer=%s", optimizer_name)
        return 0

    # Convert config_snapshot to JSON string for JSONB binding
    config_json = json.dumps(config_snapshot)

    upsert_sql = text(
        """
        INSERT INTO portfolio_allocations
            (ts, optimizer, asset_id, weight, final_weight, condition_number,
             regime_label, config_snapshot, is_active, created_at)
        VALUES
            (:ts, :optimizer, :asset_id, :weight, :final_weight, :condition_number,
             :regime_label, CAST(:config_snapshot AS jsonb), false, now())
        ON CONFLICT (ts, optimizer, asset_id) DO UPDATE SET
            weight           = EXCLUDED.weight,
            final_weight     = EXCLUDED.final_weight,
            condition_number = EXCLUDED.condition_number,
            regime_label     = EXCLUDED.regime_label,
            config_snapshot  = EXCLUDED.config_snapshot,
            created_at       = now()
        """
    )

    rows = []
    for asset_id, w in weights.items():
        final_w = final_weights.get(asset_id) if final_weights else None
        rows.append(
            {
                "ts": ts,
                "optimizer": optimizer_name,
                "asset_id": int(asset_id),
                "weight": float(w),
                "final_weight": float(final_w) if final_w is not None else None,
                "condition_number": float(condition_number)
                if condition_number is not None
                else None,
                "regime_label": regime_label,
                "config_snapshot": config_json,
            }
        )

    if dry_run:
        logger.info(
            "[DRY RUN] Would upsert %d rows for optimizer=%s ts=%s",
            len(rows),
            optimizer_name,
            ts.isoformat(),
        )
        return len(rows)

    with engine.begin() as conn:
        conn.execute(upsert_sql, rows)

    logger.info(
        "Persisted %d rows for optimizer=%s ts=%s",
        len(rows),
        optimizer_name,
        ts.isoformat(),
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Main refresh logic
# ---------------------------------------------------------------------------


def run_refresh(
    ids_arg: str,
    tf: str,
    regime_override: Optional[str],
    lookback_override: Optional[int],
    dry_run: bool,
    config_path: str,
    use_bl: bool,
    use_sizing: bool,
    db_url: str,
) -> int:
    """
    Run one full portfolio allocation refresh cycle.

    Returns 0 on success, 1 on error.
    """
    from ta_lab2.portfolio import (
        BLAllocationBuilder,
        BetSizer,
        PortfolioOptimizer,
        load_portfolio_config,
    )

    # --- Load config ---
    try:
        config = load_portfolio_config(config_path)
    except FileNotFoundError:
        logger.error("Config file not found: %s", config_path)
        return 1

    # --- Engine ---
    engine = _make_engine(db_url)

    # --- Asset IDs ---
    try:
        asset_ids = _resolve_asset_ids(ids_arg, tf, engine)
    except Exception as exc:
        logger.error("Failed to resolve asset IDs: %s", exc)
        return 1

    if not asset_ids:
        logger.warning("No asset IDs to process. Exiting.")
        return 0

    logger.info("Processing %d assets for tf=%s", len(asset_ids), tf)

    # --- Load prices ---
    prices = _load_price_matrix(asset_ids, tf, engine)
    if prices.empty:
        logger.error("No price data loaded. Cannot optimize.")
        return 1

    # --- Adaptive lookback ---
    opt_cfg = config.get("optimizer", {})
    lookback_cal = lookback_override or int(opt_cfg.get("lookback_calendar_days", 180))
    min_lookback = int(opt_cfg.get("min_lookback_bars", 60))

    # Resolve tf_days for adaptive lookback
    try:
        import os

        db_url_env = os.environ.get("TARGET_DB_URL") or db_url
        from ta_lab2.time.dim_timeframe import DimTimeframe

        dim = DimTimeframe.from_db(db_url_env)
        tf_days = float(dim.tf_days(tf))
    except Exception:
        _TF_DAYS_FALLBACK = {
            "1m": 1.0 / 1440,
            "5m": 1.0 / 288,
            "15m": 1.0 / 96,
            "30m": 1.0 / 48,
            "1H": 1.0 / 24,
            "4H": 1.0 / 6,
            "1D": 1.0,
            "7D": 7.0,
            "1W": 7.0,
            "1M": 30.0,
            "3M": 91.0,
        }
        tf_days = _TF_DAYS_FALLBACK.get(tf, 1.0)

    lookback_bars = round(lookback_cal / tf_days)
    if lookback_bars < min_lookback:
        logger.error(
            "Computed lookback_bars=%d for tf=%s is below min_lookback_bars=%d.",
            lookback_bars,
            tf,
            min_lookback,
        )
        return 1

    # --- Filter assets with insufficient history ---
    required_bars = max(min_lookback, round(lookback_bars * 0.5))
    valid_cols = [c for c in prices.columns if prices[c].count() >= required_bars]
    dropped = len(prices.columns) - len(valid_cols)
    if dropped > 0:
        logger.info(
            "Dropped %d assets with < %d bars of history (required %d); %d remain.",
            dropped,
            required_bars,
            lookback_bars,
            len(valid_cols),
        )
    prices = prices[valid_cols]

    if len(prices.columns) < 2:
        logger.error("Fewer than 2 assets with sufficient history. Cannot optimize.")
        return 1

    # --- Load market caps (for BL prior) ---
    market_caps = _load_market_caps(list(prices.columns), engine)

    # --- Load regime ---
    regime_label = _load_regime(regime_override, engine)

    # --- Run PortfolioOptimizer ---
    optimizer = PortfolioOptimizer(config=config)
    try:
        result = optimizer.run_all(prices, regime_label=regime_label, tf=tf)
    except Exception as exc:
        logger.error("PortfolioOptimizer.run_all() failed: %s", exc)
        return 1

    condition_number = result.get("condition_number")
    active_optimizer = result.get("active", "hrp")
    logger.info(
        "Optimizer result: active=%s condition_number=%.1f ill_conditioned=%s",
        active_optimizer,
        condition_number or 0.0,
        result.get("ill_conditioned", False),
    )

    # Allocation timestamp = now (UTC)
    alloc_ts = datetime.now(tz=timezone.utc)

    # Config snapshot (strip non-serializable objects)
    config_snapshot: dict[str, Any] = {
        "tf": tf,
        "lookback_calendar_days": lookback_cal,
        "lookback_bars": lookback_bars,
        "regime_label": regime_label,
        "active_optimizer": active_optimizer,
        "n_assets": len(prices.columns),
        "condition_number": float(condition_number) if condition_number else None,
        "use_bl": use_bl,
        "use_sizing": use_sizing,
    }

    total_rows = 0

    # --- Persist all optimizer outputs (mv, cvar, hrp) ---
    for opt_name in ("mv", "cvar", "hrp"):
        weights = result.get(opt_name)
        if weights is None:
            logger.debug("Optimizer %s returned None, skipping persistence.", opt_name)
            continue
        n = _persist_allocations(
            ts=alloc_ts,
            optimizer_name=opt_name,
            weights=weights,
            final_weights=None,
            condition_number=condition_number,
            regime_label=regime_label,
            config_snapshot=config_snapshot,
            engine=engine,
            dry_run=dry_run,
        )
        total_rows += n

    # --- Optional: Black-Litterman ---
    bl_weights: Optional[dict] = None
    if use_bl:
        try:
            from ta_lab2.backtests.bakeoff_orchestrator import (  # noqa: PLC0415
                load_per_asset_ic_weights,
                parse_active_features,
            )

            base_vol = prices.pct_change().std() * (252 / tf_days) ** 0.5

            # Load active feature names from feature_selection.yaml
            try:
                active_features = parse_active_features()
                feature_names = [f["name"] for f in active_features]
            except Exception as exc:
                logger.debug(
                    "Could not parse active features (%s); using empty list.", exc
                )
                feature_names = []

            # Load IC weight overrides from dim_ic_weight_overrides (Phase 87).
            # Loaded once; applied per-asset inside the ic_ir_matrix block below.
            ic_overrides = load_ic_weight_overrides(engine)

            # Load per-asset IC-IR matrix from ic_results (Phase 80 requirement).
            ic_ir_matrix: Optional[pd.DataFrame] = None
            if feature_names:
                try:
                    ic_ir_matrix = load_per_asset_ic_weights(
                        engine=engine,
                        features=feature_names,
                        tf=tf,
                        horizon=1,
                        return_type="arith",
                    )
                except Exception as exc:
                    logger.debug(
                        "load_per_asset_ic_weights failed (%s); will use prior-only path.",
                        exc,
                    )

            if ic_ir_matrix is None or ic_ir_matrix.empty:
                logger.warning(
                    "BL: no per-asset IC-IR data available (ic_results may be empty for tf=%s). "
                    "Falling through to prior-only BL run.",
                    tf,
                )
                # Fallback: prior-only stub (zero IC-IR -> build_views returns empty -> prior only)
                signal_scores = pd.DataFrame(
                    0.0, index=list(prices.columns), columns=["rsi"]
                )
                ic_ir: pd.Series | pd.DataFrame = pd.Series({"rsi": 0.0})
            else:
                # Real per-asset IC-IR loaded from ic_results.
                # Apply IC weight overrides (Phase 87): per-feature multipliers from
                # dim_ic_weight_overrides reduce BL view strength for decayed features.
                if ic_overrides:
                    # Apply overrides column-wise (each column = one feature).
                    # For per-asset overrides: apply the row's asset_id specifically.
                    # For global overrides (asset_id=None): apply to all rows.
                    # We apply global-only overrides uniformly across the matrix columns.
                    col_multipliers = {}
                    for feat in ic_ir_matrix.columns:
                        # Global override (asset_id=None) applies uniformly
                        m = ic_overrides.get((feat, None), 1.0)
                        col_multipliers[feat] = m
                    applied_cols = [f for f, m in col_multipliers.items() if m != 1.0]
                    if applied_cols:
                        ic_ir_matrix = ic_ir_matrix.copy()
                        for feat, mult in col_multipliers.items():
                            if mult != 1.0:
                                ic_ir_matrix[feat] = ic_ir_matrix[feat] * mult
                        logger.info(
                            "Applied IC weight overrides to %d feature(s): %s",
                            len(applied_cols),
                            applied_cols,
                        )

                # Use uniform signal_scores (1.0) so all features contribute equally;
                # per-asset IC-IR differences alone drive view heterogeneity.
                # TODO(Phase 87): Wire real feature values as signal_scores from
                #   features table + ama_multi_tf_u for fully live signal-weighted BL.
                ic_ir = ic_ir_matrix  # pd.DataFrame path in BLAllocationBuilder
                signal_scores = pd.DataFrame(
                    1.0,
                    index=list(prices.columns),
                    columns=ic_ir_matrix.columns,
                )
                logger.info(
                    "BL: loaded per-asset IC-IR for %d assets x %d features (tf=%s). "
                    "Using uniform signal_scores=1.0 (Phase 87 will add real signal values).",
                    len(ic_ir_matrix),
                    len(ic_ir_matrix.columns),
                    tf,
                )

            bl_builder = BLAllocationBuilder(config=config)
            bl_result = bl_builder.run(
                prices=prices,
                market_caps=market_caps,
                signal_scores=signal_scores,
                ic_ir=ic_ir,
                base_vol=base_vol,
                S=result.get("S"),
                tf=tf,
            )
            bl_weights = bl_result.get("bl")
            logger.info(
                "BL allocation computed: %d assets with non-zero weight",
                sum(1 for w in (bl_weights or {}).values() if w > 0),
            )

            n = _persist_allocations(
                ts=alloc_ts,
                optimizer_name="bl",
                weights=bl_weights or {},
                final_weights=None,
                condition_number=condition_number,
                regime_label=regime_label,
                config_snapshot=config_snapshot,
                engine=engine,
                dry_run=dry_run,
            )
            total_rows += n
        except Exception as exc:
            logger.warning("BL allocation failed (%s); skipping.", exc)

    # --- Optional: Bet sizing ---
    if use_sizing:
        try:
            # Use active optimizer weights as basis for sizing
            active_weights = optimizer.get_active_weights(result)
            if active_weights:
                # Use uniform probability = 0.6 (slight edge) and long side = 1
                # when no live signal probabilities are available
                signal_probs = {a: 0.6 for a in active_weights}
                sides = {a: 1 for a in active_weights}

                bet_sizer = BetSizer(config=config)
                sized_weights = bet_sizer.scale_weights(
                    active_weights, signal_probs, sides
                )
                logger.info(
                    "Bet-sized weights computed for %d assets", len(sized_weights)
                )

                n = _persist_allocations(
                    ts=alloc_ts,
                    optimizer_name=f"{active_optimizer}_sized",
                    weights=sized_weights,
                    final_weights=sized_weights,
                    condition_number=condition_number,
                    regime_label=regime_label,
                    config_snapshot=config_snapshot,
                    engine=engine,
                    dry_run=dry_run,
                )
                total_rows += n
        except Exception as exc:
            logger.warning("Bet sizing failed (%s); skipping.", exc)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("PORTFOLIO ALLOCATION REFRESH SUMMARY")
    print(f"{'=' * 60}")
    print(f"  TF              : {tf}")
    print(f"  Assets          : {len(prices.columns)}")
    print(f"  Lookback bars   : {lookback_bars}")
    print(f"  Active optimizer: {active_optimizer}")
    print(f"  Regime          : {regime_label or 'none'}")
    print(
        f"  Condition number: {condition_number:.1f}"
        if condition_number
        else "  Condition number: N/A"
    )
    print(f"  Rows written    : {total_rows}")
    if dry_run:
        print("  [DRY RUN] No data was written.")
    print(f"{'=' * 60}")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Refresh portfolio allocations via MV/CVaR/HRP optimizers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run for all assets on 1D timeframe
  python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids all --tf 1D

  # Dry run to preview without writing
  python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids all --dry-run

  # Specific assets, no BL, no sizing
  python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids 1,52,825 --no-bl --no-sizing

  # Override regime
  python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids all --regime bear
        """,
    )

    p.add_argument(
        "--ids",
        default="all",
        help='Asset IDs (comma-separated) or "all" (default: all)',
    )
    p.add_argument(
        "--tf",
        default="1D",
        help="Timeframe key (default: 1D)",
    )
    p.add_argument(
        "--regime",
        default=None,
        help="Override regime label (default: load from regimes)",
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=None,
        help="Override lookback calendar days (default: from config)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing to DB",
    )
    p.add_argument(
        "--config",
        default="configs/portfolio.yaml",
        help="Path to portfolio.yaml (default: configs/portfolio.yaml)",
    )
    p.add_argument(
        "--no-bl",
        action="store_true",
        help="Skip Black-Litterman allocation",
    )
    p.add_argument(
        "--no-sizing",
        action="store_true",
        help="Skip bet sizing step",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: TARGET_DB_URL env or db_config.env)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = p.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        db_url = _resolve_db_url(args.db_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    return run_refresh(
        ids_arg=args.ids,
        tf=args.tf,
        regime_override=args.regime,
        lookback_override=args.lookback,
        dry_run=args.dry_run,
        config_path=args.config,
        use_bl=not args.no_bl,
        use_sizing=not args.no_sizing,
        db_url=db_url,
    )


if __name__ == "__main__":
    sys.exit(main())
