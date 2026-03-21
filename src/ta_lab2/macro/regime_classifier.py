"""regime_classifier.py

MacroRegimeClassifier: Rule-based 4-dimensional macro regime labeler.

Reads daily macro features from fred.fred_macro_features (Phase 65-66) and
produces composite regime labels with hysteresis-filtered per-dimension
classifications.  Results are upserted into macro_regimes.

Dimensions:
    1. monetary_policy -- Hiking / Holding / Cutting
    2. liquidity       -- Strongly_Expanding / Expanding / Neutral /
                          Contracting / Strongly_Contracting
    3. risk_appetite   -- RiskOff / Neutral / RiskOn
    4. carry           -- Unwind / Stress / Stable

Composite key: monetary-liquidity-risk-carry (fixed order, dash-separated).
Bucketed macro_state: favorable / constructive / neutral / cautious / adverse.

All numeric thresholds live in configs/macro_regime_config.yaml (MREG-08).
Named profiles (default / conservative / aggressive) allow sensitivity tuning.
Hysteresis state persists to macro_hysteresis_state for incremental resume.

Phase 67, Plan 02.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.regimes.hysteresis import HysteresisTracker

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Warmup window for incremental watermark lookback (days).
# Must cover at least the hysteresis hold period + reasonable margin.
WARMUP_DAYS = 60

_DIMENSIONS = ["monetary_policy", "liquidity", "risk_appetite", "carry"]

# Required columns from Phase 66 per dimension -- fail hard if absent.
_REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "monetary_policy": ["dff", "fed_regime_trajectory"],
    "liquidity": ["net_liquidity_365d_zscore", "net_liquidity_trend"],
    "risk_appetite": ["vixcls", "hy_oas_30d_zscore", "nfci_level"],
    "carry": ["dexjpus_daily_zscore", "dexjpus_20d_vol", "us_jp_rate_spread"],
}


# ---------------------------------------------------------------------------
# Project root & YAML loader
# ---------------------------------------------------------------------------


try:
    from ta_lab2.config import project_root  # type: ignore[import]
except Exception:  # pragma: no cover

    def project_root() -> Path:
        p = Path(__file__).resolve()
        for parent in [p, *p.parents]:
            if (parent / "pyproject.toml").exists():
                return parent
        return Path(__file__).resolve().parents[3]


def _default_config_path() -> Path:
    """Return path to configs/macro_regime_config.yaml."""
    return project_root() / "configs" / "macro_regime_config.yaml"


def load_macro_regime_config(
    yaml_path: Optional[str | os.PathLike[str]] = None,
) -> Dict[str, Any]:
    """Load macro regime classifier configuration from YAML.

    Parameters
    ----------
    yaml_path:
        Optional explicit path.  Defaults to <repo>/configs/macro_regime_config.yaml.

    Returns
    -------
    dict with keys: active_profile, hysteresis, profiles, tighten_labels,
    macro_state_rules.

    Raises
    ------
    FileNotFoundError if config file does not exist.
    RuntimeError if PyYAML is not installed.
    """
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required for macro regime config. "
            "Install with: pip install pyyaml"
        )

    path = Path(yaml_path) if yaml_path is not None else _default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"Macro regime config not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        config: Dict[str, Any] = yaml.safe_load(f) or {}

    # Validate required top-level keys
    for key in ("active_profile", "hysteresis", "profiles", "macro_state_rules"):
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")

    return config


def _config_version_hash(yaml_path: Optional[str | os.PathLike[str]] = None) -> str:
    """Compute MD5 hash (truncated to 8 chars) of the YAML config content."""
    path = Path(yaml_path) if yaml_path is not None else _default_config_path()
    content = path.read_bytes()
    return hashlib.md5(content).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Numpy / pandas type safety (copied from refresh_macro_features.py)
# ---------------------------------------------------------------------------


def _to_python(v: Any) -> Any:
    """Convert numpy scalars and NaN to native Python types for psycopg2 safety."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (v != v):  # NaN check without math import
        return None
    return v


def _sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Convert DataFrame values to native Python types safe for psycopg2."""
    df = df.where(df.notna(), other=None)  # type: ignore[arg-type]
    for col in df.columns:
        if df[col].dtype == object:
            continue
        try:
            df[col] = df[col].apply(_to_python)
        except Exception:  # noqa: BLE001
            pass
    return df


# ---------------------------------------------------------------------------
# Dimension labelers
# ---------------------------------------------------------------------------


def _is_nan(v: Any) -> bool:
    """Check if a value is NaN or None."""
    if v is None:
        return True
    try:
        return v != v  # NaN != NaN
    except (TypeError, ValueError):
        return False


def _label_monetary(row: pd.Series, thresholds: Dict[str, Any]) -> Optional[str]:
    """Label monetary policy dimension: Hiking / Holding / Cutting.

    Primary: fed_regime_trajectory from Phase 66.
    Fallback: dff 90d change vs thresholds.
    """
    trajectory = row.get("fed_regime_trajectory")

    if not _is_nan(trajectory):
        # Normalize to title case
        traj_str = str(trajectory).strip().lower()
        label_map = {"hiking": "Hiking", "holding": "Holding", "cutting": "Cutting"}
        if traj_str in label_map:
            return label_map[traj_str]

    # Fallback: dff 90d change
    dff_90d_change = row.get("dff_90d_change")
    if _is_nan(dff_90d_change):
        return None

    hiking_thresh = thresholds["hiking_threshold"]
    cutting_thresh = thresholds["cutting_threshold"]

    if dff_90d_change > hiking_thresh:
        return "Hiking"
    elif dff_90d_change < cutting_thresh:
        return "Cutting"
    return "Holding"


def _label_liquidity(row: pd.Series, thresholds: Dict[str, Any]) -> Optional[str]:
    """Label liquidity dimension using net_liquidity_365d_zscore and trend.

    Z-score extremes override the base trend label.
    """
    zscore = row.get("net_liquidity_365d_zscore")
    trend = row.get("net_liquidity_trend")

    zscore_nan = _is_nan(zscore)
    trend_nan = _is_nan(trend)

    if zscore_nan and trend_nan:
        return None

    # Z-score extremes override
    if not zscore_nan:
        if zscore > thresholds["strongly_expanding_z"]:
            return "Strongly_Expanding"
        if zscore < thresholds["strongly_contracting_z"]:
            return "Strongly_Contracting"

    # Base: trend
    if not trend_nan:
        trend_str = str(trend).strip().lower()
        if trend_str == "expanding":
            return "Expanding"
        if trend_str == "contracting":
            return "Contracting"

    return "Neutral"


def _label_risk_appetite(row: pd.Series, thresholds: Dict[str, Any]) -> Optional[str]:
    """Label risk appetite dimension: RiskOff / Neutral / RiskOn.

    RiskOff if ANY risk indicator breaches its threshold.
    RiskOn if ALL risk indicators are below their thresholds.
    """
    vix = row.get("vixcls")
    if _is_nan(vix):
        return None

    hy_oas_z = row.get("hy_oas_30d_zscore")
    nfci = row.get("nfci_level")

    # RiskOff: any indicator breaches
    if vix > thresholds["vix_risk_off"]:
        return "RiskOff"
    if not _is_nan(hy_oas_z) and hy_oas_z > thresholds["hy_oas_z_risk_off"]:
        return "RiskOff"
    if not _is_nan(nfci) and nfci > thresholds["nfci_risk_off"]:
        return "RiskOff"

    # RiskOn: all available indicators below thresholds
    vix_on = vix < thresholds["vix_risk_on"]
    hy_on = _is_nan(hy_oas_z) or hy_oas_z < thresholds["hy_oas_z_risk_on"]
    nfci_on = _is_nan(nfci) or nfci < thresholds["nfci_risk_on"]

    if vix_on and hy_on and nfci_on:
        return "RiskOn"

    return "Neutral"


def _label_carry(row: pd.Series, thresholds: Dict[str, Any]) -> Optional[str]:
    """Label carry trade dimension: Unwind / Stress / Stable.

    Unwind: extreme JPY zscore + narrowing rate spread.
    Stress: elevated 20d vol.
    """
    daily_z = row.get("dexjpus_daily_zscore")
    if _is_nan(daily_z):
        return None

    vol_20d = row.get("dexjpus_20d_vol")
    spread_5d_change = row.get("us_jp_rate_spread_5d_change")

    # Unwind check
    if not _is_nan(spread_5d_change):
        if (
            daily_z > thresholds["unwind_daily_zscore"]
            and spread_5d_change < thresholds["spread_narrowing_5d"]
        ):
            return "Unwind"

    # Stress check: direct comparison of absolute vol in %
    if not _is_nan(vol_20d):
        if vol_20d > thresholds["stress_vol_threshold"]:
            return "Stress"

    return "Stable"


_LABELERS = {
    "monetary_policy": _label_monetary,
    "liquidity": _label_liquidity,
    "risk_appetite": _label_risk_appetite,
    "carry": _label_carry,
}


# ---------------------------------------------------------------------------
# Composite key and macro state bucketing
# ---------------------------------------------------------------------------


def _build_composite_key(labels: Dict[str, Optional[str]]) -> str:
    """Build composite regime key in fixed dimension order.

    None dimensions become "Unknown".
    Format: monetary-liquidity-risk-carry
    """
    parts = []
    for dim in _DIMENSIONS:
        val = labels.get(dim)
        parts.append(val if val is not None else "Unknown")
    return "-".join(parts)


def _determine_macro_state(
    regime_key: str,
    rules: Dict[str, Any],
) -> str:
    """Map composite key to bucketed macro state.

    Uses prefix matching: a rule like "Cutting-Expanding-RiskOn" matches
    "Cutting-Expanding-RiskOn-Stable" because the carry dimension is the
    last component and rules specify the first 3 dimensions.

    Checks adverse/cautious FIRST for conservative bias.
    """
    # Priority order: adverse -> cautious -> favorable -> constructive -> neutral
    for state in ("adverse", "cautious", "favorable", "constructive", "neutral"):
        patterns = rules.get(state, [])
        for pattern in patterns:
            if regime_key.startswith(pattern):
                return state

    return str(rules.get("_default", "neutral"))


# ---------------------------------------------------------------------------
# Hysteresis DB persistence
# ---------------------------------------------------------------------------


def _load_hysteresis_state(
    engine: Engine,
    profile: str,
    tracker: HysteresisTracker,
) -> None:
    """Load hysteresis state from macro_hysteresis_state into tracker."""
    sql = text(
        "SELECT dimension, current_label, pending_label, pending_count "
        "FROM macro_hysteresis_state "
        "WHERE profile = :profile"
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"profile": profile}).fetchall()
    except Exception:  # noqa: BLE001
        logger.warning("Could not load hysteresis state -- starting fresh")
        return

    for row in rows:
        dim, current, pending, count = row
        if current is not None:
            tracker._current[dim] = current
            tracker._pending[dim] = pending
            tracker._pending_count[dim] = count if count else 0
            logger.debug(
                "Loaded hysteresis state: %s = %s (pending=%s, count=%d)",
                dim,
                current,
                pending,
                count or 0,
            )


def _save_hysteresis_state(
    engine: Engine,
    profile: str,
    tracker: HysteresisTracker,
) -> None:
    """Persist hysteresis state to macro_hysteresis_state via upsert."""
    upsert_sql = text(
        "INSERT INTO macro_hysteresis_state "
        "(profile, dimension, current_label, pending_label, pending_count, updated_at) "
        "VALUES (:profile, :dimension, :current_label, :pending_label, :pending_count, now()) "
        "ON CONFLICT (profile, dimension) DO UPDATE SET "
        "current_label = EXCLUDED.current_label, "
        "pending_label = EXCLUDED.pending_label, "
        "pending_count = EXCLUDED.pending_count, "
        "updated_at = now()"
    )

    try:
        with engine.begin() as conn:
            for dim in _DIMENSIONS:
                current = tracker._current.get(dim)
                pending = tracker._pending.get(dim)
                count = tracker._pending_count.get(dim, 0)
                conn.execute(
                    upsert_sql,
                    {
                        "profile": profile,
                        "dimension": dim,
                        "current_label": current,
                        "pending_label": pending,
                        "pending_count": count,
                    },
                )
        logger.info("Saved hysteresis state for profile=%s", profile)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to save hysteresis state")


# ---------------------------------------------------------------------------
# Tightening helper for macro dimensions
# ---------------------------------------------------------------------------


def _is_macro_tightening(
    dimension: str,
    new_label: Optional[str],
    tighten_labels: Dict[str, List[str]],
) -> bool:
    """Determine if a dimension label change is tightening (risk-reducing).

    Tightening labels are defined in YAML config per dimension.
    Transitioning TO a tighten label is tightening (bypass hold).
    Transitioning FROM a tighten label is loosening (apply hold).
    """
    if new_label is None:
        return False
    dim_tighten = tighten_labels.get(dimension, [])
    return new_label in dim_tighten


# ---------------------------------------------------------------------------
# MacroRegimeClassifier
# ---------------------------------------------------------------------------


class MacroRegimeClassifier:
    """Rule-based 4-dimensional macro regime classifier.

    Reads daily macro features from fred.fred_macro_features, classifies
    each day into per-dimension labels, applies hysteresis to prevent
    flapping, computes composite regime keys, and upserts results into
    macro_regimes.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    config:
        Optional config dict (from load_macro_regime_config).
        If None, loads from default YAML path.
    profile:
        Override active profile.  If None, uses config's active_profile.

    Examples
    --------
    >>> from ta_lab2.macro.regime_classifier import MacroRegimeClassifier
    >>> classifier = MacroRegimeClassifier(engine)
    >>> n_rows = classifier.classify()
    >>> print(f"Classified {n_rows} days")
    """

    def __init__(
        self,
        engine: Engine,
        config: Optional[Dict[str, Any]] = None,
        profile: Optional[str] = None,
    ) -> None:
        self.engine = engine
        self.config = config if config is not None else load_macro_regime_config()
        self.profile = profile or self.config["active_profile"]

        # Resolve profile thresholds
        profiles = self.config["profiles"]
        if self.profile not in profiles:
            raise ValueError(
                f"Profile '{self.profile}' not found in config. "
                f"Available: {list(profiles.keys())}"
            )
        self.thresholds = profiles[self.profile]

        # Hysteresis setup
        min_bars = self.config["hysteresis"]["min_bars_hold"]
        self.tracker = HysteresisTracker(min_bars_hold=min_bars)

        # Tighten labels
        self.tighten_labels: Dict[str, List[str]] = self.config.get(
            "tighten_labels", {}
        )

        # Macro state rules
        self.macro_state_rules: Dict[str, Any] = self.config.get(
            "macro_state_rules", {"_default": "neutral"}
        )

        # Config version hash
        self._version_hash = _config_version_hash()

        logger.info(
            "MacroRegimeClassifier initialized: profile=%s, min_bars_hold=%d, "
            "version_hash=%s",
            self.profile,
            min_bars,
            self._version_hash,
        )

    # ------------------------------------------------------------------
    # Feature loading
    # ------------------------------------------------------------------

    def _load_features(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Load features from fred.fred_macro_features for the given window."""
        sql = text(
            "SELECT * FROM fred.fred_macro_features "
            "WHERE date >= :start AND date <= :end "
            "ORDER BY date"
        )
        with self.engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"start": start_date, "end": end_date})

        if df.empty:
            return df

        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        # Validate required columns
        missing: Dict[str, List[str]] = {}
        for dim, cols in _REQUIRED_COLUMNS.items():
            absent = [c for c in cols if c not in df.columns]
            if absent:
                missing[dim] = absent
        if missing:
            raise ValueError(
                f"Missing required columns in fred.fred_macro_features: {missing}. "
                "Run Phase 66 refresh_macro_features.py to populate."
            )

        return df

    # ------------------------------------------------------------------
    # Watermark
    # ------------------------------------------------------------------

    def _get_watermark(self) -> Optional[str]:
        """Get MAX(date) from macro_regimes for this profile."""
        sql = text("SELECT MAX(date) FROM macro_regimes WHERE profile = :profile")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql, {"profile": self.profile}).scalar()
            return str(result) if result is not None else None
        except Exception:  # noqa: BLE001
            logger.warning("Could not query watermark -- assuming fresh run")
            return None

    # ------------------------------------------------------------------
    # Classification pipeline
    # ------------------------------------------------------------------

    def _classify_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Classify a features DataFrame into regime labels.

        Applies dimension labelers + hysteresis per row in date order.
        """
        # Pre-compute carry spread 5d change
        if "us_jp_rate_spread" in df.columns:
            df = df.copy()
            df["us_jp_rate_spread_5d_change"] = df["us_jp_rate_spread"].diff(5)
        else:
            df = df.copy()
            df["us_jp_rate_spread_5d_change"] = float("nan")

        # Pre-compute dff 90d change for monetary policy fallback
        if "dff" in df.columns:
            df["dff_90d_change"] = df["dff"].diff(90)
        else:
            df["dff_90d_change"] = float("nan")

        results: List[Dict[str, Any]] = []

        for date_idx, row in df.iterrows():
            # Label each dimension
            raw_labels: Dict[str, Optional[str]] = {}
            for dim in _DIMENSIONS:
                labeler = _LABELERS[dim]
                dim_thresholds = self.thresholds[dim]
                raw_labels[dim] = labeler(row, dim_thresholds)

            # Apply hysteresis per dimension
            accepted_labels: Dict[str, Optional[str]] = {}
            for dim in _DIMENSIONS:
                raw = raw_labels[dim]
                if raw is None:
                    # If raw is None, keep current or set None
                    accepted_labels[dim] = self.tracker.get_current(dim)
                    continue

                is_tight = _is_macro_tightening(dim, raw, self.tighten_labels)
                accepted = self.tracker.update(dim, raw, is_tightening=is_tight)
                accepted_labels[dim] = accepted

            # Build composite key
            regime_key = _build_composite_key(accepted_labels)

            # Determine bucketed macro state
            macro_state = _determine_macro_state(regime_key, self.macro_state_rules)

            results.append(
                {
                    "date": date_idx,
                    "profile": self.profile,
                    "monetary_policy": accepted_labels.get("monetary_policy"),
                    "liquidity": accepted_labels.get("liquidity"),
                    "risk_appetite": accepted_labels.get("risk_appetite"),
                    "carry": accepted_labels.get("carry"),
                    "regime_key": regime_key,
                    "macro_state": macro_state,
                    "regime_version_hash": self._version_hash,
                }
            )

        return pd.DataFrame(results)

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def _upsert_regimes(self, df: pd.DataFrame) -> int:
        """Upsert classified regime DataFrame into macro_regimes."""
        import datetime

        if df.empty:
            return 0

        # Convert date to datetime.date for psycopg2
        df = df.copy()
        df["date"] = df["date"].apply(
            lambda x: x.date()
            if isinstance(x, (pd.Timestamp, datetime.datetime))
            else x
        )

        # Sanitize
        df = _sanitize_dataframe(df)

        col_list = [
            "date",
            "profile",
            "monetary_policy",
            "liquidity",
            "risk_appetite",
            "carry",
            "regime_key",
            "macro_state",
            "regime_version_hash",
        ]
        cols_str = ", ".join(col_list)
        update_cols = [c for c in col_list if c not in ("date", "profile")]
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        set_clause += ", ingested_at = now()"

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TEMP TABLE _regime_staging "
                    "(LIKE macro_regimes INCLUDING DEFAULTS) "
                    "ON COMMIT DROP"
                )
            )
            df[col_list].to_sql(
                "_regime_staging",
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )
            result = conn.execute(
                text(
                    f"INSERT INTO macro_regimes ({cols_str}) "
                    f"SELECT {cols_str} FROM _regime_staging "
                    f"ON CONFLICT (date, profile) DO UPDATE SET {set_clause}"
                )
            )
            row_count = result.rowcount

        logger.info("Upserted %d rows into macro_regimes", row_count)
        return row_count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        full: bool = False,
    ) -> int:
        """Run the full classification pipeline.

        Parameters
        ----------
        start_date:
            Optional override start date (ISO format).
        end_date:
            Optional override end date (ISO format).
        full:
            If True, ignore watermark and classify from 2000-01-01.

        Returns
        -------
        Number of rows upserted into macro_regimes.
        """
        # Determine compute window
        if end_date is None:
            end_date = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")

        if start_date is None:
            if full:
                start_date = "2000-01-01"
            else:
                watermark = self._get_watermark()
                if watermark is not None:
                    start_date = (
                        pd.Timestamp(watermark) - pd.Timedelta(days=WARMUP_DAYS)
                    ).strftime("%Y-%m-%d")
                    logger.info(
                        "Watermark: %s, warmup start: %s", watermark, start_date
                    )
                else:
                    start_date = "2000-01-01"
                    logger.info("No watermark -- full history from %s", start_date)

        logger.info(
            "Classification window: %s to %s (profile=%s)",
            start_date,
            end_date,
            self.profile,
        )

        # Load features
        df = self._load_features(start_date, end_date)
        if df.empty:
            logger.warning(
                "No features found for window %s to %s", start_date, end_date
            )
            return 0

        logger.info("Loaded %d rows of macro features", len(df))

        # Load hysteresis state from DB
        _load_hysteresis_state(self.engine, self.profile, self.tracker)

        # Classify
        result_df = self._classify_dataframe(df)
        logger.info(
            "Classified %d rows: %d unique macro_states",
            len(result_df),
            result_df["macro_state"].nunique(),
        )

        # Upsert
        n_upserted = self._upsert_regimes(result_df)

        # Save hysteresis state
        _save_hysteresis_state(self.engine, self.profile, self.tracker)

        return n_upserted
