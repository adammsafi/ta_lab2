"""
refresh_ctf_promoted.py -- CTF Feature Promotion ETL Script (Phase 98 Plan 01).

Materializes top CTF (cross-timeframe) features into the main features table
so that downstream consumers (BL optimizer, signals, ML) can access them via
the standard features query path.

Strategy:
  1. Pre-flight: verify Alembic migration has been run (columns exist).
  2. Discover promoted features: query ic_results for CTF features passing
     PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > ic_threshold.
  3. For each (asset_id, base_tf) that has CTF data:
       a. Load CTF features via load_ctf_features() -- wide-format pivot.
       b. Filter to only promoted column names.
       c. UPDATE features rows (not DELETE+INSERT) to preserve other columns.
  4. Append/overwrite ctf_promoted section in configs/feature_selection.yaml.

Write strategy: UPDATE only -- microstructure_feature.py pattern.
Never DELETE+INSERT (would destroy other feature columns).

Usage:
    python -m ta_lab2.scripts.features.refresh_ctf_promoted --dry-run
    python -m ta_lab2.scripts.features.refresh_ctf_promoted
    python -m ta_lab2.scripts.features.refresh_ctf_promoted --ic-threshold 0.03
    python -m ta_lab2.scripts.features.refresh_ctf_promoted --base-tf 1D
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.features.cross_timeframe import load_ctf_features

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

_DEFAULT_IC_THRESHOLD = 0.02
_DEFAULT_ALIGNMENT_SOURCE = "multi_tf"
_DEFAULT_VENUE_ID = 1

# SQL to discover CTF features passing IC threshold.
_IC_DISCOVERY_SQL = """
    SELECT
        feature,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) AS median_abs_ic,
        COUNT(DISTINCT asset_id) AS n_assets
    FROM public.ic_results
    WHERE horizon = 1
      AND return_type = 'arith'
      AND regime_col = 'all'
      AND regime_label = 'all'
      AND ic IS NOT NULL
      AND (
           feature LIKE '%_slope'
        OR feature LIKE '%_divergence'
        OR feature LIKE '%_agreement'
        OR feature LIKE '%_crossover'
        OR feature LIKE '%_ref_value'
        OR feature LIKE '%_base_value'
      )
    GROUP BY feature
    HAVING PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > :threshold
    ORDER BY median_abs_ic DESC
"""

# SQL to get (asset_id, base_tf) pairs that have CTF data.
_CTF_SCOPE_SQL = """
    SELECT DISTINCT id, base_tf
    FROM public.ctf
    WHERE venue_id = :venue_id
      AND alignment_source = :alignment_source
    ORDER BY id, base_tf
"""

# UPDATE SQL template (column list built dynamically).
_UPDATE_SQL_TEMPLATE = """
    UPDATE public.features
    SET {set_clauses}
    WHERE id = :id
      AND ts = :ts
      AND tf = :tf
      AND venue_id = :venue_id
      AND alignment_source = :alignment_source
"""

_BATCH_SIZE = 5000


# =============================================================================
# Pre-flight check
# =============================================================================


def _preflight_column_check(engine: Engine, expected_cols: list[str]) -> None:
    """Verify that all expected CTF columns exist in features table.

    Raises RuntimeError if any expected columns are missing, instructing
    the user to run the Alembic migration first.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    expected_cols:
        List of CTF feature column names expected in features table.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'features'
                """
            )
        )
        existing = {row[0] for row in result}

    missing = [c for c in expected_cols if c not in existing]
    if missing:
        raise RuntimeError(
            f"Alembic migration not applied. Missing {len(missing)} columns in "
            f"public.features. Run:\n"
            f"  python -m alembic upgrade head\n"
            f"Missing columns (first 10): {missing[:10]}"
        )

    logger.info(
        "Pre-flight check passed: all %d CTF columns exist in features",
        len(expected_cols),
    )


# =============================================================================
# Feature discovery
# =============================================================================


def discover_promoted_features(
    engine: Engine,
    ic_threshold: float = _DEFAULT_IC_THRESHOLD,
) -> list[dict]:
    """Query ic_results to find CTF features passing the IC threshold.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    ic_threshold:
        Minimum cross-asset median absolute IC for feature promotion.

    Returns
    -------
    List of dicts with keys: feature, median_abs_ic, n_assets.
    Sorted by median_abs_ic descending.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(_IC_DISCOVERY_SQL),
            {"threshold": ic_threshold},
        )
        rows = result.fetchall()

    features = [
        {
            "feature": r[0],
            "median_abs_ic": float(r[1]),
            "n_assets": int(r[2]),
        }
        for r in rows
    ]

    logger.info(
        "Discovered %d CTF features passing IC > %.4f threshold",
        len(features),
        ic_threshold,
    )
    return features


def _get_ctf_scope(
    engine: Engine,
    venue_id: int = _DEFAULT_VENUE_ID,
    alignment_source: str = _DEFAULT_ALIGNMENT_SOURCE,
    base_tf_filter: Optional[str] = None,
) -> list[tuple[int, str]]:
    """Get (asset_id, base_tf) pairs that have CTF data.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    venue_id:
        Venue ID to filter (default: 1 = CMC_AGG).
    alignment_source:
        Alignment source filter (default: 'multi_tf').
    base_tf_filter:
        Optional single base_tf to restrict scope (e.g., '1D').

    Returns
    -------
    List of (asset_id, base_tf) tuples.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(_CTF_SCOPE_SQL),
            {"venue_id": venue_id, "alignment_source": alignment_source},
        )
        scope = [(r[0], r[1]) for r in result]

    if base_tf_filter is not None:
        scope = [(aid, btf) for aid, btf in scope if btf == base_tf_filter]

    logger.info("CTF scope: %d (asset_id, base_tf) pairs", len(scope))
    return scope


# =============================================================================
# UPDATE logic
# =============================================================================


def _build_update_sql(ctf_cols: list[str]) -> str:
    """Build parametrized UPDATE SQL for a given list of CTF columns.

    Parameters
    ----------
    ctf_cols:
        List of CTF feature column names to SET.

    Returns
    -------
    SQL string suitable for sqlalchemy text().
    """
    set_clauses = ", ".join(f"{col} = :{col}" for col in ctf_cols)
    return _UPDATE_SQL_TEMPLATE.format(set_clauses=set_clauses)


def _clean_row(row: dict) -> dict:
    """Convert numpy types to Python natives and NaN/NaT to None.

    Parameters
    ----------
    row:
        Dict of {col_name: value} (from DataFrame.to_dict('records')).

    Returns
    -------
    Cleaned dict safe for psycopg2 binding.
    """
    clean: dict = {}
    for k, v in row.items():
        if v is None:
            clean[k] = None
        elif isinstance(v, float) and np.isnan(v):
            clean[k] = None
        elif isinstance(v, pd.Timestamp):
            if pd.isna(v):
                clean[k] = None
            else:
                clean[k] = v.to_pydatetime()
        elif hasattr(v, "item"):
            # numpy scalar
            val = v.item()
            if isinstance(val, float) and np.isnan(val):
                clean[k] = None
            else:
                clean[k] = val
        else:
            clean[k] = v
    return clean


def _update_features_for_scope(
    engine: Engine,
    asset_id: int,
    base_tf: str,
    promoted_cols: list[str],
    venue_id: int = _DEFAULT_VENUE_ID,
    alignment_source: str = _DEFAULT_ALIGNMENT_SOURCE,
) -> int:
    """Load CTF data for one (asset_id, base_tf) and UPDATE features rows.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    asset_id:
        Asset ID to process.
    base_tf:
        Base timeframe string (e.g. '1D').
    promoted_cols:
        List of CTF promoted feature column names to write.
    venue_id:
        Venue ID (default: 1).
    alignment_source:
        Alignment source (default: 'multi_tf').

    Returns
    -------
    Number of rows updated in features.
    """
    # Load CTF features (wide pivot format) -- all available timestamps.
    # Use a broad date range to capture all historical data.
    train_start = pd.Timestamp("2010-01-01", tz="UTC")
    train_end = pd.Timestamp.now(tz="UTC")

    with engine.connect() as conn:
        df_ctf = load_ctf_features(
            conn,
            asset_id=asset_id,
            base_tf=base_tf,
            train_start=train_start,
            train_end=train_end,
            alignment_source=alignment_source,
            venue_id=venue_id,
        )

    if df_ctf.empty:
        logger.debug(
            "No CTF data for asset_id=%d base_tf=%s -- skipping",
            asset_id,
            base_tf,
        )
        return 0

    # Filter to only the promoted columns that exist in the CTF data.
    available_ctf_cols = [c for c in promoted_cols if c in df_ctf.columns]
    if not available_ctf_cols:
        logger.debug(
            "No promoted CTF columns in CTF data for asset_id=%d base_tf=%s -- skipping",
            asset_id,
            base_tf,
        )
        return 0

    # Build write DataFrame: index (ts) + feature cols.
    df_write = df_ctf[available_ctf_cols].reset_index()  # ts becomes a column
    df_write["id"] = asset_id
    df_write["tf"] = base_tf
    df_write["venue_id"] = venue_id
    df_write["alignment_source"] = alignment_source

    # Ensure ts is tz-aware UTC.
    if not isinstance(df_write["ts"].dtype, pd.DatetimeTZDtype):
        df_write["ts"] = pd.to_datetime(df_write["ts"], utc=True)

    # Build and execute batched UPDATE.
    update_sql = text(_build_update_sql(available_ctf_cols))
    pk_cols = ["id", "ts", "tf", "venue_id", "alignment_source"]
    required_cols = pk_cols + available_ctf_cols

    rows = df_write[required_cols].to_dict("records")
    total_updated = 0

    with engine.begin() as conn:
        for i in range(0, len(rows), _BATCH_SIZE):
            batch = rows[i : i + _BATCH_SIZE]
            for row in batch:
                clean = _clean_row(row)
                result = conn.execute(update_sql, clean)
                total_updated += result.rowcount

    logger.info(
        "Promoted %d CTF features for asset_id=%d base_tf=%s: %d rows updated",
        len(available_ctf_cols),
        asset_id,
        base_tf,
        total_updated,
    )
    return total_updated


# =============================================================================
# YAML update
# =============================================================================


def _get_feature_base_tf(feature_name: str) -> str:
    """Infer base_tf from feature name by matching ref_tf suffix.

    CTF column naming: {indicator_name}_{ref_tf_lower}_{composite}
    Example: rsi_14_7d_slope -> ref_tf='7D' (not base_tf, but the ref timeframe).
    Base_tf is stored at the scope level (all promoted features exist for
    all valid base_tf values where CTF was computed).

    Returns a placeholder since base_tf is scope-level, not feature-level.
    """
    return "1D"  # Primary base_tf; features exist for all base_tfs


def _update_feature_selection_yaml(
    yaml_path: Path,
    promoted_features: list[dict],
    ic_threshold: float,
) -> None:
    """Append/overwrite ctf_promoted section in feature_selection.yaml.

    Reads the existing YAML (preserving all other sections), then adds/overwrites
    a top-level 'ctf_promoted' section with promoted feature metadata.

    Parameters
    ----------
    yaml_path:
        Path to configs/feature_selection.yaml.
    promoted_features:
        List of dicts from discover_promoted_features() with keys:
        feature, median_abs_ic, n_assets.
    ic_threshold:
        IC threshold used for promotion (for documentation).
    """
    try:
        import yaml
    except ImportError:
        logger.error("PyYAML not installed -- cannot update feature_selection.yaml")
        return

    # Read existing YAML content as text to preserve formatting of other sections.
    existing_text = yaml_path.read_text(encoding="utf-8") if yaml_path.exists() else ""

    # Parse existing to detect if ctf_promoted section already exists.
    existing_data = yaml.safe_load(existing_text) if existing_text else {}
    if existing_data is None:
        existing_data = {}

    # Build ctf_promoted section.
    ctf_promoted_section = {
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ic_threshold": ic_threshold,
        "ic_aggregation": "cross_asset_median",
        "source": "ic_results",
        "n_features": len(promoted_features),
        "features": [
            {
                "name": f["feature"],
                "median_abs_ic": round(f["median_abs_ic"], 6),
                "n_assets": f["n_assets"],
                "base_tf": _get_feature_base_tf(f["feature"]),
                "source_ctf_config": "ctf_config.yaml",
            }
            for f in promoted_features
        ],
    }

    # Update the dict.
    existing_data["ctf_promoted"] = ctf_promoted_section

    # Write back as YAML.
    output_text = yaml.dump(
        existing_data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=True,
        indent=2,
    )
    yaml_path.write_text(output_text, encoding="utf-8")

    logger.info(
        "Updated feature_selection.yaml: added ctf_promoted section with %d features",
        len(promoted_features),
    )


# =============================================================================
# Main execution
# =============================================================================


def run_refresh(
    engine: Engine,
    ic_threshold: float = _DEFAULT_IC_THRESHOLD,
    base_tf_filter: Optional[str] = None,
    dry_run: bool = False,
    yaml_path: Optional[Path] = None,
) -> dict:
    """Execute the CTF feature promotion refresh.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    ic_threshold:
        Minimum cross-asset median absolute IC for promotion.
    base_tf_filter:
        Optional base_tf to restrict processing (e.g., '1D').
    dry_run:
        If True, discover and print promoted features without writing.
    yaml_path:
        Path to configs/feature_selection.yaml. Defaults to project root.

    Returns
    -------
    Dict with summary: features_promoted, assets_processed, rows_updated.
    """
    t0 = time.time()

    # Discover promoted features.
    promoted = discover_promoted_features(engine, ic_threshold=ic_threshold)
    promoted_col_names = [f["feature"] for f in promoted]

    if not promoted:
        logger.warning(
            "No CTF features passed IC > %.4f threshold. Nothing to promote.",
            ic_threshold,
        )
        return {"features_promoted": 0, "assets_processed": 0, "rows_updated": 0}

    if dry_run:
        print(
            f"\nDRY RUN: {len(promoted)} CTF features would be promoted "
            f"(IC threshold = {ic_threshold}):\n"
        )
        for f in promoted:
            print(
                f"  {f['feature']:<50} median_abs_ic={f['median_abs_ic']:.4f}  "
                f"n_assets={f['n_assets']}"
            )
        print(f"\nTotal: {len(promoted)} features")
        return {
            "features_promoted": len(promoted),
            "assets_processed": 0,
            "rows_updated": 0,
        }

    # Pre-flight: verify all expected columns exist.
    _preflight_column_check(engine, promoted_col_names)

    # Get CTF scope: (asset_id, base_tf) pairs.
    scope = _get_ctf_scope(
        engine,
        venue_id=_DEFAULT_VENUE_ID,
        alignment_source=_DEFAULT_ALIGNMENT_SOURCE,
        base_tf_filter=base_tf_filter,
    )

    if not scope:
        logger.warning("No CTF data found in public.ctf. Nothing to write.")
        return {
            "features_promoted": len(promoted),
            "assets_processed": 0,
            "rows_updated": 0,
        }

    # Process each (asset_id, base_tf) pair.
    total_rows_updated = 0
    processed_assets: set[int] = set()

    for i, (asset_id, base_tf) in enumerate(scope, 1):
        logger.info(
            "Processing %d/%d: asset_id=%d base_tf=%s",
            i,
            len(scope),
            asset_id,
            base_tf,
        )
        rows = _update_features_for_scope(
            engine,
            asset_id=asset_id,
            base_tf=base_tf,
            promoted_cols=promoted_col_names,
            venue_id=_DEFAULT_VENUE_ID,
            alignment_source=_DEFAULT_ALIGNMENT_SOURCE,
        )
        total_rows_updated += rows
        processed_assets.add(asset_id)

    elapsed = time.time() - t0

    # Update feature_selection.yaml.
    if yaml_path is None:
        # Resolve project root: go up from this file to find pyproject.toml.
        p = Path(__file__).resolve()
        for parent in [p, *p.parents]:
            if (parent / "pyproject.toml").exists():
                yaml_path = parent / "configs" / "feature_selection.yaml"
                break
        if yaml_path is None:
            yaml_path = Path("configs/feature_selection.yaml")

    _update_feature_selection_yaml(yaml_path, promoted, ic_threshold)

    logger.info(
        "CTF feature promotion complete: %d features, %d assets, "
        "%d rows updated in %.1fs",
        len(promoted),
        len(processed_assets),
        total_rows_updated,
        elapsed,
    )

    return {
        "features_promoted": len(promoted),
        "assets_processed": len(processed_assets),
        "rows_updated": total_rows_updated,
    }


# =============================================================================
# CLI
# =============================================================================


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Promote CTF (cross-timeframe) features to features table via UPDATE. "
            "Reads ic_results to discover features passing IC > threshold, "
            "then writes values from public.ctf to public.features."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run: see what features would be promoted
  python -m ta_lab2.scripts.features.refresh_ctf_promoted --dry-run

  # Full refresh (all base_tfs)
  python -m ta_lab2.scripts.features.refresh_ctf_promoted

  # Restrict to 1D base_tf only
  python -m ta_lab2.scripts.features.refresh_ctf_promoted --base-tf 1D

  # Use stricter IC threshold
  python -m ta_lab2.scripts.features.refresh_ctf_promoted --ic-threshold 0.03
""",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show features that would be promoted without writing",
    )
    parser.add_argument(
        "--ic-threshold",
        type=float,
        default=_DEFAULT_IC_THRESHOLD,
        help=f"IC threshold for promotion (default: {_DEFAULT_IC_THRESHOLD})",
    )
    parser.add_argument(
        "--base-tf",
        type=str,
        default=None,
        help="Specific base_tf to process (default: all)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not TARGET_DB_URL:
        logger.error("TARGET_DB_URL not set")
        return 1

    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    try:
        summary = run_refresh(
            engine,
            ic_threshold=args.ic_threshold,
            base_tf_filter=args.base_tf,
            dry_run=args.dry_run,
        )

        if not args.dry_run:
            print(
                f"\nCTF feature promotion complete:\n"
                f"  Features promoted:  {summary['features_promoted']}\n"
                f"  Assets processed:   {summary['assets_processed']}\n"
                f"  Rows updated:       {summary['rows_updated']}"
            )
        return 0

    except RuntimeError as exc:
        logger.error("Pre-flight check failed: %s", exc)
        return 1
    except Exception as exc:
        logger.error("CTF feature promotion failed: %s", exc, exc_info=True)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
