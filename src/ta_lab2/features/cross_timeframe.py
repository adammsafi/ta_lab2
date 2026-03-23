# src/ta_lab2/features/cross_timeframe.py
"""
Cross-Timeframe (CTF) feature computation engine.

Phase 90, Plan 01: Data loading and alignment foundation.

This module provides:
  - CTFConfig: frozen dataclass for computation parameters
  - CTFFeature: class with data loading and alignment methods
      - _load_ctf_config: load configs/ctf_config.yaml
      - _load_dim_ctf_indicators: query dim_ctf_indicators for active indicators
      - _load_indicators_batch: batch-load all indicator columns from a source table
      - _align_timeframes: align base and reference timeframe DataFrames via merge_asof
      - _get_table_columns: introspect ctf fact table columns

Plan 02 will add: slope, divergence, agreement, crossover composites, orchestrator, write logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np  # noqa: F401 (available for plan 02 composite computations)
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

from ta_lab2.regimes.comovement import build_alignment_frame

logger = logging.getLogger(__name__)


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
    """

    alignment_source: str = "multi_tf"
    venue_id: int = 1
    yaml_path: Optional[str] = None


# ---------------------------------------------------------------------------
# CTFFeature class
# ---------------------------------------------------------------------------


class CTFFeature:
    """Cross-Timeframe feature computation engine.

    Responsible for data loading and timeframe alignment.
    Composite computations (slope, divergence, agreement, crossover) are in plan 02.

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
        - features: has venue_id in WHERE (AND venue_id = :venue_id).
        - ta and vol: venue_id is a column (present in table) but no additional
          venue_id WHERE filter needed beyond alignment_source.

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

        # features table has venue_id in WHERE
        if source_table == "features":
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
        }
        if source_table == "features":
            params["venue_id"] = self.config.venue_id

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

        For each unique asset_id in base_df, aligns the base timeframe rows with
        the most recent reference timeframe row via build_alignment_frame().

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
