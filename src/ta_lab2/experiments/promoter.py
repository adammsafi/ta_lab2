"""FeaturePromoter: BH gate, promotion pipeline, and deprecation workflow.

Orchestrates the lifecycle transition of experimental features from
'experimental' to 'promoted' via a Benjamini-Hochberg correction gate.
On promotion:
  1. Validates BH-corrected p-values at a user-supplied alpha threshold.
  2. Writes to dim_feature_registry with lifecycle='promoted'.
  3. Generates an Alembic migration stub in alembic/versions/ that adds
     a NUMERIC nullable column to cmc_features.
  4. Prints manual-step instructions for wiring the feature into the
     cmc_features refresh pipeline.

Deprecation is non-destructive: sets lifecycle='deprecated' in
dim_feature_registry but does NOT remove the cmc_features column or
purge experiment rows.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from scipy.stats import false_discovery_control
from sqlalchemy import text
from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PromotionRejectedError(Exception):
    """Raised when the BH gate rejects a feature for promotion.

    Attributes
    ----------
    reason:
        Human-readable description of why the feature was rejected.
    bh_results:
        DataFrame with BH-adjusted p-values for diagnostic inspection.
    """

    def __init__(self, reason: str, bh_results: pd.DataFrame) -> None:
        super().__init__(reason)
        self.reason = reason
        self.bh_results = bh_results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_python(val: Any) -> Any:
    """Normalize numpy scalar to Python native type for psycopg2 binding."""
    if val is None:
        return None
    if hasattr(val, "item"):
        # numpy scalar (e.g. np.float64, np.int64)
        return val.item()
    return val


def _slugify(name: str) -> str:
    """Convert a feature name to a safe slug for filenames."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower())
    return slug.strip("_")


def _find_alembic_versions_dir() -> str:
    """Locate alembic/versions/ relative to this file (walk up to project root).

    Returns the absolute path to alembic/versions/.

    Raises
    ------
    FileNotFoundError
        If alembic/versions/ is not found within 6 parent directories.
    """
    # This file is at src/ta_lab2/experiments/promoter.py
    # Project root is 3 levels up.
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(current, "alembic", "versions")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        "alembic/versions/ directory not found. "
        "Ensure you are running from within the ta_lab2 project."
    )


# ---------------------------------------------------------------------------
# FeaturePromoter
# ---------------------------------------------------------------------------


class FeaturePromoter:
    """Orchestrates the experimental-to-promoted lifecycle transition.

    Parameters
    ----------
    engine:
        SQLAlchemy engine (NullPool recommended -- caller creates).
    registry:
        Optional FeatureRegistry instance. When provided, promotion also
        writes description, compute_mode, compute_spec, input_tables,
        input_columns, tags, and yaml_digest from the YAML spec.

    Example usage::

        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        from ta_lab2.experiments import FeaturePromoter
        from ta_lab2.scripts.refresh_utils import resolve_db_url

        engine = create_engine(resolve_db_url(), poolclass=NullPool)
        promoter = FeaturePromoter(engine)
        stub_path = promoter.promote_feature("vol_ratio_30_7", alpha=0.05)
    """

    def __init__(self, engine: Engine, registry: Any | None = None) -> None:
        self._engine = engine
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_bh_gate(
        self,
        ic_results_df: pd.DataFrame,
        alpha: float = 0.05,
        min_pass_rate: float = 0.0,
    ) -> tuple[bool, pd.DataFrame, str]:
        """Apply Benjamini-Hochberg correction and evaluate the gate.

        Parameters
        ----------
        ic_results_df:
            DataFrame with at least an 'ic_p_value' column. Typically
            loaded from cmc_feature_experiments.
        alpha:
            BH significance threshold. Default 0.05.
        min_pass_rate:
            Minimum fraction of test combos that must pass BH.
            If 0.0 (default), at least one pass is required.

        Returns
        -------
        (passed, enriched_df, reason)
            passed: True when the gate is satisfied.
            enriched_df: Input df with 'ic_p_value_bh' column added.
            reason: Human-readable gate result description.
        """
        df = ic_results_df.copy()

        # Filter NaN p-values -- false_discovery_control raises ValueError on NaN
        valid_mask = df["ic_p_value"].notna()
        valid_pvals_series = df.loc[valid_mask, "ic_p_value"]

        n_valid = len(valid_pvals_series)

        if n_valid == 0:
            df["ic_p_value_bh"] = float("nan")
            return (
                False,
                df,
                "No valid p-values (all NaN) -- gate rejected.",
            )

        # Apply BH correction to the valid subset
        adjusted = false_discovery_control(
            valid_pvals_series.values.astype(float), method="bh"
        )
        df.loc[valid_mask, "ic_p_value_bh"] = adjusted

        # Count passing combos
        n_pass = int((df.loc[valid_mask, "ic_p_value_bh"] < alpha).sum())
        pass_rate = n_pass / n_valid

        if min_pass_rate == 0.0:
            passed = n_pass > 0
        else:
            passed = pass_rate >= min_pass_rate

        if passed:
            reason = (
                f"BH gate passed: {n_pass}/{n_valid} combos significant "
                f"(pass_rate={pass_rate:.2%}, alpha={alpha})."
            )
        else:
            reason = (
                f"BH gate rejected: {n_pass}/{n_valid} combos significant "
                f"(pass_rate={pass_rate:.2%}, required>={min_pass_rate:.2%} at alpha={alpha})."
            )

        return (passed, df, reason)

    def promote_feature(
        self,
        feature_name: str,
        *,
        alpha: float = 0.05,
        min_pass_rate: float = 0.0,
        confirm: bool = True,
    ) -> str:
        """Promote a feature from experimental to promoted lifecycle.

        Steps:
        1. Load experiment results from cmc_feature_experiments.
        2. Apply BH gate -- raise PromotionRejectedError if it fails.
        3. Find best IC row among BH-significant results.
        4. Optionally confirm with user.
        5. Write to dim_feature_registry (lifecycle='promoted').
        6. Generate Alembic migration stub.
        7. Update dim_feature_registry with migration_stub_path.
        8. Print manual-step instructions.

        Parameters
        ----------
        feature_name:
            Name of the feature to promote (must match cmc_feature_experiments).
        alpha:
            BH significance threshold (default 0.05).
        min_pass_rate:
            Minimum fraction of combos that must pass BH (default 0.0 = any).
        confirm:
            If True, prompt user before writing to DB. Set False (or --yes)
            for non-interactive use.

        Returns
        -------
        str
            Absolute path to the generated Alembic migration stub file.

        Raises
        ------
        ValueError
            If no experiment results exist for the feature.
        PromotionRejectedError
            If the BH gate rejects the feature.
        """
        # Step 1: Load experiment results
        ic_df = self._load_experiment_results(feature_name)
        if ic_df.empty:
            raise ValueError(
                f"No experiment results found for feature '{feature_name}' "
                "in cmc_feature_experiments."
            )

        # Step 2: BH gate
        passed, bh_df, reason = self.check_bh_gate(
            ic_df, alpha=alpha, min_pass_rate=min_pass_rate
        )
        if not passed:
            raise PromotionRejectedError(reason=reason, bh_results=bh_df)

        # Step 3: Best IC row (highest |IC| among BH-significant rows)
        sig_mask = bh_df["ic_p_value_bh"].notna() & (bh_df["ic_p_value_bh"] < alpha)
        sig_df = bh_df[sig_mask].copy()
        sig_df["_abs_ic"] = sig_df["ic"].abs()
        best_row = sig_df.loc[sig_df["_abs_ic"].idxmax()]
        best_ic = _to_python(best_row.get("ic"))
        best_horizon = _to_python(best_row.get("horizon"))

        # Step 4: Optional confirmation
        print(f"\nPromotion summary for '{feature_name}':")
        print(f"  BH gate: PASSED -- {reason}")
        print(
            f"  Best IC:      {best_ic:.6f}"
            if best_ic is not None
            else "  Best IC:      N/A"
        )
        print(
            f"  Best horizon: {best_horizon} bars"
            if best_horizon is not None
            else "  Best horizon: N/A"
        )
        print(f"  Significant combos: {sig_mask.sum()}/{len(bh_df)} (alpha={alpha})")

        if confirm:
            answer = input(f"\nPromote '{feature_name}'? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print("Promotion cancelled.")
                return ""

        # Step 5: Write to dim_feature_registry
        self._write_to_registry(
            feature_name=feature_name,
            alpha=alpha,
            min_pass_rate=min_pass_rate,
            best_ic=best_ic,
            best_horizon=best_horizon,
        )

        # Step 6: Generate migration stub
        stub_path = self._generate_migration_stub(feature_name)

        # Step 7: Update registry with stub path
        self._update_stub_path(feature_name, stub_path)

        # Step 8: Print instructions
        print(f"\nMigration stub created at: {stub_path}")
        print("Next steps:")
        print("  1. Review the migration stub.")
        print("  2. Run: alembic upgrade head")
        print("  3. Add computation to src/ta_lab2/features/promoted_features.py")
        print(f"     (create a compute function for '{feature_name}' and register it)")

        return stub_path

    def deprecate_feature(self, feature_name: str) -> None:
        """Deprecate a feature by setting lifecycle='deprecated'.

        Non-destructive: does NOT remove the column from cmc_features and
        does NOT delete rows from cmc_feature_experiments (audit trail preserved).

        Parameters
        ----------
        feature_name:
            Name of the feature to deprecate.
        """
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.dim_feature_registry
                    SET lifecycle = 'deprecated',
                        updated_at = NOW()
                    WHERE feature_name = :name
                    """
                ),
                {"name": feature_name},
            )
        print(
            f"Feature '{feature_name}' deprecated. "
            "Column remains in cmc_features but will no longer be computed."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_experiment_results(self, feature_name: str) -> pd.DataFrame:
        """Load IC results from cmc_feature_experiments for a feature."""
        with self._engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT
                        feature_name,
                        asset_id,
                        tf,
                        horizon,
                        return_type,
                        regime_col,
                        regime_label,
                        ic,
                        ic_t_stat,
                        ic_p_value,
                        ic_ir,
                        n_obs
                    FROM public.cmc_feature_experiments
                    WHERE feature_name = :name
                    ORDER BY horizon, asset_id, tf
                    """
                ),
                {"name": feature_name},
            )
            rows = result.fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows, columns=list(result.keys()))

    def _write_to_registry(
        self,
        *,
        feature_name: str,
        alpha: float,
        min_pass_rate: float,
        best_ic: float | None,
        best_horizon: int | None,
    ) -> None:
        """Write or update the dim_feature_registry entry for promotion."""
        # Pull extra metadata from registry if available
        spec: dict = {}
        if self._registry is not None:
            try:
                spec = self._registry.get_feature(feature_name)
            except KeyError:
                pass

        description = spec.get("description")
        compute = spec.get("compute", {})
        compute_mode = compute.get("mode")
        compute_spec_str: str | None = None
        if compute_mode == "inline":
            compute_spec_str = compute.get("expression")
        elif compute_mode == "dotpath":
            compute_spec_str = compute.get("function")

        input_tables = spec.get("input_tables")
        input_columns = spec.get("input_columns")
        tags = spec.get("tags")
        yaml_digest = spec.get("yaml_digest")

        now = datetime.now(timezone.utc)

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO public.dim_feature_registry (
                        feature_name,
                        lifecycle,
                        description,
                        yaml_digest,
                        compute_mode,
                        compute_spec,
                        input_tables,
                        input_columns,
                        tags,
                        promoted_at,
                        promotion_alpha,
                        promotion_min_pass_rate,
                        best_ic,
                        best_horizon,
                        updated_at
                    ) VALUES (
                        :feature_name,
                        'promoted',
                        :description,
                        :yaml_digest,
                        :compute_mode,
                        :compute_spec,
                        :input_tables,
                        :input_columns,
                        :tags,
                        :promoted_at,
                        :promotion_alpha,
                        :promotion_min_pass_rate,
                        :best_ic,
                        :best_horizon,
                        :updated_at
                    )
                    ON CONFLICT (feature_name) DO UPDATE SET
                        lifecycle = 'promoted',
                        promoted_at = EXCLUDED.promoted_at,
                        promotion_alpha = EXCLUDED.promotion_alpha,
                        promotion_min_pass_rate = EXCLUDED.promotion_min_pass_rate,
                        best_ic = EXCLUDED.best_ic,
                        best_horizon = EXCLUDED.best_horizon,
                        description = COALESCE(EXCLUDED.description, dim_feature_registry.description),
                        yaml_digest = COALESCE(EXCLUDED.yaml_digest, dim_feature_registry.yaml_digest),
                        compute_mode = COALESCE(EXCLUDED.compute_mode, dim_feature_registry.compute_mode),
                        compute_spec = COALESCE(EXCLUDED.compute_spec, dim_feature_registry.compute_spec),
                        input_tables = COALESCE(EXCLUDED.input_tables, dim_feature_registry.input_tables),
                        input_columns = COALESCE(EXCLUDED.input_columns, dim_feature_registry.input_columns),
                        tags = COALESCE(EXCLUDED.tags, dim_feature_registry.tags),
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "feature_name": feature_name,
                    "description": description,
                    "yaml_digest": yaml_digest,
                    "compute_mode": compute_mode,
                    "compute_spec": compute_spec_str,
                    "input_tables": input_tables,
                    "input_columns": input_columns,
                    "tags": tags,
                    "promoted_at": now,
                    "promotion_alpha": _to_python(alpha),
                    "promotion_min_pass_rate": _to_python(min_pass_rate),
                    "best_ic": best_ic,
                    "best_horizon": best_horizon,
                    "updated_at": now,
                },
            )

    def _generate_migration_stub(self, feature_name: str) -> str:
        """Generate an Alembic migration stub for adding the feature column.

        Queries the live Alembic head from alembic_version (not hardcoded).
        Writes to alembic/versions/{rev_id}_promoted_{slug}.py.

        Parameters
        ----------
        feature_name:
            Name of the feature to add as a NUMERIC column to cmc_features.

        Returns
        -------
        str
            Absolute path to the generated migration stub file.
        """
        # Query live Alembic head -- CRITICAL: do NOT hardcode down_revision
        # (see Phase 38 Pitfall 4 in RESEARCH.md)
        live_head: str | None = None
        try:
            with self._engine.connect() as conn:
                result = conn.execute(
                    text("SELECT version_num FROM public.alembic_version LIMIT 1")
                )
                row = result.fetchone()
                if row:
                    live_head = row[0]
        except Exception:
            # If alembic_version table doesn't exist or query fails,
            # proceed with None (stub will still be valid Python)
            live_head = None

        rev_id = uuid.uuid4().hex[:12]
        slug = _slugify(feature_name)
        column_name = slug  # Use slugified name as column name

        # Represent down_revision cleanly
        down_rev_repr = f'"{live_head}"' if live_head is not None else "None"

        stub_content = f'''\
"""promoted_feature_{slug}

Revision ID: {rev_id}
Revises: {live_head or "None"}
Create Date: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")}

MANUAL STEP: After running alembic upgrade head, wire this feature's
computation into src/ta_lab2/features/ by creating a compute function
and registering it. Suggested location:
  src/ta_lab2/features/promoted_features.py

This migration was auto-generated by FeaturePromoter.promote_feature().
The feature '{feature_name}' passed the Benjamini-Hochberg significance gate
and has been recorded in dim_feature_registry with lifecycle='promoted'.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "{rev_id}"
down_revision: Union[str, Sequence[str], None] = {down_rev_repr}
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add promoted feature column to cmc_features."""
    op.add_column(
        "cmc_features",
        sa.Column("{column_name}", sa.Numeric(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    """Remove promoted feature column from cmc_features."""
    op.drop_column("cmc_features", "{column_name}", schema="public")
'''

        versions_dir = _find_alembic_versions_dir()
        filename = f"{rev_id}_promoted_{slug}.py"
        stub_path = os.path.join(versions_dir, filename)

        # Use encoding='utf-8' to avoid Windows cp1252 decode errors
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(stub_content)

        return stub_path

    def _update_stub_path(self, feature_name: str, stub_path: str) -> None:
        """Update dim_feature_registry.migration_stub_path for the feature."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.dim_feature_registry
                    SET migration_stub_path = :path,
                        updated_at = NOW()
                    WHERE feature_name = :name
                    """
                ),
                {"path": stub_path, "name": feature_name},
            )
