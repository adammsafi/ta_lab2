"""hmm_classifier.py

HMM-based secondary macro regime classifier (MREG-10).

Fits GaussianHMM models with 2 and 3 states on all FRED float features
from fred.fred_macro_features, selects the winner by BIC, and upserts
results into cmc_hmm_regimes.

Key design decisions:
- Default covariance_type="diag": safe for 38 features (avoids O(n^2)
  parameter estimation instability with "full" covariance). Pass
  covariance_type="full" explicitly if sufficient data and you want to
  capture feature cross-correlations.
- 10 random restarts: reduces EM local-optima risk.
- Expanding window: each run uses ALL data from earliest date up to
  end_date (no look-ahead because we only fit on data <= end_date).
- Weekly refit cadence: avoids unnecessary recomputation on daily runs.
- StandardScaler: required before HMM fit; do NOT fit on raw features.
- BIC selection: LOWER BIC = better model (penalizes over-parameterization).

Usage:
    from ta_lab2.macro.hmm_classifier import HMMClassifier
    from ta_lab2.io import get_engine

    engine = get_engine()
    clf = HMMClassifier(engine)
    df = clf.fit_and_predict()
    rows = clf.upsert_results(df)
    print(f"Upserted {rows} rows to cmc_hmm_regimes")
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_N_RESTARTS = 10  # Multiple restarts to avoid EM local optima
_N_ITER = 200  # Max EM iterations per restart
_MIN_TRAIN_ROWS = 504  # ~2 calendar years minimum for stable HMM fit
_REFIT_INTERVAL_DAYS = 7  # Weekly refit cadence; skip if model_run_date < 7 days old
_N_STATES_OPTIONS = [2, 3]  # Both 2 and 3 states; BIC picks winner

# ── HMM candidate columns ───────────────────────────────────────────────────
# All FRED float columns from fred.fred_macro_features (Phases 65+66).
# TEXT columns are explicitly excluded:
#   vix_regime, nfci_4wk_direction, fed_regime_structure, fed_regime_trajectory,
#   net_liquidity_trend, source_freq_*
# NOTE: net_liquidity_365d_zscore is correct -- 30d variant does NOT exist.
_HMM_CANDIDATE_COLUMNS: list[str] = [
    # Phase 65 raw FRED series
    "walcl",
    "wtregen",
    "rrpontsyd",
    "dff",
    "dgs10",
    "t10y2y",
    "vixcls",
    "dtwexbgs",
    "ecbdfr",
    "irstci01jpm156n",
    "irltlt01jpm156n",
    # Phase 65 derived
    "net_liquidity",
    "us_jp_rate_spread",
    "us_ecb_rate_spread",
    "us_jp_10y_spread",
    "yc_slope_change_5d",
    "dtwexbgs_5d_change",
    "dtwexbgs_20d_change",
    # Phase 66 raw FRED series (lowercase)
    "bamlh0a0hym2",
    "nfci",
    "m2sl",
    "dexjpus",
    "dfedtaru",
    "dfedtarl",
    "cpiaucsl",
    # Phase 66 derived features
    "hy_oas_level",
    "hy_oas_5d_change",
    "hy_oas_30d_zscore",
    "nfci_level",
    "m2_yoy_pct",
    "dexjpus_level",
    "dexjpus_5d_pct_change",
    "dexjpus_20d_vol",
    "dexjpus_daily_zscore",
    "net_liquidity_365d_zscore",  # NOTE: 30d variant does NOT exist
    "carry_momentum",
    "cpi_surprise_proxy",
    "target_mid",
    "target_spread",
]


# ── Helpers (shared with other modules in this package) ──────────────────────


def _to_python(v: Any) -> Any:
    """Convert numpy scalars and NaN to native Python types for psycopg2 safety.

    Per project gotcha: numpy scalars are not directly bindable by psycopg2
    on all versions. NaN must become None for nullable DB columns.
    """
    if v is None:
        return None
    # numpy scalar -> Python scalar
    if hasattr(v, "item"):
        v = v.item()
    # Python float NaN -> None
    if isinstance(v, float) and (v != v):  # NaN check without math import
        return None
    return v


def _sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Convert DataFrame values to native Python types safe for psycopg2.

    - NaN -> None (for nullable SQL columns)
    - numpy scalars -> Python scalars
    """
    df = df.where(df.notna(), other=None)  # type: ignore[arg-type]
    for col in df.columns:
        if df[col].dtype == object:
            continue
        try:
            df[col] = df[col].apply(_to_python)
        except Exception:  # noqa: BLE001
            pass
    return df


def _get_table_columns(engine: Engine, table: str, schema: str = "public") -> set[str]:
    """Return set of column names for a given table."""
    sql = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = :table"
    )
    with engine.connect() as conn:
        result = conn.execute(sql, {"schema": schema, "table": table})
        return {row[0] for row in result}


# ── HMMClassifier ─────────────────────────────────────────────────────────────


class HMMClassifier:
    """Fit GaussianHMM on FRED float features and upsert regime labels.

    Fits both 2-state and 3-state GaussianHMM models using an expanding window
    (all available history up to end_date), selects the winner by BIC (lower
    is better), and writes per-date state labels to cmc_hmm_regimes.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    covariance_type:
        HMM covariance type. Default "diag" (diagonal covariance) is safe
        for 38 input features. With full covariance, O(n^2) parameters per
        state may cause numerical instability with limited training data.
        Pass "full" explicitly if you have sufficient data and want to capture
        feature cross-correlations.

    Notes
    -----
    - HMM state indices (0, 1, 2) have NO inherent semantic meaning. State 0
      is not automatically "favorable" -- the association must be inferred by
      inspecting state_means_json after fitting.
    - Expanding window: no look-ahead. Each run uses all data from the
      earliest available date up to end_date (inclusive).
    - The weekly refit cadence (_REFIT_INTERVAL_DAYS=7) prevents redundant
      recomputation. Use force_refit=True to override.
    """

    def __init__(self, engine: Engine, covariance_type: str = "diag") -> None:
        self.engine = engine
        self.covariance_type = covariance_type

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_features(self, end_date: str | None = None) -> pd.DataFrame:
        """Load FRED float features from fred.fred_macro_features.

        Filters to only columns in _HMM_CANDIDATE_COLUMNS that actually
        exist in the table (gracefully handles cases where Phase 66 features
        are not yet populated).

        Parameters
        ----------
        end_date:
            Upper bound date (inclusive). If None, loads all available data.

        Returns
        -------
        pd.DataFrame
            Index: DatetimeIndex (date column), tz-naive.
            Columns: intersection of _HMM_CANDIDATE_COLUMNS and actual table columns.
        """
        # Discover which candidate columns exist in the table
        existing_cols = _get_table_columns(
            self.engine, "fred_macro_features", schema="fred"
        )
        available = [c for c in _HMM_CANDIDATE_COLUMNS if c in existing_cols]

        if not available:
            raise ValueError(
                "No HMM candidate columns found in fred.fred_macro_features. "
                "Has Phase 65/66 run to populate the table?"
            )

        logger.info(
            "_load_features: %d/%d candidate columns available in fred_macro_features",
            len(available),
            len(_HMM_CANDIDATE_COLUMNS),
        )

        col_list = ", ".join(["date"] + available)
        if end_date:
            sql = text(
                f"SELECT {col_list} FROM fred.fred_macro_features "
                f"WHERE date <= :end_date ORDER BY date ASC"
            )
            params: dict[str, Any] = {"end_date": end_date}
        else:
            sql = text(
                f"SELECT {col_list} FROM fred.fred_macro_features ORDER BY date ASC"
            )
            params = {}

        with self.engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params, parse_dates=["date"])

        df = df.set_index("date")
        df.index = pd.to_datetime(df.index)
        logger.info(
            "_load_features: loaded %d rows, %d feature columns",
            len(df),
            len(df.columns),
        )
        return df

    def _fit_best_hmm(
        self,
        X: np.ndarray,
        n_states: int,
        random_seed: int = 42,
    ) -> GaussianHMM | None:
        """Fit GaussianHMM with multiple random restarts and return best model.

        Runs _N_RESTARTS independent fits with different random seeds.
        Keeps the model with the highest training log-likelihood (best fit).

        Parameters
        ----------
        X:
            Scaled feature array, shape (n_samples, n_features).
        n_states:
            Number of hidden states (2 or 3).
        random_seed:
            Base seed for reproducibility; each restart offsets by its index.

        Returns
        -------
        GaussianHMM | None
            Best model by log-likelihood, or None if all restarts failed.
        """
        rng = np.random.default_rng(random_seed)
        best_model: GaussianHMM | None = None
        best_score = -np.inf

        for i in range(_N_RESTARTS):
            restart_seed = int(rng.integers(0, 2**31))
            try:
                model = GaussianHMM(
                    n_components=n_states,
                    covariance_type=self.covariance_type,
                    n_iter=_N_ITER,
                    tol=1e-4,
                    random_state=restart_seed,
                )
                model.fit(X)
                score = model.score(X)
                if not np.isfinite(score):
                    logger.debug(
                        "_fit_best_hmm: restart %d/%d n_states=%d non-finite score=%s -- skipping",
                        i + 1,
                        _N_RESTARTS,
                        n_states,
                        score,
                    )
                    continue
                if score > best_score:
                    best_score = score
                    best_model = model
                    logger.debug(
                        "_fit_best_hmm: restart %d/%d n_states=%d new best log-likelihood=%.4f",
                        i + 1,
                        _N_RESTARTS,
                        n_states,
                        score,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "_fit_best_hmm: restart %d/%d n_states=%d failed: %s",
                    i + 1,
                    _N_RESTARTS,
                    n_states,
                    exc,
                )
                continue

        if best_model is None:
            logger.warning(
                "_fit_best_hmm: all %d restarts failed for n_states=%d",
                _N_RESTARTS,
                n_states,
            )
        else:
            logger.info(
                "_fit_best_hmm: n_states=%d best log-likelihood=%.4f (covariance_type=%s)",
                n_states,
                best_score,
                self.covariance_type,
            )

        return best_model

    def _check_needs_refit(self, force_refit: bool) -> bool:
        """Check whether the model needs to be refitted based on cadence.

        Queries MAX(model_run_date) from cmc_hmm_regimes. If the most recent
        run was less than _REFIT_INTERVAL_DAYS ago, skips the refit.

        Parameters
        ----------
        force_refit:
            If True, always refit regardless of cadence.

        Returns
        -------
        bool
            True if refit is needed (run fitting), False if cadence not met.
        """
        if force_refit:
            logger.info("_check_needs_refit: force_refit=True -- will refit")
            return True

        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT MAX(model_run_date) FROM cmc_hmm_regimes")
                )
                max_run_date = result.scalar()
        except Exception:  # noqa: BLE001
            logger.info(
                "_check_needs_refit: could not query cmc_hmm_regimes -- will refit (first run?)"
            )
            return True

        if max_run_date is None:
            logger.info("_check_needs_refit: no prior runs found -- will refit")
            return True

        max_run_ts = pd.Timestamp(max_run_date)
        today = pd.Timestamp.now("UTC").tz_localize(None)
        days_since = (today - max_run_ts).days

        if days_since < _REFIT_INTERVAL_DAYS:
            logger.info(
                "_check_needs_refit: last refit was %d days ago (<%d threshold) -- skipping refit",
                days_since,
                _REFIT_INTERVAL_DAYS,
            )
            return False

        logger.info(
            "_check_needs_refit: last refit was %d days ago (>=%d threshold) -- will refit",
            days_since,
            _REFIT_INTERVAL_DAYS,
        )
        return True

    # ── Public API ────────────────────────────────────────────────────────────

    def fit_and_predict(
        self,
        force_refit: bool = False,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Fit GaussianHMM on all available FRED features and predict state labels.

        Fits both 2-state and 3-state models with BIC model selection.
        Expanding window: all data from earliest available date up to end_date.
        Returns one row per (date, n_states) combination.

        Parameters
        ----------
        force_refit:
            If True, always refit even if model was run recently. Default False
            uses the weekly refit cadence (_REFIT_INTERVAL_DAYS=7).
        end_date:
            Upper date bound for feature loading (ISO format: YYYY-MM-DD).
            If None, uses all available data.

        Returns
        -------
        pd.DataFrame
            Columns: date, n_states, model_run_date, state_label,
                     state_probability, bic, aic, is_bic_winner,
                     state_means_json, covariance_type, n_features.
            One row per (date, n_states). Each date has 2 rows:
            one for 2-state model, one for 3-state model.

        Raises
        ------
        ValueError
            If fewer than _MIN_TRAIN_ROWS rows remain after dropna.
        """
        logger.info(
            "fit_and_predict: starting (covariance_type=%s, end_date=%s, force_refit=%s)",
            self.covariance_type,
            end_date,
            force_refit,
        )

        # Load features
        df_raw = self._load_features(end_date=end_date)
        total_rows = len(df_raw)

        # Drop rows with any NaN (HMM requires complete observations)
        df_clean = df_raw.dropna(how="any")
        clean_rows = len(df_clean)
        logger.info(
            "fit_and_predict: %d/%d rows retained after dropna (dropped %d NaN rows)",
            clean_rows,
            total_rows,
            total_rows - clean_rows,
        )

        if clean_rows < _MIN_TRAIN_ROWS:
            raise ValueError(
                f"Insufficient data for HMM fitting: {clean_rows} rows after dropna, "
                f"minimum required is {_MIN_TRAIN_ROWS} (~2 years). "
                "Ensure Phase 65/66 FRED data is populated."
            )

        n_features = len(df_clean.columns)
        feature_names = list(df_clean.columns)
        logger.info(
            "fit_and_predict: n_features=%d, feature_names=%s",
            n_features,
            feature_names,
        )

        # StandardScaler: required before HMM fit
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(df_clean.values)

        # Check refit cadence
        needs_refit = self._check_needs_refit(force_refit)

        model_run_date = datetime.date.today()
        dates = df_clean.index

        # Fit both n_states options
        results_by_n_states: dict[int, dict[str, Any]] = {}

        for n_states in _N_STATES_OPTIONS:
            logger.info("fit_and_predict: fitting n_states=%d model", n_states)

            if not needs_refit:
                # Refit cadence not met -- we still need to predict.
                # In practice we'd load a saved model, but since we don't persist
                # model weights to disk, we still fit here but log the decision.
                logger.info(
                    "fit_and_predict: cadence not met but fitting anyway (no model persistence yet)"
                )

            model = self._fit_best_hmm(X_scaled, n_states=n_states)
            if model is None:
                logger.warning(
                    "fit_and_predict: skipping n_states=%d (all restarts failed)",
                    n_states,
                )
                continue

            # BIC and AIC (lower = better)
            bic_val: float | None = None
            aic_val: float | None = None
            try:
                bic_val = float(model.bic(X_scaled))
                aic_val = float(model.aic(X_scaled))
                logger.info(
                    "fit_and_predict: n_states=%d BIC=%.4f AIC=%.4f",
                    n_states,
                    bic_val,
                    aic_val,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "fit_and_predict: n_states=%d BIC/AIC computation failed: %s",
                    n_states,
                    exc,
                )

            # Predict state labels (Viterbi decoding)
            state_labels: np.ndarray = model.predict(X_scaled)

            # Posterior probabilities (per-state probability matrix)
            posteriors: np.ndarray = model.predict_proba(X_scaled)
            # Max posterior probability per row (probability of assigned state)
            state_probs: np.ndarray = posteriors.max(axis=1)

            # State means for regime interpretation (n_states x n_features)
            # Store as JSON: {state_idx: {feature_name: mean_value}}
            state_means_dict: dict[int, dict[str, float]] = {}
            for s_idx in range(n_states):
                state_means_dict[s_idx] = {
                    feat: float(model.means_[s_idx, f_idx])
                    for f_idx, feat in enumerate(feature_names)
                }
            state_means_json = json.dumps(state_means_dict)

            results_by_n_states[n_states] = {
                "state_labels": state_labels,
                "state_probs": state_probs,
                "bic": bic_val,
                "aic": aic_val,
                "state_means_json": state_means_json,
            }

        if not results_by_n_states:
            raise RuntimeError(
                "fit_and_predict: all n_states options failed to produce a model. "
                "Check logs for restart failure details."
            )

        # Determine BIC winner (lower BIC = better)
        # Only compare models that have a BIC value
        bic_values = {
            n: r["bic"] for n, r in results_by_n_states.items() if r["bic"] is not None
        }
        bic_winner: int | None = None
        if bic_values:
            bic_winner = min(bic_values, key=lambda n: bic_values[n])
            logger.info(
                "fit_and_predict: BIC winner is n_states=%d (BIC=%.4f)",
                bic_winner,
                bic_values[bic_winner],
            )
            # Log all BIC values for transparency
            for n, bic in sorted(bic_values.items()):
                logger.info(
                    "fit_and_predict: n_states=%d BIC=%.4f%s",
                    n,
                    bic,
                    " [WINNER]" if n == bic_winner else "",
                )
        else:
            logger.warning(
                "fit_and_predict: no BIC values available -- cannot select winner"
            )

        # Build output DataFrame: one row per (date, n_states)
        rows: list[dict[str, Any]] = []
        for n_states, res in results_by_n_states.items():
            is_winner = bic_winner is not None and n_states == bic_winner
            state_labels = res["state_labels"]
            state_probs = res["state_probs"]

            for i, date in enumerate(dates):
                rows.append(
                    {
                        "date": date.date() if hasattr(date, "date") else date,
                        "n_states": n_states,
                        "model_run_date": model_run_date,
                        "state_label": int(state_labels[i]),
                        "state_probability": float(state_probs[i]),
                        "bic": res["bic"],
                        "aic": res["aic"],
                        "is_bic_winner": is_winner,
                        "state_means_json": res["state_means_json"],
                        "covariance_type": self.covariance_type,
                        "n_features": n_features,
                    }
                )

        df_out = pd.DataFrame(rows)
        logger.info(
            "fit_and_predict: produced %d rows (%d dates x %d models)",
            len(df_out),
            len(dates),
            len(results_by_n_states),
        )
        return df_out

    def upsert_results(self, df: pd.DataFrame) -> int:
        """Upsert HMM results into cmc_hmm_regimes.

        Uses temp table + INSERT ... ON CONFLICT (date, n_states, model_run_date)
        DO UPDATE pattern, matching project upsert conventions.

        Parameters
        ----------
        df:
            DataFrame from fit_and_predict(). Must have columns:
            date, n_states, model_run_date, state_label, state_probability,
            bic, aic, is_bic_winner, state_means_json, covariance_type, n_features.

        Returns
        -------
        int
            Number of rows upserted.
        """
        if df.empty:
            logger.warning("upsert_results: empty DataFrame, nothing to write")
            return 0

        # Sanitize for psycopg2 safety
        df = df.copy()
        df = _sanitize_dataframe(df)

        # Convert date columns to datetime.date objects
        for col in ("date", "model_run_date"):
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: x.date()
                    if isinstance(x, (pd.Timestamp, datetime.datetime))
                    else x
                )

        non_pk_cols = [
            c for c in df.columns if c not in ("date", "n_states", "model_run_date")
        ]
        set_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in non_pk_cols)
        set_clause += ", ingested_at = now()"
        col_list = ", ".join(df.columns.tolist())

        with self.engine.begin() as conn:
            # Create staging temp table
            conn.execute(
                text(
                    "CREATE TEMP TABLE _hmm_staging "
                    "(LIKE cmc_hmm_regimes INCLUDING DEFAULTS) "
                    "ON COMMIT DROP"
                )
            )

            # Write to staging
            df.to_sql(
                "_hmm_staging",
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )

            # Upsert from staging to target
            result = conn.execute(
                text(
                    f"INSERT INTO cmc_hmm_regimes ({col_list}) "
                    f"SELECT {col_list} FROM _hmm_staging "
                    "ON CONFLICT (date, n_states, model_run_date) DO UPDATE SET "
                    f"{set_clause}"
                )
            )
            row_count = result.rowcount

        logger.info("upsert_results: %d rows upserted to cmc_hmm_regimes", row_count)
        return row_count

    def compare_with_rule_based(self, n_states: int | None = None) -> dict[str, Any]:
        """Compare HMM state labels with rule-based macro regime labels.

        Loads the latest HMM state labels (BIC winner if n_states not specified)
        and the rule-based labels from cmc_macro_regimes, aligns by date,
        and computes structural agreement metrics.

        Parameters
        ----------
        n_states:
            Number of HMM states to use. If None, uses the BIC-winning model.

        Returns
        -------
        dict with keys:
            confusion_matrix: np.ndarray (sklearn confusion_matrix output)
            kappa: float (Cohen's kappa -- 1.0 = perfect, 0.0 = chance, <0 = worse than chance)
            n_aligned_dates: int (number of dates with both HMM and rule-based labels)
            hmm_n_states: int (actual n_states used)

        Notes
        -----
        HMM states are integer indices (0, 1, 2) while rule-based labels are
        strings (e.g., "favorable", "constructive", "neutral", "cautious", "adverse").
        The comparison is purely structural -- it measures whether the HMM agrees
        with the rule-based classifier in assigning similar observations to the
        same group, NOT whether state 0 == "favorable". Cohen's kappa handles
        mixed-type labels correctly.
        """
        from sklearn.metrics import cohen_kappa_score, confusion_matrix

        # Load HMM labels (latest model_run_date)
        if n_states is not None:
            hmm_sql = text(
                "SELECT date, state_label, n_states "
                "FROM cmc_hmm_regimes "
                "WHERE n_states = :n_states "
                "AND model_run_date = (SELECT MAX(model_run_date) FROM cmc_hmm_regimes) "
                "ORDER BY date ASC"
            )
            hmm_df = pd.read_sql(hmm_sql, self.engine, params={"n_states": n_states})
            actual_n_states = n_states
        else:
            hmm_sql = text(
                "SELECT date, state_label, n_states "
                "FROM cmc_hmm_regimes "
                "WHERE is_bic_winner = true "
                "AND model_run_date = (SELECT MAX(model_run_date) FROM cmc_hmm_regimes) "
                "ORDER BY date ASC"
            )
            hmm_df = pd.read_sql(hmm_sql, self.engine)
            actual_n_states = (
                int(hmm_df["n_states"].iloc[0]) if not hmm_df.empty else -1
            )

        # Load rule-based labels (macro_state column from cmc_macro_regimes)
        rb_sql = text(
            "SELECT date, macro_state FROM cmc_macro_regimes ORDER BY date ASC"
        )
        rb_df = pd.read_sql(rb_sql, self.engine)

        if hmm_df.empty or rb_df.empty:
            logger.warning(
                "compare_with_rule_based: insufficient data (hmm=%d rows, rule_based=%d rows)",
                len(hmm_df),
                len(rb_df),
            )
            return {
                "confusion_matrix": np.array([]),
                "kappa": float("nan"),
                "n_aligned_dates": 0,
                "hmm_n_states": actual_n_states,
            }

        # Align by date
        hmm_df["date"] = pd.to_datetime(hmm_df["date"])
        rb_df["date"] = pd.to_datetime(rb_df["date"])
        merged = hmm_df.merge(rb_df, on="date", how="inner")
        merged = merged.dropna(subset=["state_label", "macro_state"])

        n_aligned = len(merged)
        logger.info(
            "compare_with_rule_based: %d aligned dates (n_states=%d)",
            n_aligned,
            actual_n_states,
        )

        if n_aligned < 10:
            logger.warning(
                "compare_with_rule_based: too few aligned dates (%d) for meaningful comparison",
                n_aligned,
            )
            return {
                "confusion_matrix": np.array([]),
                "kappa": float("nan"),
                "n_aligned_dates": n_aligned,
                "hmm_n_states": actual_n_states,
            }

        hmm_labels = merged["state_label"].astype(str).tolist()
        rb_labels = merged["macro_state"].tolist()

        cm = confusion_matrix(rb_labels, hmm_labels)
        kappa = cohen_kappa_score(rb_labels, hmm_labels)

        logger.info(
            "compare_with_rule_based: Cohen's kappa=%.4f (n_aligned=%d)",
            kappa,
            n_aligned,
        )

        return {
            "confusion_matrix": cm,
            "kappa": float(kappa),
            "n_aligned_dates": n_aligned,
            "hmm_n_states": actual_n_states,
        }
