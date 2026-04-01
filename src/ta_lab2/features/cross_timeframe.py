# src/ta_lab2/features/cross_timeframe.py
"""
Cross-Timeframe (CTF) feature computation engine.

Phase 90: Complete CTF engine with data loading, alignment, and computation.

This module provides:
  - CTFConfig: frozen dataclass for computation parameters
  - CTFFeature: class with all loading, alignment, computation, and write methods
      - _load_ctf_config: load configs/ctf_config.yaml
      - _load_dim_ctf_indicators: query dim_ctf_indicators for active indicators
      - _load_indicators_batch: batch-load all indicator columns from a source table
      - _align_timeframes: align base and reference timeframe DataFrames via merge_asof
      - _get_table_columns: introspect ctf fact table columns
      - _write_to_db: scoped DELETE + to_sql INSERT into public.ctf
      - _compute_one_source: per (base_tf, ref_tf, source_table, indicator) computation
      - compute_for_ids: top-level orchestrator over all YAML combos

Module-level helpers (vectorized rolling computations):
  - _compute_slope: rolling polyfit slope
  - _compute_divergence: (base - ref) / rolling_std z-score
  - _compute_agreement: rolling fraction of sign-matching bars
  - _compute_crossover: sign-change detection for directional indicators
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, create_engine, text

try:
    from ta_lab2.config import TARGET_DB_URL, project_root  # type: ignore[import]
except Exception:  # pragma: no cover

    def project_root() -> Path:  # type: ignore[misc]
        p = Path(__file__).resolve()
        for parent in [p, *p.parents]:
            if (parent / "pyproject.toml").exists():
                return parent
        return Path(__file__).resolve().parents[3]

    import os

    TARGET_DB_URL = os.environ.get("TARGET_DB_URL", "")

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ta_lab2.features.polars_feature_ops import (
    HAVE_POLARS,
    normalize_timestamps_for_polars,
    restore_timestamps_from_polars,
)
from ta_lab2.regimes.comovement import build_alignment_frame

try:
    import polars as pl  # type: ignore[import]
except ImportError:  # pragma: no cover
    pl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level computation helpers
# ---------------------------------------------------------------------------


def _compute_slope(series: pd.Series, window: int) -> pd.Series:
    """Compute vectorized rolling OLS slope via polyfit (raw=True for speed).

    Follows the expression_engine.py _slope pattern. Uses a fixed x-array
    (0..window-1) to avoid recomputing per window.

    Parameters
    ----------
    series:
        Time-ordered series of values to compute slope over.
    window:
        Number of bars in the rolling window (slope_window from composite_params).

    Returns
    -------
    pd.Series of the same index, containing the rolling slope at each point.
    NaN for positions without sufficient data (< 2 bars).
    """
    series = series.astype(float)
    n = int(window)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_denom = ((x - x_mean) ** 2).sum()

    def _apply(arr: np.ndarray) -> float:
        if len(arr) < n:
            xi = np.arange(len(arr), dtype=float)
            xi_mean = xi.mean()
            xi_denom = ((xi - xi_mean) ** 2).sum()
            if xi_denom == 0:
                return float("nan")
            return float(np.dot(arr - arr.mean(), xi - xi_mean) / xi_denom)
        y_mean = arr.mean()
        return float(np.dot(arr - y_mean, x - x_mean) / x_denom)

    return series.rolling(window=n, min_periods=2).apply(_apply, raw=True)


def _compute_divergence(
    base_series: pd.Series,
    ref_series: pd.Series,
    window: int,
) -> pd.Series:
    """Compute divergence as (base - ref) / rolling_std z-score.

    Parameters
    ----------
    base_series:
        Values from the base (finer) timeframe.
    ref_series:
        Values from the reference (coarser) timeframe, aligned to base index.
    window:
        Rolling window for the standard deviation denominator
        (divergence_zscore_window from composite_params).

    Returns
    -------
    pd.Series of z-scored divergence. NaN when std is near zero.
    """
    base_f = base_series.astype(float)
    ref_f = ref_series.astype(float)
    diff = base_f - ref_f
    std = base_f.rolling(window=window, min_periods=window // 2).std()
    return diff / std.where(std > 1e-12, other=np.nan)


def _compute_agreement(
    base_series: pd.Series,
    ref_series: pd.Series,
    is_directional: bool,
    window: int = 20,
) -> pd.Series:
    """Compute rolling fraction of sign-matching bars.

    For directional indicators (e.g. MACD, returns): fraction of bars where
    base and ref share the same sign (both positive or both negative).

    For non-directional indicators (e.g. RSI, vol): fraction of bars where
    base and ref move in the same direction (both increasing or both decreasing).

    Parameters
    ----------
    base_series:
        Values from the base timeframe.
    ref_series:
        Values from the reference timeframe.
    is_directional:
        True for directional indicators (compare sign of value).
        False for non-directional indicators (compare sign of diff/change).
    window:
        Rolling window for fraction computation. Defaults to 20.

    Returns
    -------
    pd.Series in [0.0, 1.0], where 1.0 means all bars in window agreed.
    """
    # Ensure float dtype so None/NaN arithmetic works correctly
    base_f = base_series.astype(float)
    ref_f = ref_series.astype(float)

    if is_directional:
        # Both positive or both negative
        agree = (np.sign(base_f) * np.sign(ref_f)) > 0
    else:
        # Both moving in the same direction
        agree = (np.sign(base_f.diff()) * np.sign(ref_f.diff())) > 0

    min_periods = min(window, max(5, window // 3))
    return agree.astype(float).rolling(window=window, min_periods=min_periods).mean()


def _compute_crossover(
    base_series: pd.Series,
    ref_series: pd.Series,
    is_directional: bool,
) -> pd.Series:
    """Detect sign-change crossovers between base and reference series.

    Only meaningful for directional indicators. Non-directional returns NaN.

    Parameters
    ----------
    base_series:
        Values from the base timeframe.
    ref_series:
        Values from the reference timeframe.
    is_directional:
        True for directional indicators. False returns all-NaN series.

    Returns
    -------
    pd.Series with values:
        +1.0  = base crossed above ref (bullish crossover)
        -1.0  = base crossed below ref (bearish crossover)
         0.0  = no crossover this bar
        NaN   = non-directional indicator or insufficient history
    """
    if not is_directional:
        return pd.Series(np.nan, index=base_series.index)

    base_f = base_series.astype(float)
    ref_f = ref_series.astype(float)
    prev_above = base_f.shift(1) > ref_f.shift(1)
    curr_above = base_f > ref_f
    crossed_up = (~prev_above) & curr_above
    crossed_dn = prev_above & (~curr_above)
    return crossed_up.astype(float) - crossed_dn.astype(float)


# ---------------------------------------------------------------------------
# Polars join_asof helper (timezone-safe)
# ---------------------------------------------------------------------------


def _align_timeframes_polars(
    base_df: pd.DataFrame,
    ref_df: pd.DataFrame,
    source_col: str,
) -> pd.DataFrame:
    """Align base and reference timeframe DataFrames using polars join_asof.

    Mirrors the pandas merge_asof path but uses polars for the join.
    Handles timezone stripping/restoring around the polars boundary.

    Critical requirements for polars join_asof:
    - Both DataFrames must be sorted by the ``on`` column ascending.
    - Both datetime columns must have the same dtype -- tz-aware pandas UTC
      becomes polars Datetime('us', 'UTC') which differs from Datetime('us');
      we strip UTC before conversion and restore after.
    - ``by=`` must match dtype exactly in both frames.

    Parameters
    ----------
    base_df:
        DataFrame with columns [id, ts, <source_col>] for the base timeframe.
    ref_df:
        DataFrame with columns [id, ts, <source_col>] for the reference timeframe.
    source_col:
        Name of the indicator column present in both DataFrames.

    Returns
    -------
    pd.DataFrame with columns: [id, ts, base_value, ref_value]
    Empty DataFrame if no aligned rows exist.
    """
    if not HAVE_POLARS or pl is None:
        raise RuntimeError(
            "_align_timeframes_polars called but polars is not available"
        )

    # Strip UTC from ts before polars conversion (critical: tz-aware != tz-naive in polars)
    base_clean = normalize_timestamps_for_polars(base_df, "ts")
    ref_clean = normalize_timestamps_for_polars(ref_df, "ts")

    # Ensure sorted by ts ascending per asset (polars join_asof requires sorted join key)
    base_clean = base_clean.sort_values(["id", "ts"]).reset_index(drop=True)
    ref_clean = ref_clean.sort_values(["id", "ts"]).reset_index(drop=True)

    # Convert to polars
    pl_base = pl.from_pandas(base_clean[["id", "ts", source_col]])
    pl_ref = pl.from_pandas(ref_clean[["id", "ts", source_col]])

    # Rename ref source_col to avoid collision after join
    ref_col = f"{source_col}_ref"
    pl_ref = pl_ref.rename({source_col: ref_col})

    # polars join_asof: backward strategy = most recent ref row at or before each base ts
    # by="id" groups the join per asset (equivalent to per-asset merge_asof loop)
    pl_joined = pl_base.sort("ts").join_asof(
        pl_ref.sort("ts"),
        on="ts",
        by="id",
        strategy="backward",
    )

    # Convert back to pandas and restore UTC on ts
    result = pl_joined.to_pandas()
    result = restore_timestamps_from_polars(result, "ts")

    # Rename to canonical output columns
    result = result.rename(
        columns={
            source_col: "base_value",
            ref_col: "ref_value",
        }
    )

    # Keep only canonical columns (drop extra polars artifacts if any)
    out_cols = [
        c for c in ["id", "ts", "base_value", "ref_value"] if c in result.columns
    ]
    return result[out_cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# CTF pivot loader
# ---------------------------------------------------------------------------


def load_ctf_features(
    conn,
    asset_id: int,
    base_tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    *,
    ref_tfs: Optional[list[str]] = None,
    indicator_names: Optional[list[str]] = None,
    alignment_source: str = "multi_tf",
    venue_id: int = 1,
) -> pd.DataFrame:
    """Load CTF features from public.ctf and reshape to wide-format DataFrame.

    Queries the ctf fact table joined with dim_ctf_indicators, then pivots from
    the normalized long format (one row per indicator x ref_tf x timestamp) into
    a wide format suitable for batch_compute_ic().

    Column naming: ``{indicator_name}_{ref_tf_lower}_{composite}``
    Example: ``rsi_14_7d_slope``, ``macd_30d_divergence``

    Parameters
    ----------
    conn:
        SQLAlchemy connection (Engine.connect() context or raw connection).
    asset_id:
        Asset ID (public.dim_assets.id).
    base_tf:
        Base timeframe string (e.g. '1D', '7D').
    train_start:
        Start of training window (inclusive). Timezone-aware UTC.
    train_end:
        End of training window (inclusive). Timezone-aware UTC.
    ref_tfs:
        Optional list of reference timeframe strings to filter (e.g. ['7D', '30D']).
        If None, all reference timeframes are returned.
    indicator_names:
        Optional list of indicator names to filter (e.g. ['rsi_14', 'macd']).
        If None, all active indicators are returned.
    alignment_source:
        Alignment source filter (default: 'multi_tf').
    venue_id:
        Venue ID filter (default: 1 = CMC_AGG).

    Returns
    -------
    pd.DataFrame with:
        - DatetimeIndex named 'ts' that is tz-aware UTC
        - One column per (indicator_name, ref_tf, composite) combination
        - Columns named {indicator_name}_{ref_tf_lower}_{composite}
        - All-NaN columns dropped (e.g. crossover for non-directional indicators)
        - Empty DataFrame if no rows match the query
    """
    # ------------------------------------------------------------------
    # Build SQL query
    # ------------------------------------------------------------------
    where_parts = [
        "c.id = :asset_id",
        "c.base_tf = :base_tf",
        "c.ts >= :train_start",
        "c.ts <= :train_end",
        "c.alignment_source = :alignment_source",
        "c.venue_id = :venue_id",
    ]
    params: dict = {
        "asset_id": asset_id,
        "base_tf": base_tf,
        "train_start": train_start,
        "train_end": train_end,
        "alignment_source": alignment_source,
        "venue_id": venue_id,
    }

    if ref_tfs is not None:
        where_parts.append("c.ref_tf = ANY(:ref_tfs)")
        params["ref_tfs"] = ref_tfs

    if indicator_names is not None:
        where_parts.append("d.indicator_name = ANY(:indicator_names)")
        params["indicator_names"] = indicator_names

    where_clause = " AND ".join(where_parts)

    sql_str = f"""
        SELECT
            c.ts,
            d.indicator_name,
            c.ref_tf,
            c.ref_value,
            c.base_value,
            c.slope,
            c.divergence,
            c.agreement,
            c.crossover
        FROM public.ctf c
        JOIN public.dim_ctf_indicators d ON d.indicator_id = c.indicator_id
        WHERE {where_clause}
        ORDER BY c.ts
    """

    df = pd.read_sql(text(sql_str), conn, params=params)

    # ------------------------------------------------------------------
    # Return empty DataFrame early if no data
    # ------------------------------------------------------------------
    if df.empty:
        logger.debug(
            "load_ctf_features: no rows for asset_id=%d base_tf=%s train=%s..%s",
            asset_id,
            base_tf,
            train_start,
            train_end,
        )
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # CRITICAL: ensure ts is tz-aware UTC (Windows tz-naive fix)
    # ------------------------------------------------------------------
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # ------------------------------------------------------------------
    # Vectorized pivot: long -> wide
    # ------------------------------------------------------------------
    df["ref_tf_lower"] = df["ref_tf"].str.lower()
    df["col_base"] = df["indicator_name"] + "_" + df["ref_tf_lower"]

    composite_cols = [
        "ref_value",
        "base_value",
        "slope",
        "divergence",
        "agreement",
        "crossover",
    ]
    melted = df.melt(
        id_vars=["ts", "col_base"],
        value_vars=composite_cols,
        var_name="composite",
        value_name="val",
    )
    melted["feature_col"] = melted["col_base"] + "_" + melted["composite"]

    wide = melted.pivot_table(
        index="ts",
        columns="feature_col",
        values="val",
        aggfunc="first",
    )
    wide.columns.name = None
    wide.index.name = "ts"

    # ------------------------------------------------------------------
    # Drop all-NaN columns (e.g. crossover for non-directional indicators)
    # ------------------------------------------------------------------
    wide = wide.dropna(axis=1, how="all")

    logger.debug(
        "load_ctf_features: asset_id=%d base_tf=%s rows=%d cols=%d",
        asset_id,
        base_tf,
        len(wide),
        len(wide.columns),
    )
    return wide


# ---------------------------------------------------------------------------
# CTFConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CTFConfig:
    """Configuration for CTF feature computation.

    Parameters
    ----------
    alignment_source:
        The alignment_source value to filter source tables on (default: 'multi_tf').
    venue_id:
        The venue_id to filter on for tables that have it in the WHERE clause (default: 1 = CMC_AGG).
    yaml_path:
        Optional explicit path to CTF config YAML. None = default configs/ctf_config.yaml.
    use_polars:
        If True, use polars join_asof for timeframe alignment (faster for large DataFrames).
        Falls back to pandas merge_asof if polars is not installed.
        Default: False (zero behavior change for existing callers).
    """

    alignment_source: str = "multi_tf"
    venue_id: int = 1
    yaml_path: Optional[str] = None
    use_polars: bool = False


# ---------------------------------------------------------------------------
# CTFFeature class
# ---------------------------------------------------------------------------


class CTFFeature:
    """Cross-Timeframe feature computation engine.

    Orchestrates data loading, timeframe alignment, composite computation,
    and DB writes for the public.ctf fact table.

    Parameters
    ----------
    config:
        CTFConfig instance. If None, uses default CTFConfig().
    engine:
        SQLAlchemy engine. If None, creates one from TARGET_DB_URL.
    """

    def __init__(
        self,
        config: Optional[CTFConfig] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        self.config = config or CTFConfig()
        self.engine = engine or create_engine(TARGET_DB_URL)
        self._yaml_config: Optional[dict] = None
        self._dim_indicators: Optional[list[dict]] = None
        self._table_columns: Optional[set[str]] = None

    # -----------------------------------------------------------------------
    # YAML config
    # -----------------------------------------------------------------------

    def _load_ctf_config(self) -> dict:
        """Load (and cache) the CTF YAML configuration.

        Uses self.config.yaml_path if set, otherwise resolves
        <project_root>/configs/ctf_config.yaml.

        Returns
        -------
        dict with top-level keys: timeframe_pairs, indicators, composite_params.

        Raises
        ------
        RuntimeError if PyYAML is not installed.
        FileNotFoundError if the config file does not exist.
        """
        if self._yaml_config is not None:
            return self._yaml_config

        if yaml is None:  # pragma: no cover
            raise RuntimeError(
                "PyYAML is required for CTF config loading. "
                "Install with: pip install pyyaml"
            )

        if self.config.yaml_path is not None:
            path = Path(self.config.yaml_path)
        else:
            path = project_root() / "configs" / "ctf_config.yaml"

        if not path.exists():
            raise FileNotFoundError(f"CTF config not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            self._yaml_config = yaml.safe_load(f) or {}

        logger.debug("Loaded CTF config from %s", path)
        return self._yaml_config

    # -----------------------------------------------------------------------
    # Dimension table
    # -----------------------------------------------------------------------

    def _load_dim_ctf_indicators(self) -> list[dict]:
        """Load (and cache) active CTF indicators from dim_ctf_indicators.

        Returns
        -------
        List of dicts with keys: indicator_id, indicator_name, source_table,
        source_column, is_directional. Only is_active=TRUE rows are returned,
        ordered by indicator_id ascending.
        """
        if self._dim_indicators is not None:
            return self._dim_indicators

        sql = text(
            """
            SELECT
                indicator_id,
                indicator_name,
                source_table,
                source_column,
                is_directional
            FROM public.dim_ctf_indicators
            WHERE is_active = TRUE
            ORDER BY indicator_id
            """
        )

        with self.engine.connect() as conn:
            result = conn.execute(sql)
            rows = result.fetchall()

        self._dim_indicators = [
            {
                "indicator_id": row[0],
                "indicator_name": row[1],
                "source_table": row[2],
                "source_column": row[3],
                "is_directional": row[4],
            }
            for row in rows
        ]

        logger.debug("Loaded %d active CTF indicators", len(self._dim_indicators))
        return self._dim_indicators

    # -----------------------------------------------------------------------
    # Batch indicator loading
    # -----------------------------------------------------------------------

    def _load_indicators_batch(
        self,
        ids: list[int],
        source_table: str,
        columns: list[str],
        tf: str,
        extra_filter: str = "",
    ) -> pd.DataFrame:
        """Load indicator columns from a source table for the given asset IDs and timeframe.

        Handles the four source table asymmetries:
        - returns_bars_multi_tf_u: ts column is ``"timestamp"`` (quoted reserved word),
          aliased as ``ts``. Requires ``AND roll = FALSE`` filter.
        - ta, vol, features: ts column is ``ts``.
        - ALL tables have venue_id in their PK; filtering by venue_id is always applied
          to avoid duplicate ts rows when multiple venues are present
          (e.g. CMC_AGG venue_id=1 + Hyperliquid venue_id=2).

        Parameters
        ----------
        ids:
            List of asset IDs (public.dim_assets.id) to load.
        source_table:
            One of: 'ta', 'vol', 'returns_bars_multi_tf_u', 'features'.
        columns:
            List of indicator column names to SELECT from the source table.
        tf:
            Timeframe string (e.g. '1D', '7D', '30D').
        extra_filter:
            Additional SQL filter string appended after core WHERE clause (rarely needed;
            roll filter is handled automatically for returns_bars_multi_tf_u).

        Returns
        -------
        pd.DataFrame with columns: id, ts, alignment_source, venue_id, *columns
        Ordered by id, ts ascending. ts is timezone-aware UTC.
        """
        is_returns = source_table == "returns_bars_multi_tf_u"

        # Handle ts column name asymmetry
        ts_col = '"timestamp"' if is_returns else "ts"
        ts_alias = f"{ts_col} AS ts" if is_returns else "ts"

        # Build quoted column list
        col_list = ", ".join(f'"{c}"' for c in columns)

        # Build WHERE clause
        where_parts = [
            "id = ANY(:ids)",
            "tf = :tf",
            "alignment_source = :as_",
        ]

        if is_returns:
            where_parts.append("roll = FALSE")

        # All source tables have venue_id in PK — filter to avoid duplicate ts rows
        # when multiple venues are present (e.g. CMC_AGG venue_id=1 + Hyperliquid venue_id=2)
        where_parts.append("venue_id = :venue_id")

        if extra_filter:
            where_parts.append(extra_filter)

        where_clause = " AND ".join(where_parts)

        sql_str = f"""
            SELECT
                id,
                {ts_alias},
                alignment_source,
                venue_id,
                {col_list}
            FROM public.{source_table}
            WHERE {where_clause}
            ORDER BY id, {ts_col} ASC
        """

        params: dict = {
            "ids": ids,
            "tf": tf,
            "as_": self.config.alignment_source,
            "venue_id": self.config.venue_id,
        }

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql_str), conn, params=params)

        # CRITICAL: ensure ts is tz-aware UTC (Windows tz fix)
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)

        logger.debug(
            "_load_indicators_batch: source=%s tf=%s ids=%d rows=%d",
            source_table,
            tf,
            len(ids),
            len(df),
        )
        return df

    # -----------------------------------------------------------------------
    # Timeframe alignment
    # -----------------------------------------------------------------------

    def _align_timeframes(
        self,
        base_df: pd.DataFrame,
        ref_df: pd.DataFrame,
        source_col: str,
    ) -> pd.DataFrame:
        """Align base and reference timeframe DataFrames using backward merge_asof.

        When self.config.use_polars is True and polars is available, delegates to
        _align_timeframes_polars() which uses polars join_asof with ``by="id"``
        for a vectorized cross-asset join (no per-asset Python loop).

        When use_polars is False or polars is unavailable, falls back to the
        original per-asset pandas merge_asof loop via build_alignment_frame().

        Parameters
        ----------
        base_df:
            DataFrame with columns [id, ts, <source_col>] for the base (lower) timeframe.
        ref_df:
            DataFrame with columns [id, ts, <source_col>] for the reference (higher) timeframe.
        source_col:
            Name of the indicator column present in both DataFrames.

        Returns
        -------
        pd.DataFrame with columns: [id, ts, base_value, ref_value]
        where base_value = source_col value from base_df
        and   ref_value  = most recent source_col value from ref_df at or before ts.
        """
        # Polars path: vectorized join_asof with timezone handling
        if self.config.use_polars and HAVE_POLARS:
            try:
                result = _align_timeframes_polars(base_df, ref_df, source_col)
                logger.debug("_align_timeframes (polars): aligned_rows=%d", len(result))
                return result
            except Exception as e:
                logger.warning(
                    "_align_timeframes polars path failed (%s), falling back to pandas",
                    e,
                )
                # Fall through to pandas path below

        # Pandas path: per-asset merge_asof loop (original implementation)
        aligned_frames: list[pd.DataFrame] = []

        for asset_id in base_df["id"].unique():
            base_asset = base_df[base_df["id"] == asset_id].copy()
            ref_asset = ref_df[ref_df["id"] == asset_id].copy()

            if ref_asset.empty:
                logger.debug(
                    "_align_timeframes: no ref data for asset_id=%d, skipping", asset_id
                )
                continue

            aligned = build_alignment_frame(
                low_df=base_asset[["ts", source_col]],
                high_df=ref_asset[["ts", source_col]],
                on="ts",
                low_cols=[source_col],
                high_cols=[source_col],
                suffix_low="",
                suffix_high="_ref",
                direction="backward",
            )

            # Rename to canonical output columns
            aligned = aligned.rename(
                columns={
                    source_col: "base_value",
                    f"{source_col}_ref": "ref_value",
                }
            )

            aligned["id"] = asset_id
            aligned_frames.append(aligned[["id", "ts", "base_value", "ref_value"]])

            logger.debug(
                "_align_timeframes: asset_id=%d aligned_rows=%d",
                asset_id,
                len(aligned),
            )

        if not aligned_frames:
            return pd.DataFrame(columns=["id", "ts", "base_value", "ref_value"])

        return pd.concat(aligned_frames, ignore_index=True)

    # -----------------------------------------------------------------------
    # Table column introspection
    # -----------------------------------------------------------------------

    def _get_table_columns(self) -> set[str]:
        """Get column names from the ctf fact table in information_schema.

        Returns empty set if the table does not exist or an error occurs.
        Caches result on self._table_columns.
        """
        if self._table_columns is not None:
            return self._table_columns

        sql = text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            """
        )

        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql, {"schema": "public", "table": "ctf"})
                self._table_columns = {row[0] for row in result}
        except Exception:
            self._table_columns = set()

        return self._table_columns

    # -----------------------------------------------------------------------
    # DB write
    # -----------------------------------------------------------------------

    def _write_to_db(
        self,
        df: pd.DataFrame,
        base_tf: str,
        ref_tf: str,
        indicator_ids: list[int],
    ) -> int:
        """Write CTF computation results to public.ctf using scoped DELETE + INSERT.

        The DELETE scope is: (id, venue_id, base_tf, ref_tf, indicator_id, alignment_source).
        This ensures idempotent re-runs without duplicates.

        Parameters
        ----------
        df:
            DataFrame with CTF result rows. Must include all PK + value columns.
        base_tf:
            Base timeframe string (e.g. '1D').
        ref_tf:
            Reference timeframe string (e.g. '7D').
        indicator_ids:
            List of indicator_ids present in df (used in DELETE scope).

        Returns
        -------
        Number of rows written (0 if df is empty).
        """
        if df.empty:
            return 0

        # Filter df to only columns that exist in the ctf table
        table_cols = self._get_table_columns()
        df_cols = [c for c in df.columns if c in table_cols]
        df = df[df_cols].copy()

        # Extract unique IDs from the DataFrame
        ids = df["id"].unique().tolist()

        delete_sql = text(
            """
            DELETE FROM public.ctf
            WHERE id = ANY(:ids)
              AND venue_id = :venue_id
              AND base_tf = :base_tf
              AND ref_tf = :ref_tf
              AND indicator_id = ANY(:iids)
              AND alignment_source = :as_
            """
        )

        with self.engine.begin() as conn:
            conn.execute(
                delete_sql,
                {
                    "ids": ids,
                    "venue_id": self.config.venue_id,
                    "base_tf": base_tf,
                    "ref_tf": ref_tf,
                    "iids": indicator_ids,
                    "as_": self.config.alignment_source,
                },
            )

        # INSERT via to_sql (append mode after DELETE)
        df.to_sql(
            "ctf",
            self.engine,
            schema="public",
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10000,
        )

        rows_written = len(df)
        logger.info(
            "_write_to_db: base_tf=%s ref_tf=%s indicators=%s rows=%d",
            base_tf,
            ref_tf,
            indicator_ids,
            rows_written,
        )
        return rows_written

    # -----------------------------------------------------------------------
    # Per-source computation
    # -----------------------------------------------------------------------

    def _compute_one_source(
        self,
        ids: list[int],
        base_tf: str,
        ref_tf: str,
        source_table: str,
        source_indicators: list[dict],
        yaml_config: dict,
    ) -> int:
        """Compute CTF features for one (base_tf, ref_tf, source_table) combination.

        For each active indicator in source_indicators:
          1. Loads base and ref timeframe data
          2. Aligns via merge_asof
          3. Computes slope, divergence, agreement, crossover per asset
          4. Writes to DB via _write_to_db

        Parameters
        ----------
        ids:
            Asset IDs to process.
        base_tf:
            Base (finer) timeframe string.
        ref_tf:
            Reference (coarser) timeframe string.
        source_table:
            Source table name (e.g. 'ta', 'vol', 'returns_bars_multi_tf_u', 'features').
        source_indicators:
            List of indicator dicts from dim_ctf_indicators for this source_table.
        yaml_config:
            Full YAML config dict (for composite_params).

        Returns
        -------
        Total rows written across all indicators.
        """
        # Read composite parameters
        composite_params = yaml_config.get("composite_params", {})
        slope_window: int = int(composite_params.get("slope_window", 5))
        divergence_zscore_window: int = int(
            composite_params.get("divergence_zscore_window", 63)
        )

        # Collect all source columns (batch load once per tf)
        columns = [ind["source_column"] for ind in source_indicators]

        # Load base and ref data (roll=FALSE is handled inside _load_indicators_batch
        # for returns_bars_multi_tf_u — no extra_filter needed here)
        base_df = self._load_indicators_batch(ids, source_table, columns, base_tf)
        ref_df = self._load_indicators_batch(ids, source_table, columns, ref_tf)

        if base_df.empty or ref_df.empty:
            logger.warning(
                "_compute_one_source: no data for source=%s base_tf=%s ref_tf=%s "
                "(base_rows=%d ref_rows=%d)",
                source_table,
                base_tf,
                ref_tf,
                len(base_df),
                len(ref_df),
            )
            return 0

        total_rows = 0
        computed_at = pd.Timestamp.now("UTC")

        for ind in source_indicators:
            source_col = ind["source_column"]
            is_dir = bool(ind["is_directional"])
            indicator_id = int(ind["indicator_id"])

            # Align the two timeframes for this indicator column
            aligned = self._align_timeframes(
                base_df[["id", "ts", source_col]],
                ref_df[["id", "ts", source_col]],
                source_col,
            )

            if aligned.empty:
                logger.debug(
                    "_compute_one_source: empty aligned for indicator=%s base_tf=%s ref_tf=%s",
                    source_col,
                    base_tf,
                    ref_tf,
                )
                continue

            # Per-asset computation to avoid cross-asset contamination
            asset_frames: list[pd.DataFrame] = []
            for asset_id in aligned["id"].unique():
                df_a = aligned[aligned["id"] == asset_id].copy()

                df_a["slope"] = _compute_slope(df_a["base_value"], slope_window)
                df_a["divergence"] = _compute_divergence(
                    df_a["base_value"], df_a["ref_value"], divergence_zscore_window
                )
                df_a["agreement"] = _compute_agreement(
                    df_a["base_value"], df_a["ref_value"], is_dir
                )
                df_a["crossover"] = _compute_crossover(
                    df_a["base_value"], df_a["ref_value"], is_dir
                )
                asset_frames.append(df_a)

            if not asset_frames:
                continue

            ind_df = pd.concat(asset_frames, ignore_index=True)

            # Add CTF PK and metadata columns
            ind_df["venue_id"] = self.config.venue_id
            ind_df["base_tf"] = base_tf
            ind_df["ref_tf"] = ref_tf
            ind_df["indicator_id"] = indicator_id
            ind_df["alignment_source"] = self.config.alignment_source
            ind_df["computed_at"] = computed_at

            # base_value and ref_value are already present from _align_timeframes
            rows = self._write_to_db(ind_df, base_tf, ref_tf, [indicator_id])
            total_rows += rows

            logger.debug(
                "_compute_one_source: indicator=%s base_tf=%s ref_tf=%s rows=%d",
                source_col,
                base_tf,
                ref_tf,
                rows,
            )

        return total_rows

    # -----------------------------------------------------------------------
    # Top-level orchestrator
    # -----------------------------------------------------------------------

    def compute_for_ids(self, ids: list[int]) -> int:
        """Orchestrate CTF feature computation for all configured combos.

        Iterates over all (base_tf, ref_tf) pairs from the YAML config and
        all source tables from dim_ctf_indicators, computing and writing
        slope, divergence, agreement, and crossover features.

        Parameters
        ----------
        ids:
            List of asset IDs (public.dim_assets.id) to compute features for.

        Returns
        -------
        Total rows written to public.ctf.
        """
        yaml_cfg = self._load_ctf_config()
        indicators = self._load_dim_ctf_indicators()

        if not indicators:
            logger.warning("compute_for_ids: no active CTF indicators found")
            return 0

        # Group indicators by source_table
        by_source: dict[str, list[dict]] = {}
        for ind in indicators:
            by_source.setdefault(ind["source_table"], []).append(ind)

        # Full yaml_cfg (including composite_params) is passed to _compute_one_source.
        # source_table-to-yaml-section mapping is not needed here: _compute_one_source
        # reads composite_params directly from yaml_cfg and roll=FALSE is handled
        # automatically inside _load_indicators_batch for returns_bars_multi_tf_u.

        total_rows = 0
        timeframe_pairs = yaml_cfg.get("timeframe_pairs", [])

        for tf_pair in timeframe_pairs:
            base_tf: str = tf_pair["base_tf"]
            ref_tfs: list[str] = tf_pair.get("ref_tfs", [])

            for ref_tf in ref_tfs:
                for source_table, source_inds in by_source.items():
                    logger.info(
                        "compute_for_ids: base_tf=%s ref_tf=%s source=%s indicators=%d ids=%d",
                        base_tf,
                        ref_tf,
                        source_table,
                        len(source_inds),
                        len(ids),
                    )
                    rows = self._compute_one_source(
                        ids,
                        base_tf,
                        ref_tf,
                        source_table,
                        source_inds,
                        yaml_cfg,
                    )
                    total_rows += rows

        logger.info(
            "compute_for_ids: complete. total_rows=%d ids=%s",
            total_rows,
            ids,
        )
        return total_rows
