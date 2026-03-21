"""Point-in-time data snapshot collection for drift guard PIT replay."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text


def collect_data_snapshot(
    conn: Any, asset_ids: List[int]
) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Collect the latest data timestamps for each asset across key tables.

    Queries MAX(ts) from price_bars_multi_tf_u, features, and ema_multi_tf_u
    for each asset at the 1D timeframe. Used to record the point-in-time data state
    at paper execution time so drift replay can reconstruct what data was visible.

    Parameters
    ----------
    conn:
        SQLAlchemy connection object (engine connection or session).
    asset_ids:
        List of asset CMC IDs to snapshot.

    Returns
    -------
    dict
        Keys are str(asset_id). Values are dicts with:
        - latest_bar_ts: ISO string of latest bar timestamp, or None
        - latest_feature_ts: ISO string of latest feature timestamp, or None
        - ema_latest_ts: ISO string of latest EMA timestamp, or None
    """
    snapshot: Dict[str, Dict[str, Optional[str]]] = {}

    for asset_id in asset_ids:
        key = str(asset_id)

        # Latest bar timestamp from price bars (1D tf)
        row_bar = conn.execute(
            text(
                "SELECT MAX(ts) AS max_ts "
                "FROM price_bars_multi_tf_u "
                "WHERE id = :asset_id AND tf = '1D' "
                "AND alignment_source = 'multi_tf'"
            ),
            {"asset_id": asset_id},
        ).fetchone()
        latest_bar_ts: Optional[str] = (
            row_bar.max_ts.isoformat()
            if row_bar and row_bar.max_ts is not None
            else None
        )

        # Latest feature timestamp from features (1D tf)
        row_feat = conn.execute(
            text(
                "SELECT MAX(ts) AS max_ts "
                "FROM features "
                "WHERE id = :asset_id AND tf = '1D'"
            ),
            {"asset_id": asset_id},
        ).fetchone()
        latest_feature_ts: Optional[str] = (
            row_feat.max_ts.isoformat()
            if row_feat and row_feat.max_ts is not None
            else None
        )

        # Latest EMA timestamp from ema_multi_tf_u (1D tf)
        row_ema = conn.execute(
            text(
                "SELECT MAX(ts) AS max_ts "
                "FROM ema_multi_tf_u "
                "WHERE id = :asset_id AND tf = '1D'"
            ),
            {"asset_id": asset_id},
        ).fetchone()
        ema_latest_ts: Optional[str] = (
            row_ema.max_ts.isoformat()
            if row_ema and row_ema.max_ts is not None
            else None
        )

        snapshot[key] = {
            "latest_bar_ts": latest_bar_ts,
            "latest_feature_ts": latest_feature_ts,
            "ema_latest_ts": ema_latest_ts,
        }

    return snapshot
