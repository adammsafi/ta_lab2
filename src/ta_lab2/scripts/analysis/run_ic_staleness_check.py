"""
IC Staleness Monitor -- detect alpha decay in active-tier features.

Computes rolling IC-IR at three windows (30/63/126 bars) for each active-tier
feature and each representative asset. Flags decay when BOTH short (30-bar)
AND medium (63-bar) IC-IR fall below the staleness threshold (default 0.7).

On decay detection:
  1. Inserts a weight-halving row into dim_ic_weight_overrides (ON CONFLICT DO NOTHING).
  2. Sends a throttled Telegram WARNING alert (24h cooldown per feature).
  3. Logs the alert to pipeline_alert_log (throttled=True/False).

Return codes:
  0 -- no decay detected (or dry-run completed with no action)
  1 -- error (exception, DB failure)
  2 -- decay detected (one or more features decaying)

Usage:
    python -m ta_lab2.scripts.analysis.run_ic_staleness_check --dry-run --verbose
    python -m ta_lab2.scripts.analysis.run_ic_staleness_check --ids 1,1027
    python -m ta_lab2.scripts.analysis.run_ic_staleness_check --threshold 0.6
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.ic import compute_forward_returns, compute_rolling_ic
from ta_lab2.notifications import telegram
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IC_IR_STALENESS_THRESHOLD = 0.7  # Below this in short+medium = decay
IC_IR_ACTIVE_CUTOFF = 1.0  # Phase 80 active-tier cutoff (reference only)
WINDOWS: dict[str, int] = {"short": 30, "medium": 63, "long": 126}
COOLDOWN_HOURS_IC_DECAY = 24  # Telegram alert cooldown for ic_decay events
MAX_ACTIVE_FEATURES = 20  # Limit to top N by IC-IR mean to reduce runtime
DEFAULT_ASSET_IDS = [1, 1027]  # BTC (id=1), ETH (id=1027)
TIMEOUT_STALENESS = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_close_and_feature(
    conn,
    asset_id: int,
    feature_info: dict,
    tf: str = "1D",
    venue_id: int = 1,
) -> tuple[pd.Series, pd.Series] | None:
    """
    Load (feature_series, close_series) for the given asset, feature, and tf.

    Branches on feature_info["source"]:
      - "features": bar-level feature column in the features table
      - "ama_multi_tf_u": AMA value from ama_multi_tf_u joined with features.close

    Both series are indexed by UTC-aware timestamps.
    Returns None if the feature column does not exist or data is empty.

    venue_id filter is required: features/ama tables have venue_id in PK;
    without it, multiple venues produce duplicate ts rows causing rolling failures.
    """
    feature_name = feature_info["name"]
    source = feature_info.get("source", "features")

    if source == "ama_multi_tf_u":
        return _load_ama_feature(conn, asset_id, feature_info, tf, venue_id)

    # --- Branch A: bar-level feature from features table ---
    # Verify column exists in features table
    try:
        col_check = conn.execute(
            text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = 'features'
                  AND column_name  = :col
            """),
            {"col": feature_name},
        ).fetchone()
    except Exception as exc:
        logger.warning("Column check failed for %s: %s", feature_name, exc)
        return None

    if col_check is None:
        logger.debug(
            "Feature column '%s' not found in features table -- skipping", feature_name
        )
        return None

    sql = text(
        f"SELECT ts, {feature_name}, close "  # noqa: S608 -- column validated above
        f"FROM public.features "
        f"WHERE id = :id AND tf = :tf AND venue_id = :venue_id "
        f"ORDER BY ts"
    )

    try:
        df = pd.read_sql(
            sql,
            conn,
            params={"id": asset_id, "tf": tf, "venue_id": venue_id},
        )
    except Exception as exc:
        logger.warning(
            "Failed to load feature '%s' for asset_id=%d: %s",
            feature_name,
            asset_id,
            exc,
        )
        return None

    if df.empty:
        logger.debug(
            "No data for feature='%s' asset_id=%d tf=%s -- skipping",
            feature_name,
            asset_id,
            tf,
        )
        return None

    # CRITICAL: fix mixed-tz-offset object dtype from pd.read_sql on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()

    return df[feature_name].astype(float), df["close"].astype(float)


def _load_ama_feature(
    conn,
    asset_id: int,
    feature_info: dict,
    tf: str = "1D",
    venue_id: int = 1,
) -> tuple[pd.Series, pd.Series] | None:
    """
    Load AMA feature value + close from ama_multi_tf_u joined with features.

    CRITICAL filters: alignment_source='multi_tf', roll=FALSE, venue_id.
    Missing any of these causes duplicate rows that break rolling IC computation.
    """
    feature_name = feature_info["name"]
    indicator = feature_info["indicator"]
    params_hash = feature_info["params_hash"]

    sql = text("""
        SELECT a.ts, a.ama AS feature_value, f.close
        FROM public.ama_multi_tf_u a
        INNER JOIN public.features f
            ON f.id = a.id AND f.ts = a.ts AND f.tf = a.tf AND f.venue_id = a.venue_id
        WHERE a.id = :asset_id
          AND a.venue_id = :venue_id
          AND a.tf = :tf
          AND a.indicator = :indicator
          AND LEFT(a.params_hash, 8) = :params_hash
          AND a.alignment_source = 'multi_tf'
          AND a.roll = FALSE
        ORDER BY a.ts
    """)

    try:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "asset_id": asset_id,
                "venue_id": venue_id,
                "tf": tf,
                "indicator": indicator,
                "params_hash": params_hash,
            },
        )
    except Exception as exc:
        logger.warning(
            "Failed to load AMA feature '%s' for asset_id=%d: %s",
            feature_name,
            asset_id,
            exc,
        )
        return None

    if df.empty:
        logger.debug(
            "No data for AMA feature='%s' (indicator=%s, hash=%s) asset_id=%d tf=%s -- skipping",
            feature_name,
            indicator,
            params_hash,
            asset_id,
            tf,
        )
        return None

    # CRITICAL: fix mixed-tz-offset object dtype from pd.read_sql on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()

    logger.debug(
        "Loaded AMA feature='%s' from ama_multi_tf_u: %d rows (asset_id=%d)",
        feature_name,
        len(df),
        asset_id,
    )

    return df["feature_value"].astype(float), df["close"].astype(float)


# ---------------------------------------------------------------------------
# Multi-window IC-IR computation
# ---------------------------------------------------------------------------


def _compute_multiwindow_ic_ir(
    feature: pd.Series,
    close: pd.Series,
    horizon: int = 1,
) -> dict[str, float]:
    """
    Compute IC-IR at three windows (short=30, medium=63, long=126 bars).

    Uses compute_rolling_ic() from ta_lab2.analysis.ic at horizon=1 (1-bar
    forward return is the standard for daily staleness checks).

    Returns dict with keys: 'short', 'medium', 'long'. Values are IC-IR floats
    (may be NaN if insufficient data).
    """
    fwd_ret = compute_forward_returns(close, horizon=horizon, log=False)

    # Align feature and forward returns on common index, drop NaN
    combined = pd.concat([feature, fwd_ret], axis=1).dropna()
    if len(combined) < WINDOWS["long"] + 5:
        logger.debug(
            "Insufficient data for multi-window IC-IR: n=%d < %d",
            len(combined),
            WINDOWS["long"] + 5,
        )
        return {"short": float("nan"), "medium": float("nan"), "long": float("nan")}

    feat_clean = combined.iloc[:, 0]
    fwd_clean = combined.iloc[:, 1]

    results: dict[str, float] = {}
    for window_name, window_size in WINDOWS.items():
        if len(feat_clean) < window_size + 5:
            results[window_name] = float("nan")
            continue
        try:
            _, ic_ir, _ = compute_rolling_ic(feat_clean, fwd_clean, window=window_size)
            results[window_name] = float("nan") if ic_ir is None else float(ic_ir)
        except Exception as exc:
            logger.warning(
                "compute_rolling_ic failed for window=%s: %s", window_name, exc
            )
            results[window_name] = float("nan")

    return results


# ---------------------------------------------------------------------------
# Decay detection
# ---------------------------------------------------------------------------


def _is_decaying(
    ic_ir_by_window: dict[str, float],
    threshold: float,
) -> bool:
    """
    Return True when BOTH short AND medium IC-IR are below threshold.

    Guard: if either value is NaN (insufficient data), return False -- do NOT
    flag as decaying when data is insufficient.
    """
    short_ir = ic_ir_by_window.get("short", float("nan"))
    medium_ir = ic_ir_by_window.get("medium", float("nan"))

    # Guard: insufficient data
    if math.isnan(short_ir) or math.isnan(medium_ir):
        return False

    return short_ir < threshold and medium_ir < threshold


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------


def _write_weight_override(
    engine,
    feature: str,
    asset_id: int,
    short_ir: float,
    medium_ir: float,
    threshold: float,
    dry_run: bool = False,
) -> bool:
    """
    Insert a weight-halving row into dim_ic_weight_overrides.

    Uses ON CONFLICT DO NOTHING -- idempotent, no compound halving on re-runs.
    Returns True if insert was executed (not necessarily inserted -- conflict
    is silently ignored). Returns False on error.
    """
    reason = f"IC decay: short={short_ir:.2f}, medium={medium_ir:.2f} < {threshold}"
    if dry_run:
        logger.info(
            "[DRY-RUN] Would insert dim_ic_weight_overrides: feature=%s asset_id=%d reason=%s",
            feature,
            asset_id,
            reason,
        )
        return True

    sql = text("""
        INSERT INTO public.dim_ic_weight_overrides
            (feature, asset_id, multiplier, reason, created_at)
        VALUES
            (:feature, :asset_id, 0.5, :reason, now())
        ON CONFLICT ON CONSTRAINT uq_ic_weight_overrides DO NOTHING
    """)
    try:
        with engine.begin() as conn:
            conn.execute(
                sql, {"feature": feature, "asset_id": asset_id, "reason": reason}
            )
        logger.info(
            "dim_ic_weight_overrides: upserted feature=%s asset_id=%d (multiplier=0.5)",
            feature,
            asset_id,
        )
        return True
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "dim_ic_weight_overrides insert failed (migration pending?): %s", exc
        )
        return False
    except Exception as exc:
        logger.error("Unexpected error writing weight override: %s", exc)
        return False


def _is_alert_throttled(
    engine,
    alert_type: str,
    alert_key: str,
    cooldown_hours: int,
) -> bool:
    """
    Return True if an un-throttled alert of this type+key was sent within
    the cooldown window. Queries pipeline_alert_log.

    Gracefully returns False on DB errors (missing table, connection issues).
    """
    sql = text("""
        SELECT 1
        FROM public.pipeline_alert_log
        WHERE alert_type = :alert_type
          AND alert_key  = :alert_key
          AND sent_at    > NOW() - (INTERVAL '1 hour' * :hours)
          AND throttled  = FALSE
        LIMIT 1
    """)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sql,
                {
                    "alert_type": alert_type,
                    "alert_key": alert_key,
                    "hours": cooldown_hours,
                },
            ).fetchone()
        return row is not None
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "pipeline_alert_log not accessible (migration pending?): %s", exc
        )
        return False
    except Exception as exc:
        logger.error("Error checking alert throttle: %s", exc)
        return False


def _log_alert(
    engine,
    alert_type: str,
    alert_key: str,
    severity: str,
    message_preview: str,
    throttled: bool,
    dry_run: bool = False,
) -> None:
    """
    Persist an alert record to pipeline_alert_log.

    Logs even when throttled=True so the audit trail is complete.
    """
    if dry_run:
        logger.info(
            "[DRY-RUN] Would log pipeline_alert_log: type=%s key=%s throttled=%s",
            alert_type,
            alert_key,
            throttled,
        )
        return

    sql = text("""
        INSERT INTO public.pipeline_alert_log
            (alert_type, alert_key, severity, message_preview, sent_at, throttled)
        VALUES
            (:alert_type, :alert_key, :severity, :message_preview, now(), :throttled)
    """)
    try:
        with engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "alert_type": alert_type,
                    "alert_key": alert_key,
                    "severity": severity,
                    "message_preview": message_preview[:200]
                    if message_preview
                    else None,
                    "throttled": throttled,
                },
            )
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "Could not write to pipeline_alert_log (migration pending?): %s", exc
        )
    except Exception as exc:
        logger.error("Failed to log alert to pipeline_alert_log: %s", exc)


# ---------------------------------------------------------------------------
# Telegram alert dispatch
# ---------------------------------------------------------------------------


def _send_decay_alert(
    engine,
    feature: str,
    asset_id: int,
    ic_ir_by_window: dict[str, float],
    dry_run: bool = False,
) -> None:
    """
    Send a throttled Telegram WARNING alert for IC decay.

    Checks pipeline_alert_log for recent ic_decay alert for this feature
    within COOLDOWN_HOURS_IC_DECAY. Sends only if not throttled.
    Always logs to pipeline_alert_log.
    """
    alert_type = "ic_decay"
    alert_key = feature  # one throttle bucket per feature (across all assets)
    severity = "warning"

    short_ir = ic_ir_by_window.get("short", float("nan"))
    medium_ir = ic_ir_by_window.get("medium", float("nan"))
    long_ir = ic_ir_by_window.get("long", float("nan"))

    short_str = f"{short_ir:.2f}" if not math.isnan(short_ir) else "N/A"
    medium_str = f"{medium_ir:.2f}" if not math.isnan(medium_ir) else "N/A"
    long_str = f"{long_ir:.2f}" if not math.isnan(long_ir) else "N/A"

    title = "IC Decay Warning"
    message = (
        f"Feature: {feature}\n"
        f"Asset ID: {asset_id}\n\n"
        f"IC-IR by window:\n"
        f"  Short  (30-bar):  {short_str}\n"
        f"  Medium (63-bar):  {medium_str}\n"
        f"  Long   (126-bar): {long_str}\n\n"
        f"Threshold: {IC_IR_STALENESS_THRESHOLD}\n"
        f"Action: BL weight halved (multiplier=0.5)"
    )
    message_preview = (
        f"feature={feature} short={short_str} medium={medium_str} long={long_str}"
    )

    throttled = _is_alert_throttled(
        engine, alert_type, alert_key, COOLDOWN_HOURS_IC_DECAY
    )

    if throttled:
        logger.info(
            "IC decay alert throttled: feature=%s (24h cooldown active)", feature
        )
        _log_alert(
            engine,
            alert_type,
            alert_key,
            severity,
            message_preview,
            throttled=True,
            dry_run=dry_run,
        )
        return

    # Not throttled -- attempt to send
    if dry_run:
        logger.info(
            "[DRY-RUN] Would send Telegram IC decay alert for feature=%s", feature
        )
        _log_alert(
            engine,
            alert_type,
            alert_key,
            severity,
            message_preview,
            throttled=False,
            dry_run=True,
        )
        return

    sent = False
    if not telegram.is_configured():
        logger.warning(
            "Telegram not configured -- skipping IC decay alert for feature=%s", feature
        )
    else:
        try:
            sent = telegram.send_alert(title, message, severity=severity)
        except Exception as exc:
            logger.error("Telegram send failed for IC decay alert: %s", exc)

    _log_alert(
        engine,
        alert_type,
        alert_key,
        severity,
        message_preview,
        throttled=not sent,
        dry_run=False,
    )


# ---------------------------------------------------------------------------
# Main monitor class
# ---------------------------------------------------------------------------


class ICStalenessMonitor:
    """
    Monitor active-tier features for IC staleness (alpha decay).

    Computes multi-window IC-IR (short=30, medium=63, long=126 bars) for
    each (feature, asset) pair. Flags decay when both short AND medium IC-IR
    are below the staleness threshold. On decay: halves BL weight and sends
    a throttled Telegram alert.
    """

    def __init__(
        self,
        engine,
        asset_ids: list[int],
        threshold: float = IC_IR_STALENESS_THRESHOLD,
        tf: str = "1D",
        dry_run: bool = False,
    ) -> None:
        self._engine = engine
        self._asset_ids = asset_ids
        self._threshold = threshold
        self._tf = tf
        self._dry_run = dry_run

    def run(self) -> int:
        """
        Execute the staleness check across all active features and assets.

        Returns:
            0 -- no decay detected
            2 -- one or more (feature, asset) pairs are decaying
        """
        try:
            from ta_lab2.backtests.bakeoff_orchestrator import parse_active_features

            active_features = parse_active_features()
        except Exception as exc:
            logger.error("Failed to parse active features: %s", exc)
            return 1

        active_features = active_features[:MAX_ACTIVE_FEATURES]
        if not active_features:
            logger.error("No active features loaded -- cannot run staleness check")
            return 1

        ama_count = sum(1 for f in active_features if f["source"] == "ama_multi_tf_u")
        bar_count = len(active_features) - ama_count
        logger.info(
            "ICStalenessMonitor: checking %d features (%d AMA, %d bar-level) x %d assets",
            len(active_features),
            ama_count,
            bar_count,
            len(self._asset_ids),
        )

        any_decay = False

        for asset_id in self._asset_ids:
            logger.info("--- Checking asset_id=%d ---", asset_id)
            try:
                with self._engine.connect() as conn:
                    for feature_info in active_features:
                        result = self._check_one(conn, feature_info, asset_id)
                        if result:
                            any_decay = True
            except Exception as exc:
                logger.error("Unexpected error for asset_id=%d: %s", asset_id, exc)
                # Continue with next asset (non-fatal per-asset failure)

        if any_decay:
            logger.warning(
                "IC decay detected in one or more features -- see dim_ic_weight_overrides"
            )
            return 2

        logger.info("ICStalenessMonitor: no decay detected across all checked features")
        return 0

    def _check_one(self, conn, feature_info: dict, asset_id: int) -> bool:
        """
        Check one (feature, asset) pair.

        Args:
            feature_info: dict with keys name, indicator, params_hash, source.
            asset_id: asset to check.

        Returns True if decay detected (and override/alert dispatched).
        Returns False if no decay, insufficient data, or feature not found.
        """
        feature_name = feature_info["name"]
        data = _load_close_and_feature(conn, asset_id, feature_info, tf=self._tf)
        if data is None:
            logger.debug(
                "Skipping feature='%s' asset_id=%d -- no data", feature_name, asset_id
            )
            return False

        feature_series, close_series = data

        if len(feature_series.dropna()) < WINDOWS["long"] + 5:
            logger.debug(
                "Insufficient data for feature='%s' asset_id=%d (n=%d < %d)",
                feature_name,
                asset_id,
                len(feature_series.dropna()),
                WINDOWS["long"] + 5,
            )
            return False

        ic_ir_by_window = _compute_multiwindow_ic_ir(feature_series, close_series)

        short_ir = ic_ir_by_window.get("short", float("nan"))
        medium_ir = ic_ir_by_window.get("medium", float("nan"))
        long_ir = ic_ir_by_window.get("long", float("nan"))

        short_str = f"{short_ir:.3f}" if not math.isnan(short_ir) else "NaN"
        medium_str = f"{medium_ir:.3f}" if not math.isnan(medium_ir) else "NaN"
        long_str = f"{long_ir:.3f}" if not math.isnan(long_ir) else "NaN"

        logger.info(
            "feature='%s' asset_id=%d | short=%s medium=%s long=%s (threshold=%.2f)",
            feature_name,
            asset_id,
            short_str,
            medium_str,
            long_str,
            self._threshold,
        )

        is_decaying = _is_decaying(ic_ir_by_window, self._threshold)

        if not is_decaying:
            return False

        logger.warning(
            "IC DECAY detected: feature='%s' asset_id=%d | short=%s medium=%s < %.2f",
            feature_name,
            asset_id,
            short_str,
            medium_str,
            self._threshold,
        )

        # 1. Write weight override (idempotent)
        _write_weight_override(
            self._engine,
            feature=feature_name,
            asset_id=asset_id,
            short_ir=short_ir,
            medium_ir=medium_ir,
            threshold=self._threshold,
            dry_run=self._dry_run,
        )

        # 2. Throttled Telegram alert + pipeline_alert_log
        _send_decay_alert(
            self._engine,
            feature=feature_name,
            asset_id=asset_id,
            ic_ir_by_window=ic_ir_by_window,
            dry_run=self._dry_run,
        )

        return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the IC staleness check CLI."""
    parser = argparse.ArgumentParser(
        prog="run_ic_staleness_check",
        description=(
            "Detect alpha decay in active-tier features via multi-window IC-IR comparison."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides db_config.env and TARGET_DB_URL).",
    )
    parser.add_argument(
        "--ids",
        default=",".join(str(i) for i in DEFAULT_ASSET_IDS),
        help="Comma-separated asset IDs to check (default: 1,1027 for BTC+ETH).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=IC_IR_STALENESS_THRESHOLD,
        help=f"IC-IR staleness threshold (default: {IC_IR_STALENESS_THRESHOLD}).",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe to evaluate (default: 1D).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Compute but do not write overrides or send alerts.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        level=log_level,
        stream=sys.stdout,
    )

    # Parse asset IDs
    try:
        asset_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    except ValueError as exc:
        logger.error("Invalid --ids format: %s", exc)
        return 1

    if not asset_ids:
        logger.error("No valid asset IDs provided via --ids")
        return 1

    # Resolve DB URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as exc:
        logger.error("Cannot resolve database URL: %s", exc)
        return 1

    # Create engine (NullPool for scripts -- no persistent connection pool)
    try:
        engine = create_engine(db_url, poolclass=NullPool)
    except Exception as exc:
        logger.error("Failed to create DB engine: %s", exc)
        return 1

    # Run the monitor
    monitor = ICStalenessMonitor(
        engine=engine,
        asset_ids=asset_ids,
        threshold=args.threshold,
        tf=args.tf,
        dry_run=args.dry_run,
    )

    try:
        return_code = monitor.run()
    except Exception as exc:
        logger.error("ICStalenessMonitor failed unexpectedly: %s", exc)
        return 1

    return return_code


if __name__ == "__main__":
    sys.exit(main())
