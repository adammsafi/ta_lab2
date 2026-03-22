"""
refresh_garch_forecasts.py -- Daily GARCH conditional volatility forecast refresh.

For each asset with sufficient return history, fits GARCH/GJR-GARCH/EGARCH/FIGARCH
models and writes 1-day and 5-day ahead conditional volatility forecasts to the
garch_forecasts table.  Model diagnostics are written to garch_diagnostics.

Algorithm per asset
-------------------
1. Load log returns from returns_bars_multi_tf (roll=FALSE, canonical only).
2. Skip if n_obs < --min-obs (default 126).
3. Call fit_all_variants() from garch_engine to fit all four model types.
4. For each model_type:
   a. Insert diagnostics row -> capture run_id via RETURNING.
   b. If converged:
      - Insert forecast rows for horizon 1 and horizon 5 (forecast_source='garch').
   c. If not converged:
      - Carry-forward: look up last converged forecast and apply 5-day half-life decay.
      - If no prior forecast either: fall back to Garman-Klass 21-day rolling vol from
        price_bars_multi_tf (forecast_source='fallback_gk').
      - If OHLC data also unavailable: skip this model for this asset (non-fatal).
5. Update garch_state table.
6. After all assets: REFRESH MATERIALIZED VIEW CONCURRENTLY garch_forecasts_latest.

All writes use temp-table + ON CONFLICT DO UPDATE batch upsert for garch_forecasts.
Diagnostics are INSERT-only (never updated).

Usage::

    python -m ta_lab2.scripts.garch.refresh_garch_forecasts --ids all --tf 1D
    python -m ta_lab2.scripts.garch.refresh_garch_forecasts --ids 1,52 --tf 1D --verbose
    python -m ta_lab2.scripts.garch.refresh_garch_forecasts --ids all --dry-run
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.garch_engine import MODEL_SPECS, GARCHResult, fit_all_variants
from ta_lab2.scripts.garch.garch_state_manager import (
    GARCHStateConfig,
    GARCHStateManager,
)
from ta_lab2.scripts.refresh_utils import parse_ids, resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRINT_PREFIX = "garch_forecast"

#: Half-life (days) for carry-forward decay of a prior convergence failure.
_CARRY_FORWARD_HALF_LIFE = 5.0

#: Number of bars used to compute the GK fallback volatility.
_GK_WINDOW = 21


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _load_asset_ids(engine: Engine, venue_id: int) -> list[int]:
    """Return all distinct asset IDs present in returns_bars_multi_tf for venue_id."""
    sql = text("""
        SELECT DISTINCT id
        FROM public.returns_bars_multi_tf
        WHERE venue_id = :venue_id
        ORDER BY id
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"venue_id": venue_id}).fetchall()
    return [row[0] for row in rows]


def _load_returns(
    engine: Engine,
    asset_id: int,
    venue_id: int,
    tf: str,
) -> pd.DataFrame:
    """Load canonical (roll=FALSE) log-returns for one asset.

    Returns DataFrame with columns: ts (tz-aware), ret_log.
    """
    sql = text("""
        SELECT ts, ret_log
        FROM public.returns_bars_multi_tf
        WHERE id = :id
          AND venue_id = :venue_id
          AND tf = :tf
          AND roll = FALSE
          AND ret_log IS NOT NULL
        ORDER BY ts ASC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={"id": asset_id, "venue_id": venue_id, "tf": tf},
        )
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _load_ohlc_for_gk(
    engine: Engine,
    asset_id: int,
    venue_id: int,
    tf: str,
    window: int = _GK_WINDOW,
) -> pd.DataFrame:
    """Load last ``window`` OHLC bars for a GK fallback volatility estimate.

    Returns DataFrame with columns: open, high, low, close (all float).
    """
    sql = text("""
        SELECT open, high, low, close
        FROM public.price_bars_multi_tf
        WHERE id = :id
          AND venue_id = :venue_id
          AND tf = :tf
          AND roll = FALSE
        ORDER BY ts DESC
        LIMIT :window
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={"id": asset_id, "venue_id": venue_id, "tf": tf, "window": window},
        )
    return df


def _compute_gk_vol(ohlc_df: pd.DataFrame) -> float | None:
    """Compute Garman-Klass volatility (annualised, decimal) from an OHLC DataFrame.

    Returns None if the DataFrame is empty or contains non-positive prices.
    """
    if ohlc_df.empty:
        return None
    o = ohlc_df["open"].astype(float)
    h = ohlc_df["high"].astype(float)
    lo = ohlc_df["low"].astype(float)
    c = ohlc_df["close"].astype(float)
    if (o <= 0).any() or (h <= 0).any() or (lo <= 0).any() or (c <= 0).any():
        return None
    rs = 0.5 * (np.log(h / lo)) ** 2 - (2.0 * np.log(2.0) - 1.0) * (np.log(c / o)) ** 2
    vol_daily = float(np.sqrt(rs.mean()))
    vol_annual = vol_daily * math.sqrt(252.0)
    # Return in decimal (not annualised: a single daily forecast is more useful here)
    # We store 1-day equivalent: annualised / sqrt(252)
    return vol_annual / math.sqrt(252.0)


def _load_latest_converged_forecast(
    engine: Engine,
    asset_id: int,
    venue_id: int,
    tf: str,
    model_type: str,
    horizon: int,
) -> float | None:
    """Look up the most recent converged forecast row for carry-forward."""
    sql = text("""
        SELECT cond_vol
        FROM public.garch_forecasts
        WHERE id = :id
          AND venue_id = :venue_id
          AND tf = :tf
          AND model_type = :model_type
          AND horizon = :horizon
          AND forecast_source = 'garch'
        ORDER BY ts DESC
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(
            sql,
            {
                "id": asset_id,
                "venue_id": venue_id,
                "tf": tf,
                "model_type": model_type,
                "horizon": horizon,
            },
        ).fetchone()
    return float(row[0]) if row else None


def _insert_diagnostics(
    conn: Any,
    asset_id: int,
    venue_id: int,
    ts: datetime,
    tf: str,
    result: GARCHResult,
    refit_reason: str,
) -> int | None:
    """INSERT one diagnostics row and return the generated run_id."""
    sql = text("""
        INSERT INTO public.garch_diagnostics
            (id, venue_id, ts, tf, model_type,
             converged, convergence_flag,
             aic, bic, loglikelihood, ljung_box_pvalue,
             n_obs, refit_reason, error_msg)
        VALUES
            (:id, :venue_id, :ts, :tf, :model_type,
             :converged, :convergence_flag,
             :aic, :bic, :loglikelihood, :ljung_box_pvalue,
             :n_obs, :refit_reason, :error_msg)
        RETURNING run_id
    """)
    params = {
        "id": asset_id,
        "venue_id": venue_id,
        "ts": ts,
        "tf": tf,
        "model_type": result.model_type,
        "converged": result.converged,
        "convergence_flag": result.convergence_flag,
        "aic": result.aic,
        "bic": result.bic,
        "loglikelihood": result.loglikelihood,
        "ljung_box_pvalue": result.ljung_box_pvalue,
        "n_obs": result.n_obs,
        "refit_reason": refit_reason,
        "error_msg": result.error_msg,
    }
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else None


# ---------------------------------------------------------------------------
# Batch upsert helper for garch_forecasts
# ---------------------------------------------------------------------------

_TEMP_TABLE_DDL = """
CREATE TEMP TABLE tmp_garch_forecasts (LIKE public.garch_forecasts INCLUDING DEFAULTS)
ON COMMIT DROP
"""

_UPSERT_SQL = """
INSERT INTO public.garch_forecasts
    (id, venue_id, ts, tf, model_type, horizon, cond_vol, forecast_source, model_run_id)
SELECT
    id, venue_id, ts, tf, model_type, horizon, cond_vol, forecast_source, model_run_id
FROM tmp_garch_forecasts
ON CONFLICT (id, venue_id, ts, tf, model_type, horizon) DO UPDATE SET
    cond_vol        = EXCLUDED.cond_vol,
    forecast_source = EXCLUDED.forecast_source,
    model_run_id    = EXCLUDED.model_run_id,
    created_at      = now()
"""


def _batch_upsert_forecasts(
    conn: Any,
    rows: list[dict[str, Any]],
) -> int:
    """Upsert a list of forecast dicts via temp table.

    Each dict must have keys: id, venue_id, ts, tf, model_type, horizon,
    cond_vol, forecast_source, model_run_id.

    Returns number of rows upserted.
    """
    if not rows:
        return 0

    # Create temp table (ON COMMIT DROP)
    conn.execute(text(_TEMP_TABLE_DDL))

    # Bulk-insert into temp table
    conn.execute(
        text("""
            INSERT INTO tmp_garch_forecasts
                (id, venue_id, ts, tf, model_type, horizon, cond_vol, forecast_source, model_run_id)
            VALUES
                (:id, :venue_id, :ts, :tf, :model_type, :horizon, :cond_vol, :forecast_source, :model_run_id)
        """),
        rows,
    )

    # Upsert from temp into permanent
    result = conn.execute(text(_UPSERT_SQL))
    return result.rowcount


# ---------------------------------------------------------------------------
# Per-asset processing
# ---------------------------------------------------------------------------


def _process_asset(
    engine: Engine,
    state_manager: GARCHStateManager,
    asset_id: int,
    venue_id: int,
    tf: str,
    min_obs: int,
    dry_run: bool,
    verbose: bool,
) -> dict[str, int]:
    """Process one asset: fit GARCH variants, write diagnostics + forecasts.

    Returns dict with keys: skipped, converged, fallback, failed.
    """
    stats = {"skipped": 0, "converged": 0, "fallback": 0, "failed": 0}

    # ------------------------------------------------------------------
    # 1. Load returns
    # ------------------------------------------------------------------
    ret_df = _load_returns(engine, asset_id, venue_id, tf)
    if len(ret_df) < min_obs:
        logger.warning(
            "Asset id=%d venue_id=%d tf=%s: only %d obs (need %d) -- skipping",
            asset_id,
            venue_id,
            tf,
            len(ret_df),
            min_obs,
        )
        stats["skipped"] = len(MODEL_SPECS)
        return stats

    returns_array = ret_df["ret_log"].to_numpy(dtype=float)
    last_ts: datetime = ret_df["ts"].iloc[-1].to_pydatetime()

    if verbose:
        _print(f"id={asset_id}: {len(ret_df)} obs, last_ts={last_ts.date()}")

    if dry_run:
        _print(f"[dry-run] Would fit {len(MODEL_SPECS)} variants for id={asset_id}")
        return stats

    # ------------------------------------------------------------------
    # 2. Fit all variants
    # ------------------------------------------------------------------
    fit_results: dict[str, GARCHResult] = fit_all_variants(
        returns_array, min_obs=min_obs
    )

    # ------------------------------------------------------------------
    # 3. Write diagnostics and forecasts per model_type
    # ------------------------------------------------------------------
    forecast_rows: list[dict[str, Any]] = []

    with engine.begin() as conn:
        for model_type, result in fit_results.items():
            # --- 3a. Insert diagnostics ---
            run_id = _insert_diagnostics(
                conn,
                asset_id=asset_id,
                venue_id=venue_id,
                ts=last_ts,
                tf=tf,
                result=result,
                refit_reason="daily",
            )

            # --- 3b. Build forecast rows ---
            if (
                result.converged
                and result.h1_vol is not None
                and result.h5_vol is not None
            ):
                # Converged: use GARCH forecasts
                forecast_rows.append(
                    {
                        "id": asset_id,
                        "venue_id": venue_id,
                        "ts": last_ts,
                        "tf": tf,
                        "model_type": model_type,
                        "horizon": 1,
                        "cond_vol": float(result.h1_vol),
                        "forecast_source": "garch",
                        "model_run_id": run_id,
                    }
                )
                forecast_rows.append(
                    {
                        "id": asset_id,
                        "venue_id": venue_id,
                        "ts": last_ts,
                        "tf": tf,
                        "model_type": model_type,
                        "horizon": 5,
                        "cond_vol": float(result.h5_vol),
                        "forecast_source": "garch",
                        "model_run_id": run_id,
                    }
                )
                stats["converged"] += 1

            else:
                # Not converged: attempt carry-forward, then GK fallback
                fallback_applied = False

                for horizon in (1, 5):
                    prior_vol = _load_latest_converged_forecast(
                        engine, asset_id, venue_id, tf, model_type, horizon
                    )

                    if prior_vol is not None:
                        # 5-day exponential half-life decay: vol *= exp(-ln2/5)
                        decay = math.exp(-math.log(2.0) / _CARRY_FORWARD_HALF_LIFE)
                        carried_vol = prior_vol * decay
                        forecast_rows.append(
                            {
                                "id": asset_id,
                                "venue_id": venue_id,
                                "ts": last_ts,
                                "tf": tf,
                                "model_type": model_type,
                                "horizon": horizon,
                                "cond_vol": carried_vol,
                                "forecast_source": "carry_forward",
                                "model_run_id": run_id,
                            }
                        )
                        fallback_applied = True
                    else:
                        # GK fallback: load OHLC and compute single-bar GK vol
                        ohlc_df = _load_ohlc_for_gk(engine, asset_id, venue_id, tf)
                        gk_vol = _compute_gk_vol(ohlc_df)

                        if gk_vol is not None:
                            forecast_rows.append(
                                {
                                    "id": asset_id,
                                    "venue_id": venue_id,
                                    "ts": last_ts,
                                    "tf": tf,
                                    "model_type": model_type,
                                    "horizon": horizon,
                                    "cond_vol": gk_vol,
                                    "forecast_source": "fallback_gk",
                                    "model_run_id": run_id,
                                }
                            )
                            fallback_applied = True
                        else:
                            logger.debug(
                                "id=%d tf=%s model=%s horizon=%d: no GK data, skipping forecast",
                                asset_id,
                                tf,
                                model_type,
                                horizon,
                            )
                            stats["failed"] += 1

                if fallback_applied:
                    stats["fallback"] += 1

        # --- 3c. Batch upsert all forecast rows for this asset ---
        if forecast_rows:
            _batch_upsert_forecasts(conn, forecast_rows)

    # ------------------------------------------------------------------
    # 4. Update state for all model types
    # ------------------------------------------------------------------
    for model_type, result in fit_results.items():
        state_manager.update_state(
            id=asset_id,
            venue_id=venue_id,
            tf=tf,
            model_type=model_type,
            converged=result.converged,
            ts=last_ts,
        )

    if verbose:
        n_converged = sum(1 for r in fit_results.values() if r.converged)
        _print(
            f"id={asset_id}: {n_converged}/{len(MODEL_SPECS)} converged, {len(forecast_rows)} forecast rows"
        )

    return stats


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for GARCH forecast refresh."""
    parser = argparse.ArgumentParser(
        description="Daily GARCH conditional volatility forecast refresh.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--ids",
        default="all",
        help="Comma-separated asset IDs or 'all'.",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe to process.",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        dest="venue_id",
        help="Venue ID (1=CMC_AGG).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        dest="db_url",
        help="Database URL override (falls back to db_config.env / TARGET_DB_URL).",
    )
    parser.add_argument(
        "--min-obs",
        type=int,
        default=126,
        dest="min_obs",
        help="Minimum observations required to attempt GARCH fit.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose per-asset output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would execute without running fits or writes.",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=log_level,
    )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    db_url = resolve_db_url(args.db_url)
    engine = create_engine(db_url, poolclass=NullPool, future=True)

    state_config = GARCHStateConfig()
    state_manager = GARCHStateManager(engine, state_config)

    if not args.dry_run:
        state_manager.ensure_state_table()

    # ------------------------------------------------------------------
    # Resolve asset IDs
    # ------------------------------------------------------------------
    requested_ids = parse_ids(args.ids)

    if requested_ids is None:
        asset_ids = _load_asset_ids(engine, args.venue_id)
        _print(f"Loaded {len(asset_ids)} asset IDs for venue_id={args.venue_id}")
    else:
        asset_ids = requested_ids
        _print(f"Processing {len(asset_ids)} specified asset IDs")

    if not asset_ids:
        _print("No asset IDs to process. Exiting.")
        engine.dispose()
        return

    if args.dry_run:
        _print(
            f"[dry-run] Would process {len(asset_ids)} assets, tf={args.tf}, min_obs={args.min_obs}"
        )
        engine.dispose()
        return

    # ------------------------------------------------------------------
    # Process each asset
    # ------------------------------------------------------------------
    t0 = time.time()
    total_stats: dict[str, int] = {
        "skipped": 0,
        "converged": 0,
        "fallback": 0,
        "failed": 0,
    }
    n_errors = 0

    for i, asset_id in enumerate(asset_ids, start=1):
        try:
            asset_stats = _process_asset(
                engine=engine,
                state_manager=state_manager,
                asset_id=asset_id,
                venue_id=args.venue_id,
                tf=args.tf,
                min_obs=args.min_obs,
                dry_run=False,
                verbose=args.verbose,
            )
            for k, v in asset_stats.items():
                total_stats[k] += v

            if i % 50 == 0 or i == len(asset_ids):
                elapsed = time.time() - t0
                _print(
                    f"Progress: {i}/{len(asset_ids)} assets | {elapsed:.0f}s elapsed"
                )

        except Exception as exc:
            logger.error("Failed for asset_id=%d: %s", asset_id, exc, exc_info=True)
            n_errors += 1

    # ------------------------------------------------------------------
    # Refresh materialized view
    # ------------------------------------------------------------------
    _print("Refreshing garch_forecasts_latest materialized view...")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY public.garch_forecasts_latest"
                )
            )
        _print("Materialized view refreshed.")
    except Exception as exc:
        logger.error("Failed to refresh garch_forecasts_latest: %s", exc)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed_total = time.time() - t0
    _print("=" * 60)
    _print(f"GARCH refresh complete in {elapsed_total:.1f}s")
    _print(f"  Assets processed : {len(asset_ids)}")
    _print(f"  Model fits converged : {total_stats['converged']}")
    _print(f"  Carry-forward/GK fallbacks : {total_stats['fallback']}")
    _print(f"  Skipped (insufficient data) : {total_stats['skipped']}")
    _print(f"  Failed : {total_stats['failed']}")
    _print(f"  Errors : {n_errors}")

    engine.dispose()


if __name__ == "__main__":
    main()
