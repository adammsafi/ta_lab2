"""lead_lag_analyzer.py

Macro-to-crypto lead-lag cross-correlation analyzer (MREG-11).

Scans all FRED float features against BTC and ETH daily returns across
lags [-60, +60] days, computes Bartlett significance thresholds, and
upserts results to cmc_macro_lead_lag_results.

Lead-lag convention (IMPORTANT):
    col_a = macro feature (reference), col_b = asset return (shifted)
    best_lag < 0: macro feature LEADS asset returns (macro is predictive)
    best_lag > 0: asset returns LEAD macro feature (macro is lagging)

This matches the lead_lag_max_corr() convention from ta_lab2.regimes.comovement:
    positive lag k means col_b is shifted forward k steps relative to col_a.

Bartlett significance threshold:
    For N overlapping observations, values beyond +/- 2/sqrt(N) are
    statistically significant at approximately the 95% confidence level
    under the null hypothesis of no serial correlation (Bartlett, 1946).

Lag range note:
    The lag range is [-60, +60] days. This was explicitly expanded from the
    original ROADMAP specification of [-20..+20] during the Phase 68 discuss
    session. The user chose the wider range to capture slower macro-to-crypto
    transmission channels. See 68-CONTEXT.md for the decision.

Usage:
    from ta_lab2.macro.lead_lag_analyzer import LeadLagAnalyzer
    from ta_lab2.io import get_engine

    engine = get_engine()
    analyzer = LeadLagAnalyzer(engine)
    df = analyzer.scan_all()
    rows = analyzer.upsert_results(df)
    print(f"Upserted {rows} rows to cmc_macro_lead_lag_results")
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.macro.hmm_classifier import (
    _HMM_CANDIDATE_COLUMNS,
    _get_table_columns,
    _sanitize_dataframe,
    _to_python,  # noqa: F401 -- re-exported for package-level use
)
from ta_lab2.regimes.comovement import lead_lag_max_corr

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Lag range: [-60, +60] days (expanded from original ROADMAP [-20..+20]).
# See 68-CONTEXT.md decision: user explicitly chose wider range to capture
# slower macro-to-crypto transmission channels.
_DEFAULT_LAG_RANGE = range(-60, 61)

# Default asset IDs to scan (BTC=1, ETH=2 per project dim conventions)
_DEFAULT_ASSET_IDS = [1, 2]

# Asset ID to human-readable name mapping for column naming
_ASSET_ID_TO_NAME: dict[int, str] = {
    1: "btc",
    2: "eth",
}

# Daily timeframe code for cmc_returns_bars_multi_tf
_RETURN_TF = "1D"


# ── LeadLagAnalyzer ─────────────────────────────────────────────────────────


class LeadLagAnalyzer:
    """Scan FRED macro features against crypto asset returns for lead-lag relationships.

    For each (macro_feature, asset_return) pair, finds the lag maximizing
    absolute Pearson correlation and assesses statistical significance using
    the Bartlett threshold (2/sqrt(N)).

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    lag_range:
        Range of lags to test. Default: range(-60, 61) per CONTEXT.md.
        Negative lags: macro leads asset returns.
        Positive lags: asset returns lead macro feature.

    Notes
    -----
    Lag convention: this class passes col_a=macro_feature, col_b=asset_return
    to lead_lag_max_corr(). Under that convention:
        best_lag < 0 means macro is predictive (leads crypto)
        best_lag > 0 means crypto leads macro (macro is lagging)
    """

    def __init__(
        self,
        engine: Engine,
        lag_range: range | None = None,
    ) -> None:
        self.engine = engine
        self.lag_range = lag_range if lag_range is not None else _DEFAULT_LAG_RANGE

    # ── Private helpers ───────────────────────────────────────────────────────

    def _discover_return_column(self) -> str:
        """Discover the primary return column in cmc_returns_bars_multi_tf.

        Prefers ret_cc (close-to-close return). Falls back to first ret_* column.

        Returns
        -------
        str
            Column name to use as the asset return metric.

        Raises
        ------
        ValueError
            If no ret_* columns exist in the table.
        """
        existing_cols = _get_table_columns(self.engine, "cmc_returns_bars_multi_tf")
        ret_cols = sorted(c for c in existing_cols if c.startswith("ret"))
        if not ret_cols:
            raise ValueError(
                "No ret_* columns found in cmc_returns_bars_multi_tf. "
                "Has the returns pipeline been run?"
            )
        # Prefer ret_cc (close-to-close); fall back to first available
        if "ret_cc" in ret_cols:
            col = "ret_cc"
        else:
            col = ret_cols[0]
            logger.warning(
                "_discover_return_column: ret_cc not found, falling back to '%s'", col
            )
        logger.info("_discover_return_column: using return column '%s'", col)
        return col

    def _load_macro_features(self) -> pd.DataFrame:
        """Load FRED float features from fred.fred_macro_features.

        Loads all columns from _HMM_CANDIDATE_COLUMNS that exist in the table,
        with date as a tz-naive DatetimeIndex.

        Returns
        -------
        pd.DataFrame
            Index: DatetimeIndex, tz-naive (normalized to date level).
            Columns: intersection of _HMM_CANDIDATE_COLUMNS and actual table columns.
        """
        existing_cols = _get_table_columns(
            self.engine, "fred_macro_features", schema="fred"
        )
        available = [c for c in _HMM_CANDIDATE_COLUMNS if c in existing_cols]

        if not available:
            raise ValueError(
                "No macro feature columns found in fred.fred_macro_features. "
                "Has Phase 65/66 run?"
            )

        col_list = ", ".join(["date"] + available)
        sql = text(f"SELECT {col_list} FROM fred.fred_macro_features ORDER BY date ASC")

        with self.engine.connect() as conn:
            df = pd.read_sql(sql, conn, parse_dates=["date"])

        df = df.set_index("date")
        # Normalize to tz-naive date-level index (macro features use DATE type)
        df.index = pd.to_datetime(df.index).normalize()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        logger.info(
            "_load_macro_features: %d rows, %d feature columns",
            len(df),
            len(df.columns),
        )
        return df

    def _load_asset_returns(
        self, asset_ids: list[int] | None = None, return_col: str = "ret_cc"
    ) -> pd.DataFrame:
        """Load daily asset returns from cmc_returns_bars_multi_tf.

        Loads returns for each asset_id at 1D timeframe, merges on timestamp
        (normalized to date-level for alignment with macro features).

        Parameters
        ----------
        asset_ids:
            List of asset IDs to load. Defaults to _DEFAULT_ASSET_IDS [1, 2].
        return_col:
            Column name for the return metric (default: "ret_cc").

        Returns
        -------
        pd.DataFrame
            Index: DatetimeIndex, tz-naive (normalized to date level).
            Columns: one per asset, named "{name}_1d_return"
                     (e.g. "btc_1d_return", "eth_1d_return").
        """
        ids = asset_ids if asset_ids is not None else _DEFAULT_ASSET_IDS
        frames: list[pd.DataFrame] = []

        for asset_id in ids:
            name = _ASSET_ID_TO_NAME.get(asset_id, f"asset_{asset_id}")
            col_alias = f"{name}_1d_return"
            sql = text(
                f"SELECT ts, {return_col} AS {col_alias} "
                "FROM cmc_returns_bars_multi_tf "
                "WHERE id = :id AND tf = :tf "
                "ORDER BY ts ASC"
            )
            with self.engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": _RETURN_TF})  # type: ignore[arg-type]

            if df.empty:
                logger.warning(
                    "_load_asset_returns: no returns found for id=%d tf=%s",
                    asset_id,
                    _RETURN_TF,
                )
                continue

            df = df.set_index("ts")
            # Normalize tz-aware timestamp to tz-naive date-level index
            # Critical: cmc_returns_bars_multi_tf.ts is TIMESTAMP WITH TZ;
            # fred_macro_features.date is DATE (tz-naive). Normalize before join.
            df.index = pd.to_datetime(df.index).normalize()
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            frames.append(df)
            logger.info(
                "_load_asset_returns: loaded %d rows for %s (id=%d)",
                len(df),
                col_alias,
                asset_id,
            )

        if not frames:
            raise ValueError(
                f"No asset returns loaded for ids={ids} tf={_RETURN_TF}. "
                "Ensure returns pipeline has been run."
            )

        # Merge all assets on date index (outer join to preserve all dates)
        result = frames[0]
        for frame in frames[1:]:
            result = result.join(frame, how="outer")

        return result

    # ── Public API ────────────────────────────────────────────────────────────

    def scan_all(self, asset_ids: list[int] | None = None) -> pd.DataFrame:
        """Scan all FRED float features against crypto returns for lead-lag relationships.

        For each (macro_feature, asset_return) pair, tests all lags in self.lag_range
        using lead_lag_max_corr() and computes Bartlett significance threshold.

        Parameters
        ----------
        asset_ids:
            Asset IDs to scan against. Defaults to [1, 2] (BTC, ETH).

        Returns
        -------
        pd.DataFrame
            One row per (macro_feature, asset_col) pair. Columns match
            cmc_macro_lead_lag_results schema:
                macro_feature, asset_col, computed_at, best_lag, best_corr,
                is_significant, n_obs, lag_range_min, lag_range_max,
                corr_by_lag_json.
        """
        logger.info(
            "scan_all: starting (lag_range=[%d, %d], asset_ids=%s)",
            min(self.lag_range),
            max(self.lag_range),
            asset_ids or _DEFAULT_ASSET_IDS,
        )

        # Discover return column
        return_col = self._discover_return_column()

        # Load data
        macro_df = self._load_macro_features()
        returns_df = self._load_asset_returns(
            asset_ids=asset_ids, return_col=return_col
        )

        # Build combined DataFrame aligned on date index
        # Use inner join so both macro and returns must have data
        combined = macro_df.join(returns_df, how="inner")
        logger.info(
            "scan_all: combined DataFrame has %d rows, %d columns",
            len(combined),
            len(combined.columns),
        )

        if combined.empty:
            logger.warning(
                "scan_all: no overlapping dates between macro features and asset returns"
            )
            return pd.DataFrame()

        # Identify feature and return columns
        macro_cols = [c for c in macro_df.columns if c in combined.columns]
        return_cols = [c for c in returns_df.columns if c in combined.columns]

        computed_at = datetime.date.today()
        lag_range_min = min(self.lag_range)
        lag_range_max = max(self.lag_range)

        rows: list[dict[str, Any]] = []
        total_pairs = len(macro_cols) * len(return_cols)
        significant_count = 0
        top_corrs: list[tuple[float, str, str, int]] = []  # (|corr|, macro, asset, lag)

        logger.info(
            "scan_all: scanning %d macro features x %d asset columns = %d pairs",
            len(macro_cols),
            len(return_cols),
            total_pairs,
        )

        for macro_col in macro_cols:
            for asset_col in return_cols:
                # Drop rows where either series is NaN for this pair
                pair_df = combined[[macro_col, asset_col]].dropna()
                n_obs = len(pair_df)

                if n_obs < abs(lag_range_min) + abs(lag_range_max) + 10:
                    logger.debug(
                        "scan_all: skipping %s vs %s (n_obs=%d too small for lag range)",
                        macro_col,
                        asset_col,
                        n_obs,
                    )
                    rows.append(
                        {
                            "macro_feature": macro_col,
                            "asset_col": asset_col,
                            "computed_at": computed_at,
                            "best_lag": None,
                            "best_corr": None,
                            "is_significant": None,
                            "n_obs": n_obs,
                            "lag_range_min": lag_range_min,
                            "lag_range_max": lag_range_max,
                            "corr_by_lag_json": None,
                        }
                    )
                    continue

                # Compute lead-lag correlation profile
                result = lead_lag_max_corr(
                    pair_df,
                    col_a=macro_col,
                    col_b=asset_col,
                    lags=self.lag_range,
                )

                # lead_lag_max_corr returns Dict[str, object]; cast to concrete types
                best_lag_raw: int = int(result["best_lag"])  # type: ignore[call-overload]
                best_corr_raw: float = float(result["best_corr"])  # type: ignore[arg-type]
                corr_by_lag_raw: pd.Series = result["corr_by_lag"]  # type: ignore[assignment]

                # Bartlett significance threshold: 2/sqrt(N)
                # Values beyond this threshold are ~95% significant under H0: no correlation
                bartlett_threshold = 2.0 / np.sqrt(n_obs)
                best_corr_finite = np.isfinite(best_corr_raw)
                is_significant = (
                    bool(abs(best_corr_raw) > bartlett_threshold)
                    if best_corr_finite
                    else None
                )

                if is_significant:
                    significant_count += 1

                # Convert corr_by_lag Series to JSON {lag: corr}
                corr_dict = {
                    int(lag): (float(corr) if np.isfinite(float(corr)) else None)  # type: ignore[call-overload]
                    for lag, corr in corr_by_lag_raw.items()
                }
                corr_by_lag_json = json.dumps(corr_dict)

                rows.append(
                    {
                        "macro_feature": macro_col,
                        "asset_col": asset_col,
                        "computed_at": computed_at,
                        "best_lag": best_lag_raw,
                        "best_corr": best_corr_raw if best_corr_finite else None,
                        "is_significant": is_significant,
                        "n_obs": n_obs,
                        "lag_range_min": lag_range_min,
                        "lag_range_max": lag_range_max,
                        "corr_by_lag_json": corr_by_lag_json,
                    }
                )

                # Track top correlations for summary log
                if best_corr_finite:
                    top_corrs.append(
                        (abs(best_corr_raw), macro_col, asset_col, best_lag_raw)
                    )

        df_out = pd.DataFrame(rows)

        # Summary logging
        logger.info(
            "scan_all: scanned %d pairs, %d significant (bartlett threshold)",
            total_pairs,
            significant_count,
        )
        if top_corrs:
            top5 = sorted(top_corrs, reverse=True)[:5]
            logger.info("scan_all: top 5 pairs by |best_corr|:")
            for abs_corr, macro_col, asset_col, lag in top5:
                direction = (
                    "macro leads"
                    if lag < 0
                    else ("asset leads" if lag > 0 else "concurrent")
                )
                logger.info(
                    "  %s vs %s: |corr|=%.4f at lag=%d (%s)",
                    macro_col,
                    asset_col,
                    abs_corr,
                    lag,
                    direction,
                )

        return df_out

    def upsert_results(self, df: pd.DataFrame) -> int:
        """Upsert lead-lag results into cmc_macro_lead_lag_results.

        Uses temp table + INSERT ... ON CONFLICT (macro_feature, asset_col, computed_at)
        DO UPDATE pattern, matching project upsert conventions.

        Parameters
        ----------
        df:
            DataFrame from scan_all(). Must have columns:
            macro_feature, asset_col, computed_at, best_lag, best_corr,
            is_significant, n_obs, lag_range_min, lag_range_max, corr_by_lag_json.

        Returns
        -------
        int
            Number of rows upserted.
        """
        if df.empty:
            logger.warning("upsert_results: empty DataFrame, nothing to write")
            return 0

        df = df.copy()
        df = _sanitize_dataframe(df)

        # Convert computed_at to datetime.date
        if "computed_at" in df.columns:
            df["computed_at"] = df["computed_at"].apply(
                lambda x: x.date()
                if isinstance(x, (pd.Timestamp, datetime.datetime))
                else x
            )

        pk_cols = ("macro_feature", "asset_col", "computed_at")
        non_pk_cols = [c for c in df.columns if c not in pk_cols]
        set_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in non_pk_cols)
        set_clause += ", ingested_at = now()"
        col_list = ", ".join(df.columns.tolist())

        with self.engine.begin() as conn:
            # Create staging temp table
            conn.execute(
                text(
                    "CREATE TEMP TABLE _lead_lag_staging "
                    "(LIKE cmc_macro_lead_lag_results INCLUDING DEFAULTS) "
                    "ON COMMIT DROP"
                )
            )

            # Write to staging
            df.to_sql(
                "_lead_lag_staging",
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )

            # Upsert from staging to target
            result = conn.execute(
                text(
                    f"INSERT INTO cmc_macro_lead_lag_results ({col_list}) "
                    f"SELECT {col_list} FROM _lead_lag_staging "
                    "ON CONFLICT (macro_feature, asset_col, computed_at) DO UPDATE SET "
                    f"{set_clause}"
                )
            )
            row_count = result.rowcount

        logger.info(
            "upsert_results: %d rows upserted to cmc_macro_lead_lag_results", row_count
        )
        return row_count
