"""Stop calibration: MAE/MFE percentile-based stop and TP level derivation.

Reads MAE (Maximum Adverse Excursion) and MFE (Maximum Favorable Excursion)
from backtest_trades for a given (asset_id, strategy, signal_id) combination
and computes percentile-based stop-loss and take-profit levels.

Stop levels are expressed as absolute decimal fractions (e.g., 0.025 = 2.5%
adverse move). Take-profit levels are positive decimal fractions (e.g., 0.04
= 4% favorable move).

MIN_TRADES_FOR_CALIBRATION gate (default: 30) prevents noisy calibration from
assets with insufficient trade history. Assets below the gate receive no DB
row and continue to use global defaults from portfolio.yaml.

Public API:
    MIN_TRADES_FOR_CALIBRATION  -- minimum trade count gate (constant = 30)
    calibrate_stops_from_mae_mfe(engine, asset_id, strategy, signal_id) -> dict | None
    persist_calibrations(engine, calibrations) -> int

Usage:
    from ta_lab2.analysis.stop_calibration import (
        calibrate_stops_from_mae_mfe,
        persist_calibrations,
        MIN_TRADES_FOR_CALIBRATION,
    )

    result = calibrate_stops_from_mae_mfe(engine, asset_id=1, strategy="rsi", signal_id=3)
    if result is not None:
        result["id"] = 1
        result["strategy"] = "rsi"
        count = persist_calibrations(engine, [result])
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Minimum number of bake-off trades required to compute calibrated stop levels.
# Assets below this gate use global defaults from portfolio.yaml instead.
MIN_TRADES_FOR_CALIBRATION: int = 30


def calibrate_stops_from_mae_mfe(
    engine: Engine,
    asset_id: int,
    strategy: str,
    signal_id: int,
) -> dict[str, Any] | None:
    """Compute stop levels from MAE/MFE percentiles for one (asset, strategy).

    Queries backtest_trades joined to backtest_runs on run_id. Filters by
    asset_id and signal_id and requires non-null mae and mfe values.

    Returns None if fewer than MIN_TRADES_FOR_CALIBRATION rows exist.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        Active SQLAlchemy engine. Use NullPool for batch scripts.
    asset_id : int
        Asset numeric ID (matches dim_assets.id / backtest_runs.asset_id).
    strategy : str
        Strategy name string (e.g. 'rsi', 'ema_crossover', 'ama_kama').
    signal_id : int
        Signal ID from dim_signals / backtest_runs.signal_id.

    Returns
    -------
    dict or None
        Dictionary with keys:
          sl_p25   -- 25th percentile of abs(mae)  (tight stop level)
          sl_p50   -- 50th percentile of abs(mae)  (medium stop level)
          sl_p75   -- 75th percentile of abs(mae)  (wide stop level)
          tp_p50   -- 50th percentile of mfe        (conservative TP)
          tp_p75   -- 75th percentile of mfe        (aggressive TP)
          n_trades -- number of trades used in calibration
        Returns None when trade count < MIN_TRADES_FOR_CALIBRATION.
    """
    sql = text(
        """
        SELECT ABS(bt.mae) AS abs_mae, bt.mfe
        FROM public.backtest_trades bt
        JOIN public.backtest_runs br ON bt.run_id = br.run_id
        WHERE br.asset_id  = :asset_id
          AND br.signal_id = :signal_id
          AND bt.mae IS NOT NULL
          AND bt.mfe IS NOT NULL
        """
    )

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sql, {"asset_id": asset_id, "signal_id": signal_id}
            ).fetchall()
    except Exception as exc:
        logger.error(
            "calibrate_stops_from_mae_mfe: DB query failed "
            "asset_id=%d signal_id=%d strategy=%s: %s",
            asset_id,
            signal_id,
            strategy,
            exc,
        )
        return None

    if len(rows) < MIN_TRADES_FOR_CALIBRATION:
        logger.debug(
            "calibrate_stops_from_mae_mfe: asset_id=%d strategy=%s "
            "has %d trades (< %d minimum) -- skipping calibration",
            asset_id,
            strategy,
            len(rows),
            MIN_TRADES_FOR_CALIBRATION,
        )
        return None

    abs_mae = np.array([float(r[0]) for r in rows], dtype=float)
    mfe = np.array([float(r[1]) for r in rows], dtype=float)

    result: dict[str, Any] = {
        "sl_p25": float(np.nanpercentile(abs_mae, 25)),
        "sl_p50": float(np.nanpercentile(abs_mae, 50)),
        "sl_p75": float(np.nanpercentile(abs_mae, 75)),
        "tp_p50": float(np.nanpercentile(mfe, 50)),
        "tp_p75": float(np.nanpercentile(mfe, 75)),
        "n_trades": len(rows),
    }

    logger.debug(
        "calibrate_stops_from_mae_mfe: asset_id=%d strategy=%s "
        "n_trades=%d sl_p50=%.4f tp_p50=%.4f",
        asset_id,
        strategy,
        result["n_trades"],
        result["sl_p50"],
        result["tp_p50"],
    )

    return result


def persist_calibrations(
    engine: Engine,
    calibrations: list[dict[str, Any]],
) -> int:
    """Upsert calibration rows into stop_calibrations table.

    Uses ON CONFLICT (id, strategy) DO UPDATE to overwrite stale rows.
    Sets calibrated_at = now() on every upsert.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        Active SQLAlchemy engine. Use NullPool for batch scripts.
    calibrations : list[dict]
        List of calibration dicts. Each dict must include:
          id         -- asset numeric ID (INTEGER)
          strategy   -- strategy name (TEXT)
          sl_p25, sl_p50, sl_p75  -- stop-loss percentile levels
          tp_p50, tp_p75          -- take-profit percentile levels
          n_trades   -- trade count used in calibration

    Returns
    -------
    int
        Number of rows written (inserted or updated).
    """
    if not calibrations:
        logger.info("persist_calibrations: no calibrations to write")
        return 0

    upsert_sql = text(
        """
        INSERT INTO public.stop_calibrations
            (id, strategy, sl_p25, sl_p50, sl_p75, tp_p50, tp_p75, n_trades,
             calibrated_at)
        VALUES
            (:id, :strategy, :sl_p25, :sl_p50, :sl_p75, :tp_p50, :tp_p75,
             :n_trades, now())
        ON CONFLICT (id, strategy) DO UPDATE SET
            sl_p25        = EXCLUDED.sl_p25,
            sl_p50        = EXCLUDED.sl_p50,
            sl_p75        = EXCLUDED.sl_p75,
            tp_p50        = EXCLUDED.tp_p50,
            tp_p75        = EXCLUDED.tp_p75,
            n_trades      = EXCLUDED.n_trades,
            calibrated_at = now()
        """
    )

    written = 0
    try:
        with engine.begin() as conn:
            for row in calibrations:
                conn.execute(
                    upsert_sql,
                    {
                        "id": int(row["id"]),
                        "strategy": str(row["strategy"]),
                        "sl_p25": float(row["sl_p25"])
                        if row.get("sl_p25") is not None
                        else None,
                        "sl_p50": float(row["sl_p50"])
                        if row.get("sl_p50") is not None
                        else None,
                        "sl_p75": float(row["sl_p75"])
                        if row.get("sl_p75") is not None
                        else None,
                        "tp_p50": float(row["tp_p50"])
                        if row.get("tp_p50") is not None
                        else None,
                        "tp_p75": float(row["tp_p75"])
                        if row.get("tp_p75") is not None
                        else None,
                        "n_trades": int(row["n_trades"])
                        if row.get("n_trades") is not None
                        else None,
                    },
                )
                written += 1
    except Exception as exc:
        logger.error("persist_calibrations: upsert failed: %s", exc)
        raise

    logger.info("persist_calibrations: wrote %d calibration rows", written)
    return written
