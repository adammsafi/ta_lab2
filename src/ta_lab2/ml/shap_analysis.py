"""
SHAP TreeExplainer interaction analysis for LGBMRanker models.

Computes SHAP values and SHAP interaction values for a fitted LGBMRanker
(CrossSectionalRanker.model_) to reveal which feature pairs jointly drive
the cross-sectional ranking.

Design
------
- ``shap`` is lazy-imported inside methods (same pattern as lightgbm in
  double_ensemble.py) so this module is importable even when shap is not
  installed.  An informative ImportError is raised at call time.
- ``max_samples=500`` caps memory usage: the interaction tensor is
  O(n_samples * n_features * n_features) and can OOM on large datasets.
- Interaction values are the full SHAP interaction matrix (f, f) per sample;
  the diagonal entries are main-effect contributions (zeroed out before
  returning top pairs).
- update_feature_selection() writes an ``interactions`` key to
  feature_selection.yaml to satisfy the ML-02 feedback requirement.

References
----------
Lundberg et al. (2018): Consistent individualized feature attribution for
    tree ensembles.  https://arxiv.org/abs/1802.03888
shap.TreeExplainer: https://shap.readthedocs.io/
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import yaml

logger = logging.getLogger(__name__)

_SHAP_INSTALL_MSG = (
    "shap is required for RankerShapAnalyzer. Install it with: pip install shap"
)


def _import_shap() -> Any:
    """Lazy-import shap; raise informative error if not installed."""
    try:
        import shap  # noqa: PLC0415

        return shap
    except ImportError as e:
        raise ImportError(_SHAP_INSTALL_MSG) from e


class RankerShapAnalyzer:
    """
    SHAP TreeExplainer interaction analysis for a fitted LGBMRanker model.

    Parameters
    ----------
    model : lgb.LGBMRanker
        Fitted LightGBM ranker model (e.g. CrossSectionalRanker.model_).
    feature_names : list[str]
        Ordered list of feature column names matching the columns used to
        train the model.

    Attributes
    ----------
    shap_values_ : np.ndarray or None
        Shape (n_samples, n_features).  Set by compute_shap_values().
    interaction_values_ : np.ndarray or None
        Shape (n_samples, n_features, n_features).  Set by
        compute_interaction_values().
    mean_abs_interactions_ : np.ndarray or None
        Shape (n_features, n_features).  Mean absolute interaction strength,
        diagonal zeroed.  Set by compute_interaction_values().
    """

    def __init__(self, model: Any, feature_names: list[str]) -> None:
        self.model = model
        self.feature_names: list[str] = list(feature_names)
        self.shap_values_: np.ndarray | None = None
        self.interaction_values_: np.ndarray | None = None
        self.mean_abs_interactions_: np.ndarray | None = None

    # ------------------------------------------------------------------
    # SHAP values
    # ------------------------------------------------------------------

    def compute_shap_values(
        self,
        X_sample: np.ndarray,
        max_samples: int = 500,
    ) -> np.ndarray:
        """Compute SHAP values for the fitted ranker model.

        Parameters
        ----------
        X_sample : np.ndarray
            Feature matrix of shape (n_samples, n_features).  Subsample is
            taken if n_samples > max_samples.
        max_samples : int
            Maximum number of rows to use.  Default 500 for memory safety.

        Returns
        -------
        np.ndarray
            SHAP values, shape (n_samples, n_features).  Also stored as
            ``self.shap_values_``.
        """
        shap = _import_shap()

        if len(X_sample) > max_samples:
            rng = np.random.default_rng(42)
            idx = rng.choice(len(X_sample), size=max_samples, replace=False)
            idx.sort()
            X_sample = X_sample[idx]
            logger.info(
                "compute_shap_values: subsampled to %d rows (max_samples=%d)",
                max_samples,
                max_samples,
            )

        logger.info(
            "compute_shap_values: computing SHAP values for %d rows x %d features ...",
            X_sample.shape[0],
            X_sample.shape[1],
        )
        explainer = shap.TreeExplainer(self.model)
        shap_values = np.array(explainer.shap_values(X_sample))

        # TreeExplainer on LGBMRanker may return a list of arrays (one per class)
        # or a single (n, f) array.  Flatten to (n, f) by averaging if needed.
        if shap_values.ndim == 3:
            # (n_classes, n_samples, n_features) or (n_samples, n_features, n_classes)
            # LightGBM ranker typically returns (n_samples, n_features) directly;
            # handle both orientations defensively.
            if shap_values.shape[0] == X_sample.shape[0]:
                # Already (n_samples, n_features, something) — take mean over last axis
                shap_values = shap_values.mean(axis=-1)
            else:
                # (n_classes, n_samples, n_features) — take mean over first axis
                shap_values = shap_values.mean(axis=0)

        self.shap_values_ = shap_values
        logger.info("compute_shap_values: done, shape=%s", shap_values.shape)
        return shap_values

    # ------------------------------------------------------------------
    # SHAP interaction values
    # ------------------------------------------------------------------

    def compute_interaction_values(
        self,
        X_sample: np.ndarray,
        max_samples: int = 500,
    ) -> np.ndarray:
        """Compute SHAP interaction values (Shapley interaction index).

        The interaction tensor is O(n * f * f) — use max_samples to cap memory.

        Parameters
        ----------
        X_sample : np.ndarray
            Feature matrix of shape (n_samples, n_features).
        max_samples : int
            Maximum rows to use.  Default 500.

        Returns
        -------
        np.ndarray
            Interaction tensor, shape (n_samples, n_features, n_features).
            Also stored as ``self.interaction_values_``.
            ``self.mean_abs_interactions_`` is set to the (f, f) mean absolute
            interaction matrix with diagonal zeroed.
        """
        shap = _import_shap()

        if len(X_sample) > max_samples:
            rng = np.random.default_rng(42)
            idx = rng.choice(len(X_sample), size=max_samples, replace=False)
            idx.sort()
            X_sample = X_sample[idx]
            logger.info(
                "compute_interaction_values: subsampled to %d rows (max_samples=%d)",
                max_samples,
                max_samples,
            )

        logger.info(
            "compute_interaction_values: computing interaction values for "
            "%d rows x %d features (this may take several minutes) ...",
            X_sample.shape[0],
            X_sample.shape[1],
        )
        explainer = shap.TreeExplainer(self.model)
        interaction_values = np.array(explainer.shap_interaction_values(X_sample))

        # interaction_values shape: (n_samples, n_features, n_features)
        # Guard against extra dimensions from multi-output models
        if interaction_values.ndim == 4:
            # (n_samples, n_features, n_features, n_classes) — average over last
            interaction_values = interaction_values.mean(axis=-1)

        self.interaction_values_ = interaction_values

        # Mean absolute interaction: (f, f) matrix
        mean_abs = np.abs(interaction_values).mean(axis=0)

        # Zero the diagonal — diagonal entries are main effects, not interactions
        np.fill_diagonal(mean_abs, 0.0)
        self.mean_abs_interactions_ = mean_abs

        logger.info(
            "compute_interaction_values: done, tensor shape=%s",
            interaction_values.shape,
        )
        return interaction_values

    # ------------------------------------------------------------------
    # Top interaction pairs
    # ------------------------------------------------------------------

    def top_interaction_pairs(self, k: int = 5) -> list[dict]:
        """Return top k feature interaction pairs by mean absolute strength.

        Extracts the upper triangle of ``self.mean_abs_interactions_`` to
        avoid double-counting symmetric pairs.

        Parameters
        ----------
        k : int
            Number of top pairs to return (default 5).

        Returns
        -------
        list[dict]
            Each dict has keys:
            - ``feature_a`` (str): first feature name
            - ``feature_b`` (str): second feature name
            - ``mean_abs_interaction`` (float): interaction strength

            Sorted descending by ``mean_abs_interaction``.

        Raises
        ------
        RuntimeError
            If compute_interaction_values() has not been called yet.
        """
        if self.mean_abs_interactions_ is None:
            raise RuntimeError(
                "No interaction values available. "
                "Call compute_interaction_values() first."
            )

        mat = self.mean_abs_interactions_
        n = mat.shape[0]

        pairs: list[dict] = []
        for i in range(n):
            for j in range(i + 1, n):  # upper triangle only
                val = float(mat[i, j])
                if val > 0:
                    pairs.append(
                        {
                            "feature_a": self.feature_names[i],
                            "feature_b": self.feature_names[j],
                            "mean_abs_interaction": val,
                        }
                    )

        pairs.sort(key=lambda x: x["mean_abs_interaction"], reverse=True)
        return pairs[:k]

    # ------------------------------------------------------------------
    # Top SHAP features
    # ------------------------------------------------------------------

    def top_shap_features(self, k: int = 20) -> list[dict]:
        """Return top k features by mean absolute SHAP value.

        Parameters
        ----------
        k : int
            Number of top features (default 20).

        Returns
        -------
        list[dict]
            Each dict has keys:
            - ``feature`` (str): feature name
            - ``mean_abs_shap`` (float): mean absolute SHAP value

            Sorted descending.

        Raises
        ------
        RuntimeError
            If compute_shap_values() has not been called yet.
        """
        if self.shap_values_ is None:
            raise RuntimeError(
                "No SHAP values available. Call compute_shap_values() first."
            )

        mean_abs = np.abs(self.shap_values_).mean(axis=0)
        order = np.argsort(mean_abs)[::-1]

        result: list[dict] = []
        for idx in order[:k]:
            result.append(
                {
                    "feature": self.feature_names[idx],
                    "mean_abs_shap": float(mean_abs[idx]),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        top_k_interactions: int = 5,
        top_k_features: int = 20,
    ) -> str:
        """Generate a markdown report of SHAP findings.

        Parameters
        ----------
        top_k_interactions : int
            Number of top interaction pairs to show (default 5).
        top_k_features : int
            Number of top features to show (default 20).

        Returns
        -------
        str
            Markdown-formatted report string.
        """
        lines: list[str] = []
        lines.append("# SHAP Interaction Analysis Report")
        lines.append("")
        lines.append(
            f"Model: LGBMRanker | Features: {len(self.feature_names)} | Generated: auto"
        )
        lines.append("")

        # ------------------------------------------------------------------
        # Section 1: Feature importance
        # ------------------------------------------------------------------
        features = self.top_shap_features(k=top_k_features)
        lines.append(f"## SHAP Feature Importance (Top {top_k_features})")
        lines.append("")
        lines.append("| Rank | Feature | Mean |SHAP| |")
        lines.append("|------|---------|-------------|")
        for rank, item in enumerate(features, start=1):
            lines.append(
                f"| {rank} | `{item['feature']}` | {item['mean_abs_shap']:.6f} |"
            )
        lines.append("")

        # ------------------------------------------------------------------
        # Section 2: Interaction pairs
        # ------------------------------------------------------------------
        pairs = self.top_interaction_pairs(k=top_k_interactions)
        lines.append(f"## SHAP Interaction Pairs (Top {top_k_interactions})")
        lines.append("")
        lines.append("| Rank | Feature A | Feature B | Mean |Interaction| |")
        lines.append("|------|-----------|-----------|-----------------|")
        for rank, item in enumerate(pairs, start=1):
            lines.append(
                f"| {rank} | `{item['feature_a']}` | `{item['feature_b']}` "
                f"| {item['mean_abs_interaction']:.6f} |"
            )
        lines.append("")

        # ------------------------------------------------------------------
        # Section 3: Recommendations
        # ------------------------------------------------------------------
        lines.append("## Recommendations")
        lines.append("")
        if pairs:
            lines.append(
                "The following feature pairs exhibit strong interaction effects "
                "in the LGBMRanker.  Consider:"
            )
            lines.append("")
            lines.append(
                "1. **Feature engineering**: create product or ratio features "
                "from top-interacting pairs to make interactions explicit."
            )
            lines.append(
                "2. **Feature selection**: retain both members of each top pair "
                "even if one has low main-effect SHAP — the interaction "
                "contribution justifies inclusion."
            )
            lines.append(
                "3. **Model architecture**: if top pairs span different feature "
                "families (e.g. AMA momentum + CTF trend), ensure both "
                "families are represented in the active-tier selection."
            )
            lines.append("")
            lines.append("**Top interaction pairs identified:**")
            lines.append("")
            for rank, item in enumerate(pairs, start=1):
                lines.append(
                    f"- **{rank}.** `{item['feature_a']}` x `{item['feature_b']}` "
                    f"(strength={item['mean_abs_interaction']:.6f})"
                )
        else:
            lines.append(
                "No significant interaction pairs found.  "
                "This may indicate that the model relies primarily on "
                "independent main effects."
            )
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Feature selection update
    # ------------------------------------------------------------------

    def update_feature_selection(
        self,
        yaml_path: str,
        engine: Any = None,
        top_k_interactions: int = 3,
    ) -> None:
        """Write top interaction findings back to feature_selection.yaml.

        Loads the existing YAML, adds (or overwrites) an ``interactions`` key
        with the top k interaction pairs, and writes back to disk.

        If ``engine`` is provided, also updates the ``notes`` column in
        ``dim_feature_selection`` for each interacting feature with a note
        of the form "SHAP interaction partner: {other_feature}".

        Parameters
        ----------
        yaml_path : str
            Path to the feature_selection.yaml config file.
        engine : SQLAlchemy engine, optional
            If provided, used to update dim_feature_selection notes.
        top_k_interactions : int
            Number of top pairs to write to YAML (default 3).
        """
        from pathlib import Path

        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            logger.warning(
                "update_feature_selection: %s does not exist, will create.",
                yaml_path,
            )
            existing_config: dict = {}
        else:
            with open(yaml_path, encoding="utf-8") as f:
                existing_config = yaml.safe_load(f) or {}

        pairs = self.top_interaction_pairs(k=top_k_interactions)

        # Build serialisable list (no numpy types)
        interaction_entries = [
            {
                "feature_a": str(p["feature_a"]),
                "feature_b": str(p["feature_b"]),
                "strength": round(float(p["mean_abs_interaction"]), 8),
            }
            for p in pairs
        ]

        existing_config["interactions"] = interaction_entries

        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write("# Feature Selection Config -- generated by Phase 80\n")
            yaml.dump(existing_config, f, default_flow_style=False, allow_unicode=True)

        logger.info(
            "update_feature_selection: wrote %d interaction pairs to %s",
            len(interaction_entries),
            yaml_path,
        )

        # ------------------------------------------------------------------
        # Optional: update dim_feature_selection notes
        # ------------------------------------------------------------------
        if engine is not None and pairs:
            from sqlalchemy import text

            for pair in pairs:
                feat_a = pair["feature_a"]
                feat_b = pair["feature_b"]

                # Update notes for feature_a — note its interaction with feature_b
                note_a = f"SHAP interaction partner: {feat_b}"
                # Update notes for feature_b — note its interaction with feature_a
                note_b = f"SHAP interaction partner: {feat_a}"

                # NOTE: Use %% for literal % in SQLAlchemy text() with psycopg2;
                # single % would be interpreted as a format placeholder.
                # dim_feature_selection uses 'rationale' not 'notes' column.
                update_sql = text(
                    """
                    UPDATE public.dim_feature_selection
                    SET rationale = CASE
                        WHEN rationale IS NULL THEN :note
                        WHEN rationale NOT LIKE '%%SHAP interaction%%' THEN rationale || '; ' || :note
                        ELSE rationale
                    END
                    WHERE feature_name = :feature_name
                    """
                )
                with engine.begin() as conn:
                    conn.execute(update_sql, {"note": note_a, "feature_name": feat_a})
                    conn.execute(update_sql, {"note": note_b, "feature_name": feat_b})

            logger.info(
                "update_feature_selection: updated notes in dim_feature_selection "
                "for %d feature pairs",
                len(pairs),
            )
