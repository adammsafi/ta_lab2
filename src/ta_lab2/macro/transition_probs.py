"""transition_probs.py

Regime transition probability matrix builder (MREG-12).

Computes static (full-history) and rolling (252-day) transition probability
matrices from both rule-based (cmc_macro_regimes) and HMM (cmc_hmm_regimes)
regime label sequences. Results are row-normalized (each row sums to 1.0)
and upserted to cmc_macro_transition_probs.

Key design decisions:
- DISTINCT ON (date) in _load_hmm_regimes: expanding-window HMM refits produce
  multiple rows per date (one per model_run_date). DISTINCT ON ensures only
  the row from the most recent model run is retained for each date.
- Rolling window = 252 days (1 trading year): provides ~1 year of regime
  history per window, balancing recency vs. statistical stability.
- Row-normalized matrices: probability[from, to] = count[from->to] / sum_row.
  Zero-count rows remain 0.0 (not NaN, not dropped from output).
- Both rule-based and HMM sources supported; graceful handling of empty tables.

Usage:
    from ta_lab2.macro.transition_probs import TransitionProbMatrix, get_transition_prob
    from ta_lab2.io import get_engine

    engine = get_engine()
    tpm = TransitionProbMatrix(engine)
    df = tpm.compute_all()
    rows = tpm.upsert_results(df)
    print(f"Upserted {rows} rows to cmc_macro_transition_probs")

    # Programmatic access
    prob = get_transition_prob(engine, "favorable", "adverse", window_type="static")
    print(f"P(favorable -> adverse) = {prob}")
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.macro.hmm_classifier import _sanitize_dataframe, _to_python

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

ROLLING_WINDOW_DAYS = 252  # 1 trading year for rolling window


# ── TransitionProbMatrix ─────────────────────────────────────────────────────


class TransitionProbMatrix:
    """Compute static and rolling regime transition probability matrices.

    Supports two regime sources:
        - "rule_based": labels from cmc_macro_regimes (MacroRegimeClassifier)
        - "hmm": labels from cmc_hmm_regimes (HMMClassifier BIC winner)

    The output shape is a flat DataFrame where each row represents a single
    (from_state, to_state) cell of the transition matrix, shaped for upsert
    into cmc_macro_transition_probs.
    """

    def __init__(self, engine: Engine, rolling_window_days: int = ROLLING_WINDOW_DAYS):
        self.engine = engine
        self.rolling_window_days = rolling_window_days

    # ── Regime label loaders ──────────────────────────────────────────────

    def _load_rule_based_regimes(self) -> pd.DataFrame:
        """Load rule-based macro regime labels from cmc_macro_regimes.

        Returns DataFrame with 'date' index and 'macro_state' column.
        Returns empty DataFrame if table is empty or does not exist.
        """
        try:
            query = text(
                "SELECT date, macro_state "
                "FROM cmc_macro_regimes "
                "WHERE profile = 'default' "
                "ORDER BY date ASC"
            )
            with self.engine.connect() as conn:
                rows = conn.execute(query).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "_load_rule_based_regimes: cmc_macro_regimes unavailable (%s). "
                "Run refresh_macro_regimes.py first.",
                exc,
            )
            return pd.DataFrame()

        if not rows:
            logger.warning(
                "_load_rule_based_regimes: cmc_macro_regimes has no 'default' profile rows. "
                "Run refresh_macro_regimes.py to populate."
            )
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["date", "macro_state"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        logger.info("_load_rule_based_regimes: loaded %d rows", len(df))
        return df

    def _load_hmm_regimes(self, n_states: int | None = None) -> pd.DataFrame:
        """Load HMM regime labels from cmc_hmm_regimes.

        When n_states is None, uses the BIC winner rows. DISTINCT ON (date)
        is applied so that each date returns exactly one row -- the most recent
        model_run_date -- preventing duplicate rows from expanding-window refits.

        When n_states is provided, filters to that n_states value and the
        most recent model_run_date for that configuration.

        State labels (int 0, 1, 2) are converted to strings ("state_0", etc.)
        for consistency with downstream consumers.

        Returns DataFrame with 'date' index and 'state_label' column.
        Returns empty DataFrame if table is empty or does not exist.
        """
        try:
            if n_states is None:
                # BIC winner path: latest model_run_date per date, is_bic_winner=true
                query = text(
                    "SELECT DISTINCT ON (date) date, state_label "
                    "FROM cmc_hmm_regimes "
                    "WHERE is_bic_winner = true "
                    "ORDER BY date, model_run_date DESC"
                )
                params: dict[str, Any] = {}
            else:
                # Explicit n_states path: most recent model_run_date for that n_states
                query = text(
                    "SELECT DISTINCT ON (date) date, state_label "
                    "FROM cmc_hmm_regimes "
                    "WHERE n_states = :n_states "
                    "  AND model_run_date = ("
                    "      SELECT MAX(model_run_date) FROM cmc_hmm_regimes "
                    "      WHERE n_states = :n_states"
                    "  ) "
                    "ORDER BY date"
                )
                params = {"n_states": n_states}

            with self.engine.connect() as conn:
                rows = conn.execute(query, params).fetchall()

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "_load_hmm_regimes: cmc_hmm_regimes unavailable (%s). "
                "Run refresh_macro_analytics.py --hmm-only first.",
                exc,
            )
            return pd.DataFrame()

        if not rows:
            logger.warning(
                "_load_hmm_regimes: no %s rows found in cmc_hmm_regimes. "
                "Run refresh_macro_analytics.py --hmm-only to populate.",
                "BIC winner" if n_states is None else f"n_states={n_states}",
            )
            if n_states is None:
                # Try fallback to n_states=2
                logger.info("_load_hmm_regimes: falling back to n_states=2")
                return self._load_hmm_regimes(n_states=2)
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["date", "state_label"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        # Convert integer state labels to string representation
        df["state_label"] = df["state_label"].apply(
            lambda x: f"state_{x}" if pd.notna(x) else None
        )

        # Drop rows where state_label is None (NULL in DB)
        df = df.dropna(subset=["state_label"])

        logger.info("_load_hmm_regimes: loaded %d rows", len(df))
        return df

    # ── Transition matrix computation ─────────────────────────────────────

    def _compute_transition_matrix(self, labels: pd.Series) -> pd.DataFrame:
        """Compute row-normalized transition probability matrix.

        For a sequence of regime labels, counts all consecutive (from, to)
        transitions and normalizes each row to sum to 1.0.

        Zero-count rows produce 0.0 probabilities (not NaN, not omitted).

        Parameters
        ----------
        labels:
            Series of regime label strings, indexed by date, sorted ascending.

        Returns
        -------
        Square DataFrame with states as both index and columns.
        Entries are probabilities in [0.0, 1.0].
        """
        if len(labels) < 2:
            return pd.DataFrame()

        # Get all unique states (sorted for deterministic output)
        states = sorted(labels.dropna().unique().tolist())
        if not states:
            return pd.DataFrame()

        # Build count matrix
        count_matrix: dict[str, dict[str, int]] = {
            s: {t: 0 for t in states} for s in states
        }

        label_values = labels.dropna().tolist()
        for i in range(len(label_values) - 1):
            from_state = label_values[i]
            to_state = label_values[i + 1]
            if from_state in count_matrix and to_state in count_matrix[from_state]:
                count_matrix[from_state][to_state] += 1
            elif from_state in count_matrix:
                # to_state appeared in labels but wasn't in initial state list
                # (shouldn't happen with sorted unique, but be defensive)
                count_matrix[from_state][to_state] = 1

        # Build DataFrame
        counts_df = pd.DataFrame(count_matrix, dtype=float).T
        counts_df = counts_df.reindex(index=states, columns=states, fill_value=0.0)

        # Row-normalize
        row_sums = counts_df.sum(axis=1)
        prob_df = counts_df.copy()
        for state in states:
            if row_sums[state] > 0:
                prob_df.loc[state] = counts_df.loc[state] / row_sums[state]
            else:
                prob_df.loc[state] = 0.0

        return prob_df

    def _flatten_matrix(
        self,
        prob_df: pd.DataFrame,
        count_df: pd.DataFrame | None,
        regime_source: str,
        window_type: str,
        window_end_date: datetime.date,
        window_days: int,
    ) -> pd.DataFrame:
        """Flatten a square transition matrix to row-per-cell format for DB storage.

        Each (from_state, to_state) cell becomes one row with columns:
            regime_source, window_type, window_end_date,
            from_state, to_state, probability,
            transition_count, total_from_count, window_days.
        """
        if prob_df.empty:
            return pd.DataFrame()

        records = []
        states = prob_df.index.tolist()

        for from_state in states:
            row_total = (
                int(count_df.loc[from_state].sum())
                if count_df is not None and from_state in count_df.index
                else 0
            )
            for to_state in states:
                prob = float(prob_df.loc[from_state, to_state])
                tc = (
                    int(count_df.loc[from_state, to_state])
                    if count_df is not None and from_state in count_df.index
                    else 0
                )
                records.append(
                    {
                        "regime_source": regime_source,
                        "window_type": window_type,
                        "window_end_date": window_end_date,
                        "from_state": from_state,
                        "to_state": to_state,
                        "probability": prob,
                        "transition_count": tc,
                        "total_from_count": row_total,
                        "window_days": window_days,
                    }
                )

        return pd.DataFrame(records)

    def _build_count_matrix(
        self, labels: pd.Series
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return (count_df, prob_df) for labels.

        count_df has raw integer counts; prob_df is row-normalized.
        """
        if len(labels) < 2:
            return pd.DataFrame(), pd.DataFrame()

        states = sorted(labels.dropna().unique().tolist())
        if not states:
            return pd.DataFrame(), pd.DataFrame()

        count_matrix: dict[str, dict[str, int]] = {
            s: {t: 0 for t in states} for s in states
        }

        label_values = labels.dropna().tolist()
        for i in range(len(label_values) - 1):
            from_state = label_values[i]
            to_state = label_values[i + 1]
            if from_state in count_matrix:
                if to_state not in count_matrix[from_state]:
                    count_matrix[from_state][to_state] = 0
                count_matrix[from_state][to_state] += 1

        counts_df = pd.DataFrame(count_matrix, dtype=float).T
        counts_df = counts_df.reindex(index=states, columns=states, fill_value=0.0)

        # Row-normalize
        row_sums = counts_df.sum(axis=1)
        prob_df = counts_df.copy()
        for state in states:
            if row_sums[state] > 0:
                prob_df.loc[state] = counts_df.loc[state] / row_sums[state]
            else:
                prob_df.loc[state] = 0.0

        return counts_df, prob_df

    # ── Public compute methods ────────────────────────────────────────────

    def compute_static(self, regime_source: str) -> pd.DataFrame:
        """Compute static (full-history) transition matrix for a regime source.

        Parameters
        ----------
        regime_source:
            "rule_based" or "hmm"

        Returns
        -------
        DataFrame shaped for cmc_macro_transition_probs upsert.
        """
        df = self._load_labels(regime_source)
        if df.empty:
            logger.warning(
                "compute_static(%s): empty label sequence, skipping", regime_source
            )
            return pd.DataFrame()

        label_col = "macro_state" if regime_source == "rule_based" else "state_label"
        labels = df[label_col].dropna()

        if len(labels) < 2:
            logger.warning(
                "compute_static(%s): fewer than 2 labels, cannot compute transitions",
                regime_source,
            )
            return pd.DataFrame()

        count_df, prob_df = self._build_count_matrix(labels)
        if prob_df.empty:
            return pd.DataFrame()

        window_end_date = labels.index.max().date()
        window_days = len(labels)

        result = self._flatten_matrix(
            prob_df=prob_df,
            count_df=count_df,
            regime_source=regime_source,
            window_type="static",
            window_end_date=window_end_date,
            window_days=window_days,
        )

        logger.info(
            "compute_static(%s): %d rows (window_days=%d, end=%s)",
            regime_source,
            len(result),
            window_days,
            window_end_date,
        )
        return result

    def compute_rolling(self, regime_source: str) -> pd.DataFrame:
        """Compute rolling transition matrices for a regime source.

        For each date from (min_date + rolling_window_days) to max_date,
        computes the transition matrix over the preceding rolling_window_days.

        Parameters
        ----------
        regime_source:
            "rule_based" or "hmm"

        Returns
        -------
        DataFrame shaped for cmc_macro_transition_probs upsert.
        All rolling windows concatenated.
        """
        df = self._load_labels(regime_source)
        if df.empty:
            logger.warning(
                "compute_rolling(%s): empty label sequence, skipping", regime_source
            )
            return pd.DataFrame()

        label_col = "macro_state" if regime_source == "rule_based" else "state_label"
        labels = df[label_col].dropna().sort_index()

        if len(labels) < self.rolling_window_days:
            logger.warning(
                "compute_rolling(%s): %d labels < window size %d, skipping",
                regime_source,
                len(labels),
                self.rolling_window_days,
            )
            return pd.DataFrame()

        all_frames: list[pd.DataFrame] = []

        dates = labels.index
        min_date = dates[0]

        # Compute rolling window for each end date
        cutoff = min_date + pd.Timedelta(days=self.rolling_window_days)
        end_dates = dates[dates >= cutoff]

        logger.info(
            "compute_rolling(%s): computing %d rolling windows (window=%d days)",
            regime_source,
            len(end_dates),
            self.rolling_window_days,
        )

        for end_date in end_dates:
            start_date = end_date - pd.Timedelta(days=self.rolling_window_days)
            window_labels = labels[
                (labels.index >= start_date) & (labels.index <= end_date)
            ]

            if len(window_labels) < 2:
                continue

            count_df, prob_df = self._build_count_matrix(window_labels)
            if prob_df.empty:
                continue

            frame = self._flatten_matrix(
                prob_df=prob_df,
                count_df=count_df,
                regime_source=regime_source,
                window_type="rolling",
                window_end_date=end_date.date(),
                window_days=self.rolling_window_days,
            )
            if not frame.empty:
                all_frames.append(frame)

        if not all_frames:
            logger.warning(
                "compute_rolling(%s): no rolling windows produced output", regime_source
            )
            return pd.DataFrame()

        result = pd.concat(all_frames, ignore_index=True)
        logger.info(
            "compute_rolling(%s): %d total rows across %d windows",
            regime_source,
            len(result),
            len(all_frames),
        )
        return result

    def compute_all(self) -> pd.DataFrame:
        """Compute all transition matrices (static + rolling, rule-based + HMM).

        Returns
        -------
        Combined DataFrame with all four combinations, shaped for
        cmc_macro_transition_probs upsert.
        """
        frames: list[pd.DataFrame] = []
        sources_processed: list[str] = []

        for source in ["rule_based", "hmm"]:
            # Static
            static = self.compute_static(source)
            if not static.empty:
                frames.append(static)
                sources_processed.append(f"{source}:static")

            # Rolling
            rolling = self.compute_rolling(source)
            if not rolling.empty:
                frames.append(rolling)
                sources_processed.append(f"{source}:rolling")

        if not frames:
            logger.warning(
                "compute_all: no transition rows produced. "
                "Ensure cmc_macro_regimes and cmc_hmm_regimes have data."
            )
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        logger.info(
            "compute_all: %d total transition rows computed. Sources: %s",
            len(result),
            ", ".join(sources_processed),
        )
        return result

    # ── DB upsert ─────────────────────────────────────────────────────────

    def upsert_results(self, df: pd.DataFrame) -> int:
        """Upsert transition probability DataFrame into cmc_macro_transition_probs.

        Uses temp table + ON CONFLICT (regime_source, window_type,
        window_end_date, from_state, to_state) DO UPDATE pattern.

        Parameters
        ----------
        df:
            DataFrame returned by compute_static(), compute_rolling(),
            or compute_all().

        Returns
        -------
        Number of rows upserted.
        """
        if df.empty:
            logger.warning("upsert_results: empty DataFrame, nothing to write")
            return 0

        df = df.copy()

        # Convert window_end_date to datetime.date for psycopg2
        df["window_end_date"] = df["window_end_date"].apply(
            lambda x: x.date()
            if isinstance(x, (pd.Timestamp, datetime.datetime))
            else x
        )

        # NaN -> None and numpy scalar -> Python scalar safety
        df = _sanitize_dataframe(df)

        # Columns that go into DB (all except ingested_at which uses server_default)
        cols = [
            "regime_source",
            "window_type",
            "window_end_date",
            "from_state",
            "to_state",
            "probability",
            "transition_count",
            "total_from_count",
            "window_days",
        ]

        col_list = ", ".join(cols)
        pk_cols = [
            "regime_source",
            "window_type",
            "window_end_date",
            "from_state",
            "to_state",
        ]
        update_cols = [c for c in cols if c not in pk_cols]
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        set_clause += ", ingested_at = now()"

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TEMP TABLE _tp_staging "
                    "(LIKE cmc_macro_transition_probs INCLUDING DEFAULTS) "
                    "ON COMMIT DROP"
                )
            )

            df[cols].to_sql(
                "_tp_staging",
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )

            result = conn.execute(
                text(
                    f"INSERT INTO cmc_macro_transition_probs ({col_list}) "
                    f"SELECT {col_list} FROM _tp_staging "
                    f"ON CONFLICT (regime_source, window_type, window_end_date, from_state, to_state) "
                    f"DO UPDATE SET {set_clause}"
                )
            )
            row_count = result.rowcount

        logger.info("upsert_results: %d rows upserted", row_count)
        return row_count

    # ── Internal helper ───────────────────────────────────────────────────

    def _load_labels(self, regime_source: str) -> pd.DataFrame:
        """Route label loading to the appropriate loader."""
        if regime_source == "rule_based":
            return self._load_rule_based_regimes()
        elif regime_source == "hmm":
            return self._load_hmm_regimes()
        else:
            raise ValueError(
                f"Unknown regime_source={regime_source!r}. "
                "Must be 'rule_based' or 'hmm'."
            )


# ── Module-level convenience wrapper ─────────────────────────────────────────


def get_transition_prob(
    engine: Engine,
    from_state: str,
    to_state: str,
    regime_source: str = "rule_based",
    window_type: str = "static",
    window_end_date: str | None = None,
) -> float | None:
    """Get transition probability for a specific regime-to-regime pair.

    Queries cmc_macro_transition_probs for the probability of transitioning
    from from_state to to_state under the specified regime_source and
    window_type.

    When window_end_date is None, returns the probability for the most recent
    window_end_date that matches the given regime_source AND window_type.
    This scoping is deliberate: different sources (rule_based vs hmm) and
    window types (static vs rolling) may have different latest dates.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to marketdata database.
    from_state:
        Source regime label (e.g. "favorable", "adverse", "state_0").
    to_state:
        Target regime label.
    regime_source:
        "rule_based" or "hmm" (default: "rule_based").
    window_type:
        "static" or "rolling" (default: "static").
    window_end_date:
        ISO date string (e.g. "2025-01-15") or None for latest available.
        When None, the most recent window_end_date for the matching
        regime_source + window_type is used automatically. No ValueError
        is raised for None + rolling; it simply uses the latest rolling date.

    Returns
    -------
    Probability as float in [0.0, 1.0], or None if no matching row found.
    """
    # IMPORTANT: MAX(window_end_date) subquery MUST be scoped to matching
    # regime_source AND window_type to prevent cross-contamination when sources
    # have different date ranges (e.g. HMM starts later than rule-based).
    query = text(
        "SELECT probability "
        "FROM cmc_macro_transition_probs "
        "WHERE regime_source = :src "
        "  AND window_type = :wt "
        "  AND from_state = :fs "
        "  AND to_state = :ts "
        "  AND window_end_date = COALESCE( "
        "        :date::date, "
        "        (SELECT MAX(window_end_date) "
        "         FROM cmc_macro_transition_probs "
        "         WHERE regime_source = :src AND window_type = :wt) "
        "      )"
    )

    date_param = window_end_date  # None or ISO string; COALESCE handles None

    try:
        with engine.connect() as conn:
            result = conn.execute(
                query,
                {
                    "src": regime_source,
                    "wt": window_type,
                    "fs": from_state,
                    "ts": to_state,
                    "date": date_param,
                },
            ).scalar()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "get_transition_prob: query failed (%s). "
            "Ensure cmc_macro_transition_probs is populated.",
            exc,
        )
        return None

    if result is None:
        return None

    return float(_to_python(result))
