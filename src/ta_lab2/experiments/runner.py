"""ExperimentRunner: Core execution engine for the Phase 38 experimentation framework.

Computes experimental features from YAML spec, writes values to a temp scratch table,
scores them with Phase 37 compute_ic(), applies BH correction across all rows, and
returns results with cost tracking metadata.

No production tables are polluted -- feature values go into a session-scoped
TEMP table only. Only cmc_feature_experiments is written to (and only by the CLI
wrapper, not by ExperimentRunner itself).

Public API
----------
ExperimentRunner.run():
    Compute feature, score with IC, apply BH correction, return result DataFrame.
"""

from __future__ import annotations

import importlib
import logging
import math
import time
import tracemalloc
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control
from sqlalchemy import text

from ta_lab2.analysis.ic import compute_ic
from ta_lab2.experiments.registry import FeatureRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist of tables that ExperimentRunner is permitted to query.
# This prevents SQL injection via a crafted YAML features.yaml.
# Only table names and column names are injected into f-strings;
# all values (id, tf, dates) are parameterized.
# ---------------------------------------------------------------------------
_ALLOWED_TABLES = frozenset(
    [
        "cmc_price_bars_multi_tf",
        "cmc_price_bars_multi_tf_u",
        "cmc_returns_bars_multi_tf",
        "cmc_returns_bars_multi_tf_u",
        "cmc_ema_multi_tf",
        "cmc_ema_multi_tf_u",
        "cmc_returns_ema_multi_tf",
        "cmc_returns_ema_multi_tf_u",
        "cmc_vol",
        "cmc_ta_daily",
        "cmc_features",
        "cmc_regimes",
    ]
)

# Tables that do NOT have a `tf` column — filter by id + ts only.
_TABLES_WITHOUT_TF = frozenset(
    [
        "cmc_vol",
        "cmc_ta_daily",
    ]
)

# Default close source when inputs do not include a close price
_CLOSE_SOURCE_TABLE = "cmc_price_bars_multi_tf_u"


class ExperimentRunner:
    """
    Core execution engine for feature experimentation.

    Loads input data from declared source tables, computes feature values via
    inline eval or dotpath, writes to a temp scratch table (session-scoped),
    scores with Phase 37's compute_ic(), applies BH correction across ALL rows
    of the run (all assets x horizons x return_types), and returns results with
    cost metadata.

    Parameters
    ----------
    registry : FeatureRegistry
        Loaded feature registry (must have called registry.load() before passing).
    engine : sqlalchemy.Engine
        SQLAlchemy engine for database access. Caller creates it with NullPool.

    Example usage::

        from sqlalchemy import create_engine, pool
        from ta_lab2.experiments import FeatureRegistry
        from ta_lab2.experiments.runner import ExperimentRunner

        registry = FeatureRegistry("configs/experiments/features.yaml")
        registry.load()

        engine = create_engine(db_url, poolclass=pool.NullPool)
        runner = ExperimentRunner(registry, engine)

        result_df = runner.run(
            "vol_ratio_30_7",
            asset_ids=[1, 2, 3],
            tf="1D",
            train_start=pd.Timestamp("2024-01-01", tz="UTC"),
            train_end=pd.Timestamp("2025-12-31", tz="UTC"),
        )
    """

    def __init__(self, registry: FeatureRegistry, engine: Any) -> None:
        if not registry._features:
            raise ValueError(
                "FeatureRegistry is empty. Call registry.load() before passing to ExperimentRunner."
            )
        self.registry = registry
        self.engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        feature_name: str,
        asset_ids: list[int],
        tf: str,
        train_start: pd.Timestamp,
        train_end: pd.Timestamp,
        *,
        horizons: list[int] | None = None,
        return_types: list[str] | None = None,
        dry_run: bool = False,
    ) -> pd.DataFrame:
        """
        Compute an experimental feature and score it with IC.

        Parameters
        ----------
        feature_name : str
            Feature name as registered in the YAML registry (expanded variant name).
        asset_ids : list[int]
            Asset IDs to evaluate.
        tf : str
            Timeframe string (e.g. "1D").
        train_start : pd.Timestamp
            Start of training window (tz-aware UTC, inclusive).
        train_end : pd.Timestamp
            End of training window (tz-aware UTC, inclusive).
        horizons : list[int], optional
            Forward bar horizons. Default: [1, 2, 3, 5, 10, 20, 60].
        return_types : list[str], optional
            Return types. Default: ["arith", "log"].
        dry_run : bool
            If True, skip scratch table writes (still computes IC).

        Returns
        -------
        pd.DataFrame
            One row per (asset_id, tf, horizon, return_type). Columns include:
            feature_name, asset_id, tf, horizon, return_type, ic, ic_t_stat,
            ic_p_value, ic_p_value_bh, ic_ir, ic_ir_t_stat, turnover, n_obs,
            yaml_digest, train_start, train_end,
            wall_clock_seconds, peak_memory_mb, n_rows_computed.
        """
        spec = self.registry.get_feature(feature_name)

        # Look up tf_days_nominal from dim_timeframe
        tf_days_nominal = self._get_tf_days_nominal(tf)

        # Start cost tracking
        tracemalloc.start()
        t0 = time.perf_counter()
        n_rows_computed = 0

        # Build a scratch table name: _exp_{safe_name}_{epoch_suffix}
        safe_name = "".join(
            c if c.isalnum() or c == "_" else "_" for c in feature_name
        )[:20]
        epoch_suffix = str(int(t0))[-8:]
        scratch_name = f"_exp_{safe_name}_{epoch_suffix}"

        all_ic_rows: list[pd.DataFrame] = []

        with self.engine.connect() as conn:
            # Create temp scratch table (session-scoped)
            if not dry_run:
                self._create_scratch_table(conn, scratch_name)

            for asset_id in asset_ids:
                logger.debug(
                    "ExperimentRunner: feature=%s asset_id=%d tf=%s",
                    feature_name,
                    asset_id,
                    tf,
                )
                try:
                    # Load input data from declared source tables
                    input_df = self._load_inputs(
                        conn, spec, asset_id, tf, train_start, train_end
                    )

                    if input_df.empty:
                        logger.debug(
                            "No input data for asset_id=%d tf=%s — skipping",
                            asset_id,
                            tf,
                        )
                        continue

                    # Compute feature values
                    feature_series = self._compute_feature(spec, input_df)

                    if feature_series is None or feature_series.empty:
                        logger.debug(
                            "Feature computation returned empty series for asset_id=%d — skipping",
                            asset_id,
                        )
                        continue

                    n_rows_computed += len(feature_series)

                    # Write feature values to scratch table
                    if not dry_run:
                        self._write_to_scratch(
                            conn,
                            scratch_name,
                            feature_series,
                            asset_id,
                            tf,
                            feature_name,
                        )

                    # Extract or load close series for IC scoring
                    close_series = self._get_close_series(
                        conn, input_df, spec, asset_id, tf, train_start, train_end
                    )

                    if close_series is None or close_series.empty:
                        logger.debug(
                            "No close series for asset_id=%d tf=%s — skipping IC",
                            asset_id,
                            tf,
                        )
                        continue

                    # Score with Phase 37 compute_ic
                    ic_df = compute_ic(
                        feature_series,
                        close_series,
                        train_start,
                        train_end,
                        horizons=horizons,
                        return_types=return_types,
                        tf_days_nominal=tf_days_nominal,
                    )

                    # Add asset/tf context columns
                    ic_df["asset_id"] = asset_id
                    ic_df["tf"] = tf

                    all_ic_rows.append(ic_df)

                except Exception as exc:
                    logger.warning(
                        "ExperimentRunner: failed for asset_id=%d feature=%s: %s",
                        asset_id,
                        feature_name,
                        exc,
                        exc_info=True,
                    )
                    continue

            # Commit scratch table writes for debug visibility
            if not dry_run:
                conn.commit()

        # Stop cost tracking
        wall_clock_seconds = time.perf_counter() - t0
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_memory_mb = peak_bytes / (1024 * 1024)

        if not all_ic_rows:
            logger.warning(
                "ExperimentRunner: no IC results produced for feature=%s", feature_name
            )
            return pd.DataFrame()

        # Concatenate all IC rows
        result_df = pd.concat(all_ic_rows, ignore_index=True)

        # Apply BH correction ONCE across ALL rows (all assets x horizons x return_types)
        result_df = self._apply_bh_correction(result_df)

        # Add feature metadata
        result_df["feature_name"] = feature_name
        result_df["yaml_digest"] = spec.get("yaml_digest", "")
        result_df["train_start"] = train_start
        result_df["train_end"] = train_end

        # Add cost metadata
        result_df["wall_clock_seconds"] = round(wall_clock_seconds, 3)
        result_df["peak_memory_mb"] = round(peak_memory_mb, 2)
        result_df["n_rows_computed"] = n_rows_computed

        logger.info(
            "ExperimentRunner: feature=%s done: %d IC rows in %.1fs (%.1f MB peak)",
            feature_name,
            len(result_df),
            wall_clock_seconds,
            peak_memory_mb,
        )

        return result_df

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _get_tf_days_nominal(self, tf: str) -> int:
        """Look up tf_days_nominal from dim_timeframe. Default 1 on failure."""
        from ta_lab2.time.dim_timeframe import DimTimeframe

        try:
            db_url = str(self.engine.url)
            dim = DimTimeframe.from_db(db_url)
            return dim.tf_days(tf)
        except Exception as exc:
            logger.warning(
                "Could not look up tf_days_nominal for tf=%s (%s) — defaulting to 1",
                tf,
                exc,
            )
            return 1

    def _create_scratch_table(self, conn: Any, scratch_name: str) -> None:
        """Create a session-scoped temp scratch table for feature value storage."""
        # Temp tables use unquoted names; use safe_name only (no schema prefix)
        conn.execute(
            text(
                f"""
                CREATE TEMP TABLE IF NOT EXISTS {scratch_name} (
                    id INTEGER NOT NULL,
                    ts TIMESTAMPTZ NOT NULL,
                    tf TEXT NOT NULL,
                    feature_name TEXT NOT NULL,
                    feature_val DOUBLE PRECISION
                )
                """
            )
        )
        logger.debug("Created temp scratch table: %s", scratch_name)

    def _load_inputs(
        self,
        conn: Any,
        spec: dict,
        asset_id: int,
        tf: str,
        train_start: pd.Timestamp,
        train_end: pd.Timestamp,
    ) -> pd.DataFrame:
        """
        Load input columns from declared source tables.

        Each entry in spec["inputs"] specifies a table and list of columns.
        Results from multiple inputs are merged by ts (inner join on ts index).

        SECURITY: Table names are validated against _ALLOWED_TABLES allowlist.
        Column names are validated to be simple identifiers (alphanumeric + underscore).
        All values (id, tf, dates) are parameterized.

        Parameters
        ----------
        conn : SQLAlchemy connection
        spec : dict
            Feature spec from FeatureRegistry.
        asset_id : int
        tf : str
        train_start, train_end : pd.Timestamp (tz-aware UTC)

        Returns
        -------
        pd.DataFrame
            Merged input data indexed by ts (UTC).
        """
        inputs = spec.get("inputs", [])
        if not inputs:
            return pd.DataFrame()

        merged: pd.DataFrame | None = None

        for inp in inputs:
            table = inp.get("table", "")
            columns = inp.get("columns", [])

            # Validate table name against allowlist (SQL injection prevention)
            if table not in _ALLOWED_TABLES:
                raise ValueError(
                    f"Input table '{table}' is not in the allowed tables list. "
                    f"Allowed: {sorted(_ALLOWED_TABLES)}"
                )

            # Validate column names (alphanumeric + underscore only)
            for col in columns:
                if not _is_safe_identifier(col):
                    raise ValueError(
                        f"Column name '{col}' contains unsafe characters. "
                        "Only alphanumeric and underscore are allowed."
                    )

            col_list = ", ".join(columns)

            # Build query — handle tables without tf column
            if table in _TABLES_WITHOUT_TF:
                sql_str = (
                    f"SELECT ts, {col_list} FROM public.{table} "
                    f"WHERE id = :id AND ts BETWEEN :start AND :end ORDER BY ts"
                )
                params = {
                    "id": asset_id,
                    "start": train_start,
                    "end": train_end,
                }
            else:
                sql_str = (
                    f"SELECT ts, {col_list} FROM public.{table} "
                    f"WHERE id = :id AND tf = :tf AND ts BETWEEN :start AND :end ORDER BY ts"
                )
                params = {
                    "id": asset_id,
                    "tf": tf,
                    "start": train_start,
                    "end": train_end,
                }

            df = pd.read_sql(text(sql_str), conn, params=params)

            if df.empty:
                logger.debug(
                    "_load_inputs: empty result from %s for asset_id=%d tf=%s",
                    table,
                    asset_id,
                    tf,
                )
                return pd.DataFrame()

            # Fix tz-aware timestamp (MEMORY.md pitfall)
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df = df.set_index("ts")

            if merged is None:
                merged = df
            else:
                # Inner join on ts index
                merged = merged.join(df, how="inner")

        return merged if merged is not None else pd.DataFrame()

    def _compute_feature(
        self,
        spec: dict,
        input_df: pd.DataFrame,
    ) -> pd.Series | None:
        """
        Compute feature values from input DataFrame.

        Dispatches based on compute mode:
        - 'inline': eval() expression with DataFrame columns as locals.
        - 'dotpath': import and call a Python function.

        Parameters
        ----------
        spec : dict
            Feature spec.
        input_df : pd.DataFrame
            Input data indexed by ts.

        Returns
        -------
        pd.Series or None
            Feature values indexed by ts.
        """
        compute = spec.get("compute", {})
        mode = compute.get("mode")

        if mode == "inline":
            expression = compute.get("expression", "")
            resolved_params = spec.get("resolved_params", {})

            # Build local namespace: DataFrame columns + resolved params
            local_vars: dict[str, Any] = {}
            for col in input_df.columns:
                local_vars[col] = input_df[col]
            # Also expose the full DataFrame as 'df'
            local_vars["df"] = input_df
            # Add resolved params
            local_vars.update(resolved_params)
            # Add close series if available
            if "close" in input_df.columns:
                local_vars["close"] = input_df["close"]

            # Restrict builtins for security
            safe_globals: dict[str, Any] = {
                "np": np,
                "pd": pd,
                "__builtins__": {},
            }

            try:
                result = eval(expression, safe_globals, local_vars)  # noqa: S307
            except Exception as exc:
                raise ValueError(
                    f"Failed to evaluate inline expression {expression!r}: {exc}"
                ) from exc

            if isinstance(result, pd.Series):
                return result
            # Try to coerce to Series with same index
            return pd.Series(result, index=input_df.index)

        elif mode == "dotpath":
            dotpath = compute.get("function", "")
            if ":" not in dotpath:
                raise ValueError(
                    f"Dotpath must use 'module.path:function_name' format, got: {dotpath!r}"
                )
            module_path, func_name = dotpath.rsplit(":", 1)
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            result = fn(input_df)

            if isinstance(result, pd.Series):
                return result
            return pd.Series(result, index=input_df.index)

        else:
            raise ValueError(
                f"Unknown compute mode: {mode!r}. Must be 'inline' or 'dotpath'."
            )

    def _get_close_series(
        self,
        conn: Any,
        input_df: pd.DataFrame,
        spec: dict,
        asset_id: int,
        tf: str,
        train_start: pd.Timestamp,
        train_end: pd.Timestamp,
    ) -> pd.Series | None:
        """
        Get close price series for IC scoring.

        If 'close' is already in input_df (loaded from price table), return it.
        Otherwise load from cmc_price_bars_multi_tf_u.

        Parameters
        ----------
        conn : SQLAlchemy connection
        input_df : pd.DataFrame (ts-indexed)
        spec, asset_id, tf, train_start, train_end: context

        Returns
        -------
        pd.Series indexed by ts (UTC), or None on failure.
        """
        if "close" in input_df.columns:
            return input_df["close"]

        # Load close from default price table
        sql_str = (
            f"SELECT ts, close FROM public.{_CLOSE_SOURCE_TABLE} "
            f"WHERE id = :id AND tf = :tf AND ts BETWEEN :start AND :end ORDER BY ts"
        )
        df = pd.read_sql(
            text(sql_str),
            conn,
            params={
                "id": asset_id,
                "tf": tf,
                "start": train_start,
                "end": train_end,
            },
        )

        if df.empty:
            logger.debug(
                "_get_close_series: no close data for asset_id=%d tf=%s",
                asset_id,
                tf,
            )
            return None

        # Fix tz-aware timestamp (MEMORY.md pitfall)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts")
        return df["close"]

    def _write_to_scratch(
        self,
        conn: Any,
        scratch_name: str,
        feature_series: pd.Series,
        asset_id: int,
        tf: str,
        feature_name: str,
    ) -> None:
        """
        Batch INSERT feature values into the temp scratch table.

        Uses executemany pattern with parameterized queries.

        Parameters
        ----------
        conn : SQLAlchemy connection
        scratch_name : str
            Name of the temp scratch table (created by _create_scratch_table).
        feature_series : pd.Series
            Feature values indexed by ts (UTC).
        asset_id : int
        tf : str
        feature_name : str
        """
        if feature_series.empty:
            return

        sql = text(
            f"""
            INSERT INTO {scratch_name} (id, ts, tf, feature_name, feature_val)
            VALUES (:id, :ts, :tf, :feature_name, :feature_val)
            """
        )

        params_list = []
        for ts, val in feature_series.items():
            params_list.append(
                {
                    "id": asset_id,
                    "ts": ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts,
                    "tf": tf,
                    "feature_name": feature_name,
                    "feature_val": float(val) if not _is_nan(val) else None,
                }
            )

        if params_list:
            conn.execute(sql, params_list)

        logger.debug(
            "_write_to_scratch: wrote %d rows to %s for asset_id=%d",
            len(params_list),
            scratch_name,
            asset_id,
        )

    def _apply_bh_correction(self, result_df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply Benjamini-Hochberg correction across ALL rows of a single run.

        BH correction is applied ONCE across all (asset_id, horizon, return_type)
        combinations — not per-asset. This is the correct conservative approach:
        we are testing multiple hypotheses simultaneously.

        NaN p-values are filtered before correction and restored as NaN after.

        Parameters
        ----------
        result_df : pd.DataFrame
            IC results with 'ic_p_value' column.

        Returns
        -------
        pd.DataFrame
            Same DataFrame with 'ic_p_value_bh' column added.
        """
        if "ic_p_value" not in result_df.columns:
            result_df["ic_p_value_bh"] = np.nan
            return result_df

        # Initialize output column with NaN
        result_df = result_df.copy()
        result_df["ic_p_value_bh"] = np.nan

        # Filter rows with valid (non-NaN) p-values
        valid_mask = result_df["ic_p_value"].notna()
        valid_pvals = result_df.loc[valid_mask, "ic_p_value"].values

        if len(valid_pvals) == 0:
            return result_df

        # Apply BH correction
        try:
            adjusted = false_discovery_control(valid_pvals, method="bh")
            result_df.loc[valid_mask, "ic_p_value_bh"] = adjusted
        except Exception as exc:
            logger.warning(
                "_apply_bh_correction: BH correction failed (%s) — ic_p_value_bh left as NaN",
                exc,
            )

        return result_df


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _is_safe_identifier(name: str) -> bool:
    """Return True if name contains only alphanumeric characters and underscores."""
    return all(c.isalnum() or c == "_" for c in name) and len(name) > 0


def _is_nan(val: Any) -> bool:
    """Return True if val is float NaN."""
    try:
        return math.isnan(val)
    except (TypeError, ValueError):
        return False
