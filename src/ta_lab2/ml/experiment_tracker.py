"""ML experiment tracking backed by PostgreSQL cmc_ml_experiments table.

Provides ExperimentTracker, a lightweight experiment manager that logs and
queries ML model runs.  Every training run (MDA/SFI ranking, regime routing,
DoubleEnsemble, Optuna sweep) should produce one row via ``log_run()``.

Design notes
------------
- Uses the cmc_ml_experiments table (DDL: sql/ml/095_cmc_ml_experiments.sql).
- ``ensure_table()`` runs the DDL idempotently (CREATE TABLE IF NOT EXISTS).
- All JSONB columns are serialised with ``json.dumps``; numpy scalars are
  normalised via the ``_to_python`` helper (``hasattr(v, 'item')`` pattern).
- Timestamps returned from the DB are converted to UTC-aware via
  ``pd.to_datetime(utc=True)`` to avoid the tz-naive pitfall on Windows.

Example
-------
    >>> from sqlalchemy import create_engine
    >>> engine = create_engine("postgresql://user:pass@host/db")
    >>> tracker = ExperimentTracker(engine)
    >>> tracker.ensure_table()
    >>> eid = tracker.log_run(
    ...     run_name="lgbm_1d_v1",
    ...     model_type="lgbm",
    ...     model_params={"n_estimators": 100, "num_leaves": 31},
    ...     feature_set=["rsi_14", "atr_14", "ret_arith"],
    ...     cv_method="purged_kfold",
    ...     train_start="2022-01-01",
    ...     train_end="2024-12-31",
    ...     asset_ids=[1, 2],
    ...     tf="1D",
    ...     oos_accuracy=0.54,
    ... )
    >>> run = tracker.get_run(eid)
    >>> df = tracker.list_runs(model_type="lgbm", limit=10)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_python(v: Any) -> Any:
    """Normalise numpy scalars to plain Python types.

    psycopg2 cannot bind numpy scalar types (e.g. ``np.float64``,
    ``np.int32``).  This helper converts them to the corresponding Python
    built-in using the ``.item()`` method, which is present on all numpy
    scalar types.
    """
    if hasattr(v, "item"):
        return v.item()
    return v


def _to_jsonb(v: Any) -> str | None:
    """Serialise a value to a JSONB-compatible JSON string.

    Handles None (returns None), dicts, lists, and objects whose values may
    include numpy scalars.
    """
    if v is None:
        return None

    def _recurse(obj: Any) -> Any:
        if hasattr(obj, "item"):
            return obj.item()
        if isinstance(obj, dict):
            return {k: _recurse(val) for k, val in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_recurse(val) for val in obj]
        return obj

    return json.dumps(_recurse(v))


def _compute_feature_set_hash(feature_set: list[str]) -> str:
    """SHA-256 of the sorted feature set joined by ','."""
    canonical = ",".join(sorted(feature_set))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _find_ddl_path() -> Path:
    """Locate sql/ml/095_cmc_ml_experiments.sql relative to this file."""
    # Walk up from src/ta_lab2/ml/ to project root then into sql/ml/
    here = Path(__file__).resolve()
    # up: ml/ -> ta_lab2/ -> src/ -> project root
    project_root = here.parent.parent.parent.parent
    ddl = project_root / "sql" / "ml" / "095_cmc_ml_experiments.sql"
    if not ddl.exists():
        # Fallback: env override
        env_path = os.environ.get("CMC_ML_DDL_PATH")
        if env_path:
            return Path(env_path)
        raise FileNotFoundError(
            f"DDL file not found at {ddl}. "
            "Set CMC_ML_DDL_PATH environment variable to override."
        )
    return ddl


# ---------------------------------------------------------------------------
# ExperimentTracker
# ---------------------------------------------------------------------------


class ExperimentTracker:
    """Lightweight PostgreSQL-backed ML experiment manager.

    Parameters
    ----------
    engine:
        SQLAlchemy engine pointing at the PostgreSQL database that contains
        (or will contain) the ``cmc_ml_experiments`` table.

    Methods
    -------
    ensure_table()
        Execute the DDL idempotently.
    log_run(...)
        Insert one experiment run and return its experiment_id UUID string.
    get_run(experiment_id)
        Fetch one run as a dict, or None if not found.
    list_runs(model_type, limit)
        Return a DataFrame of recent runs.
    compare_runs(experiment_ids)
        Return a DataFrame with key metric columns for side-by-side comparison.
    """

    TABLE = "public.cmc_ml_experiments"

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    def ensure_table(self) -> None:
        """Execute the DDL from sql/ml/095_cmc_ml_experiments.sql.

        Safe to call multiple times — the DDL uses ``CREATE TABLE IF NOT
        EXISTS`` so it is a no-op when the table already exists.
        """
        ddl_path = _find_ddl_path()
        # MEMORY.md: always open SQL files with encoding='utf-8' on Windows
        with open(ddl_path, encoding="utf-8") as f:
            ddl_sql = f.read()

        # Split on semicolons and execute each non-empty statement
        # (handles multi-statement DDL files: CREATE TABLE + CREATE INDEX + COMMENT)
        with self._engine.begin() as conn:
            for statement in ddl_sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(text(stmt))

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log_run(
        self,
        run_name: str,
        model_type: str,
        model_params: dict,
        feature_set: list[str],
        cv_method: str,
        train_start: Any,
        train_end: Any,
        asset_ids: list[int],
        tf: str,
        *,
        cv_n_splits: int | None = None,
        cv_embargo_frac: float | None = None,
        label_method: str | None = None,
        label_params: dict | None = None,
        oos_accuracy: float | None = None,
        oos_sharpe: float | None = None,
        oos_precision: float | None = None,
        oos_recall: float | None = None,
        oos_f1: float | None = None,
        n_oos_folds: int | None = None,
        mda_importances: dict | None = None,
        sfi_importances: dict | None = None,
        optuna_study_name: str | None = None,
        optuna_n_trials: int | None = None,
        optuna_best_params: dict | None = None,
        regime_routing: bool = False,
        regime_performance: dict | None = None,
        duration_seconds: float | None = None,
        notes: str | None = None,
    ) -> str:
        """Insert one ML experiment run and return its experiment_id.

        Parameters
        ----------
        run_name:
            Human-readable label (need not be unique).
        model_type:
            Model family: ``'lgbm'``, ``'random_forest'``, ``'double_ensemble'``,
            ``'regime_routed'``, etc.
        model_params:
            Full hyperparameter dict.
        feature_set:
            List of feature column names used in training.
        cv_method:
            Cross-validation method identifier: ``'purged_kfold'``, ``'cpcv'``,
            ``'walk_forward'``, etc.
        train_start, train_end:
            Training date range (ISO string or pandas Timestamp).
        asset_ids:
            List of integer asset IDs included in training.
        tf:
            Timeframe string (e.g. ``'1D'``, ``'4H'``).
        **kwargs:
            All optional columns listed in the method signature.

        Returns
        -------
        str
            The experiment_id UUID as a string.
        """
        feature_set_hash = _compute_feature_set_hash(feature_set)

        # Normalise timestamps to ISO strings for psycopg2
        train_start_str = (
            train_start.isoformat()
            if hasattr(train_start, "isoformat")
            else str(train_start)
        )
        train_end_str = (
            train_end.isoformat() if hasattr(train_end, "isoformat") else str(train_end)
        )

        # Normalise numpy scalars in the metric values
        def _norm(v: Any) -> Any:
            return _to_python(v)

        insert_sql = text(
            f"""
            INSERT INTO {self.TABLE} (
                run_name, model_type, model_params, feature_set, feature_set_hash,
                cv_method, cv_n_splits, cv_embargo_frac,
                label_method, label_params,
                train_start, train_end,
                asset_ids, tf,
                oos_accuracy, oos_sharpe, oos_precision, oos_recall, oos_f1,
                n_oos_folds,
                mda_importances, sfi_importances,
                optuna_study_name, optuna_n_trials, optuna_best_params,
                regime_routing, regime_performance,
                duration_seconds, notes
            )
            VALUES (
                :run_name, :model_type, CAST(:model_params AS JSONB), :feature_set, :feature_set_hash,
                :cv_method, :cv_n_splits, :cv_embargo_frac,
                :label_method, CAST(:label_params AS JSONB),
                CAST(:train_start AS TIMESTAMPTZ), CAST(:train_end AS TIMESTAMPTZ),
                CAST(:asset_ids AS INTEGER[]), :tf,
                :oos_accuracy, :oos_sharpe, :oos_precision, :oos_recall, :oos_f1,
                :n_oos_folds,
                CAST(:mda_importances AS JSONB), CAST(:sfi_importances AS JSONB),
                :optuna_study_name, :optuna_n_trials, CAST(:optuna_best_params AS JSONB),
                :regime_routing, CAST(:regime_performance AS JSONB),
                :duration_seconds, :notes
            )
            RETURNING experiment_id::TEXT
            """
        )

        params = {
            "run_name": run_name,
            "model_type": model_type,
            "model_params": _to_jsonb(model_params),
            "feature_set": list(feature_set),
            "feature_set_hash": feature_set_hash,
            "cv_method": cv_method,
            "cv_n_splits": _norm(cv_n_splits),
            "cv_embargo_frac": _norm(cv_embargo_frac),
            "label_method": label_method,
            "label_params": _to_jsonb(label_params),
            "train_start": train_start_str,
            "train_end": train_end_str,
            "asset_ids": "{" + ",".join(str(_norm(i)) for i in asset_ids) + "}",
            "tf": tf,
            "oos_accuracy": _norm(oos_accuracy),
            "oos_sharpe": _norm(oos_sharpe),
            "oos_precision": _norm(oos_precision),
            "oos_recall": _norm(oos_recall),
            "oos_f1": _norm(oos_f1),
            "n_oos_folds": _norm(n_oos_folds),
            "mda_importances": _to_jsonb(mda_importances),
            "sfi_importances": _to_jsonb(sfi_importances),
            "optuna_study_name": optuna_study_name,
            "optuna_n_trials": _norm(optuna_n_trials),
            "optuna_best_params": _to_jsonb(optuna_best_params),
            "regime_routing": bool(regime_routing),
            "regime_performance": _to_jsonb(regime_performance),
            "duration_seconds": _norm(duration_seconds),
            "notes": notes,
        }

        with self._engine.begin() as conn:
            row = conn.execute(insert_sql, params).fetchone()
        return str(row[0])

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_run(self, experiment_id: str) -> dict | None:
        """Fetch one experiment run by its UUID.

        Parameters
        ----------
        experiment_id:
            UUID string (as returned by ``log_run``).

        Returns
        -------
        dict or None
            Row as a plain dict, or None if not found.
        """
        sql = text(
            f"""
            SELECT *
            FROM {self.TABLE}
            WHERE experiment_id = CAST(:eid AS UUID)
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"eid": experiment_id}).mappings().fetchone()
        if row is None:
            return None
        return dict(row)

    def list_runs(
        self,
        model_type: str | None = None,
        limit: int = 50,
    ) -> pd.DataFrame:
        """Return a DataFrame of recent experiment runs.

        Parameters
        ----------
        model_type:
            Optional filter: only return runs with this ``model_type``.
        limit:
            Maximum number of rows to return (default 50).

        Returns
        -------
        pd.DataFrame
            Rows ordered by ``created_at DESC``.  Timestamp columns are
            UTC-aware.
        """
        where = "WHERE model_type = :model_type" if model_type is not None else ""
        sql = text(
            f"""
            SELECT
                experiment_id::TEXT,
                run_name,
                model_type,
                model_params,
                feature_set_hash,
                cv_method,
                cv_n_splits,
                train_start,
                train_end,
                tf,
                oos_accuracy,
                oos_sharpe,
                oos_precision,
                oos_recall,
                oos_f1,
                n_oos_folds,
                regime_routing,
                created_at,
                duration_seconds,
                notes
            FROM {self.TABLE}
            {where}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )
        params: dict[str, Any] = {"limit": limit}
        if model_type is not None:
            params["model_type"] = model_type

        with self._engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)

        # Ensure UTC-aware timestamps (MEMORY.md Windows pitfall)
        for col in ("train_start", "train_end", "created_at"):
            if col in df.columns and not df.empty:
                df[col] = pd.to_datetime(df[col], utc=True)

        return df

    def compare_runs(self, experiment_ids: list[str]) -> pd.DataFrame:
        """Return a DataFrame with key metric columns for side-by-side comparison.

        Parameters
        ----------
        experiment_ids:
            List of UUID strings to compare.

        Returns
        -------
        pd.DataFrame
            One row per experiment_id with columns: experiment_id, run_name,
            model_type, cv_method, oos_accuracy, oos_sharpe, oos_precision,
            oos_recall, oos_f1, n_oos_folds, regime_routing, created_at,
            duration_seconds.
        """
        if not experiment_ids:
            return pd.DataFrame()

        # Build a parameterised IN clause with individual named params
        param_names = [f"eid_{i}" for i in range(len(experiment_ids))]
        in_clause = ", ".join(f"CAST(:{p} AS UUID)" for p in param_names)

        sql = text(
            f"""
            SELECT
                experiment_id::TEXT,
                run_name,
                model_type,
                feature_set_hash,
                cv_method,
                cv_n_splits,
                cv_embargo_frac,
                tf,
                oos_accuracy,
                oos_sharpe,
                oos_precision,
                oos_recall,
                oos_f1,
                n_oos_folds,
                regime_routing,
                optuna_study_name,
                optuna_n_trials,
                created_at,
                duration_seconds,
                notes
            FROM {self.TABLE}
            WHERE experiment_id IN ({in_clause})
            ORDER BY created_at DESC
            """
        )
        params = {p: eid for p, eid in zip(param_names, experiment_ids)}

        with self._engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)

        # Ensure UTC-aware timestamps
        if "created_at" in df.columns and not df.empty:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True)

        return df
