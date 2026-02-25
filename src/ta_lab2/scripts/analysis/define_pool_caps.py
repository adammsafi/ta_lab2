"""
define_pool_caps.py
~~~~~~~~~~~~~~~~~~~
CLI for pool cap definition and dim_risk_limits seeding.

Derives pool-level loss caps from Phase 42 bake-off MaxDD data and seeds the
dim_risk_limits table with Conservative / Core / Opportunistic / Aggregate pool rows.
Also generates POOL_CAPS.md documenting derivation and V1 enforcement rules.

Closes LOSS-03 (pool-level caps).

Usage
-----
    # Report only (no DB write)
    python -m ta_lab2.scripts.analysis.define_pool_caps

    # Write pool rows to dim_risk_limits
    python -m ta_lab2.scripts.analysis.define_pool_caps --seed-db

    # Dry-run (print config and exit)
    python -m ta_lab2.scripts.analysis.define_pool_caps --dry-run

    # Custom sizing fraction and safety buffer
    python -m ta_lab2.scripts.analysis.define_pool_caps --sizing-fraction 0.10 --safety-buffer 2.0

    # Custom output directory
    python -m ta_lab2.scripts.analysis.define_pool_caps --output-dir reports/loss_limits/
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # ta_lab2/

# ---------------------------------------------------------------------------
# Pool definitions (from Phase 48 CONTEXT.md and Vision Draft)
# ---------------------------------------------------------------------------
POOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "conservative": {
        "description": "Capital preservation; lowest risk exposure",
        "dd_target_vision": 0.12,  # Vision Draft: DD <= 10-12%
        "max_position_pct": 0.10,
        "max_portfolio_pct": 0.40,
    },
    "core": {
        "description": "Balanced risk/return; primary allocation",
        "dd_target_vision": 0.20,  # Vision Draft: DD <= 20%
        "max_position_pct": 0.20,
        "max_portfolio_pct": 0.60,
    },
    "opportunistic": {
        "description": "Higher risk tolerance; tactical allocation",
        "dd_target_vision": 0.40,  # No Vision Draft target; set at 2x Core
        "max_position_pct": 0.40,
        "max_portfolio_pct": 0.80,
    },
    "aggregate": {
        "description": "V1 single-portfolio enforcement cap",
        "dd_target_vision": 0.15,  # 15% portfolio DD circuit breaker
        "max_position_pct": 0.15,
        "max_portfolio_pct": 0.80,
    },
}

# ---------------------------------------------------------------------------
# Empirical fallback values from Phase 42 bake-off (STRATEGY_SELECTION.md)
# These values are used when strategy_bakeoff_results table is unavailable.
# ---------------------------------------------------------------------------
_EMPIRICAL_BAKEOFF: List[Dict[str, Any]] = [
    {
        "strategy_name": "ema_trend_17_77",
        "max_drawdown_mean": -0.386,  # -38.6%
        "max_drawdown_worst": -0.750,  # -75.0%
    },
    {
        "strategy_name": "ema_trend_21_50",
        "max_drawdown_mean": -0.387,  # -38.7%
        "max_drawdown_worst": -0.701,  # -70.1%
    },
]

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_engine(db_url: Optional[str] = None):
    """Create SQLAlchemy engine with NullPool."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.scripts.refresh_utils import resolve_db_url

    url = db_url or resolve_db_url()
    return create_engine(url, poolclass=NullPool)


def _load_bakeoff_from_db(engine) -> List[Dict[str, Any]]:
    """
    Load MaxDD data from strategy_bakeoff_results table.
    Returns empty list if table does not exist or has no rows for the target strategies.
    """
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT strategy_name, max_drawdown_mean, max_drawdown_worst
                    FROM public.strategy_bakeoff_results
                    WHERE strategy_name IN ('ema_trend_17_77', 'ema_trend_21_50')
                    """
                )
            )
            rows = result.fetchall()
            if not rows:
                return []
            return [
                {
                    "strategy_name": row[0],
                    "max_drawdown_mean": float(row[1]),
                    "max_drawdown_worst": float(row[2]),
                }
                for row in rows
            ]
    except Exception as exc:
        logger.warning("Could not load strategy_bakeoff_results from DB: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Cap derivation logic
# ---------------------------------------------------------------------------


def derive_caps(
    sizing_fraction: float = 0.10,
    safety_buffer: float = 2.0,
    bakeoff_data: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, float]]:
    """
    Derive pool daily_loss_pct_threshold values from bake-off MaxDD data.

    Parameters
    ----------
    sizing_fraction : float
        V1 position sizing fraction (0.10 = 10%).
    safety_buffer : float
        Safety multiplier applied when computing pool caps.
    bakeoff_data : list of dicts, optional
        MaxDD data from strategy_bakeoff_results. If None, uses empirical fallback.

    Returns
    -------
    derivation : dict
        Full derivation chain for reporting.
    pool_daily_loss : dict
        Mapping pool_name -> daily_loss_pct_threshold (fraction, e.g. 0.077).
    """
    source_data = bakeoff_data if bakeoff_data else _EMPIRICAL_BAKEOFF
    data_source = "DB" if bakeoff_data else "empirical_fallback"

    # Compute average MaxDD mean across selected strategies
    dd_means = [abs(row["max_drawdown_mean"]) for row in source_data]
    avg_dd_mean = sum(dd_means) / len(dd_means) if dd_means else 0.386

    # Expected portfolio DD at V1 sizing
    expected_dd = avg_dd_mean * sizing_fraction

    # Base pool loss (expected_dd * safety_buffer)
    base_loss = expected_dd * safety_buffer

    logger.info("Bake-off data source: %s", data_source)
    logger.info("Avg MaxDD mean across selected strategies: %.1f%%", avg_dd_mean * 100)
    logger.info(
        "Expected portfolio DD at %.0f%% sizing: %.2f%%",
        sizing_fraction * 100,
        expected_dd * 100,
    )
    logger.info(
        "Base pool loss (expected_dd * %.1fx safety buffer): %.2f%%",
        safety_buffer,
        base_loss * 100,
    )

    # Pool-specific thresholds
    conservative_loss = min(
        base_loss, POOL_DEFINITIONS["conservative"]["dd_target_vision"]
    )
    core_loss = min(base_loss * 2, POOL_DEFINITIONS["core"]["dd_target_vision"])
    opportunistic_loss = min(
        base_loss * 3, POOL_DEFINITIONS["opportunistic"]["dd_target_vision"]
    )
    aggregate_loss = 0.15  # Hardcoded V1 circuit breaker from Phase 42 decision

    logger.info(
        "Conservative daily loss cap: %.2f%% (min of base=%.2f%%, vision=%.0f%%)",
        conservative_loss * 100,
        base_loss * 100,
        POOL_DEFINITIONS["conservative"]["dd_target_vision"] * 100,
    )
    logger.info(
        "Core daily loss cap: %.2f%% (min of base*2=%.2f%%, vision=%.0f%%)",
        core_loss * 100,
        base_loss * 2 * 100,
        POOL_DEFINITIONS["core"]["dd_target_vision"] * 100,
    )
    logger.info(
        "Opportunistic daily loss cap: %.2f%% (min of base*3=%.2f%%, vision=%.0f%%)",
        opportunistic_loss * 100,
        base_loss * 3 * 100,
        POOL_DEFINITIONS["opportunistic"]["dd_target_vision"] * 100,
    )
    logger.info(
        "Aggregate daily loss cap: %.2f%% (hardcoded V1 circuit breaker)",
        aggregate_loss * 100,
    )

    derivation = {
        "data_source": data_source,
        "source_data": source_data,
        "avg_dd_mean_pct": avg_dd_mean * 100,
        "sizing_fraction": sizing_fraction,
        "expected_dd_pct": expected_dd * 100,
        "safety_buffer": safety_buffer,
        "base_loss_pct": base_loss * 100,
    }

    pool_daily_loss = {
        "conservative": conservative_loss,
        "core": core_loss,
        "opportunistic": opportunistic_loss,
        "aggregate": aggregate_loss,
    }

    return derivation, pool_daily_loss


# ---------------------------------------------------------------------------
# DB seeding
# ---------------------------------------------------------------------------


def seed_dim_risk_limits(
    engine, pool_daily_loss: Dict[str, float]
) -> List[Dict[str, Any]]:
    """
    Seed dim_risk_limits with pool rows.

    Uses SELECT-before-INSERT/UPDATE pattern since pool_name has no UNIQUE constraint.

    Returns list of seeded rows with action taken ('inserted' or 'updated').
    """
    from sqlalchemy import text

    seeded = []

    with engine.begin() as conn:
        for pool_name, daily_loss in pool_daily_loss.items():
            pool_def = POOL_DEFINITIONS[pool_name]
            max_pos = pool_def["max_position_pct"]
            max_port = pool_def["max_portfolio_pct"]

            # SELECT-before-INSERT check (no UNIQUE constraint on pool_name)
            result = conn.execute(
                text(
                    "SELECT limit_id FROM public.dim_risk_limits WHERE pool_name = :pool_name"
                ),
                {"pool_name": pool_name},
            )
            existing = result.fetchone()

            if existing:
                limit_id = existing[0]
                conn.execute(
                    text(
                        """
                        UPDATE public.dim_risk_limits
                        SET daily_loss_pct_threshold = :daily_loss,
                            max_position_pct = :max_pos,
                            max_portfolio_pct = :max_port
                        WHERE limit_id = :limit_id
                        """
                    ),
                    {
                        "daily_loss": daily_loss,
                        "max_pos": max_pos,
                        "max_port": max_port,
                        "limit_id": limit_id,
                    },
                )
                action = "updated"
                logger.info(
                    "UPDATED dim_risk_limits: pool_name=%s, limit_id=%s, "
                    "daily_loss=%.2f%%, max_pos=%.0f%%, max_port=%.0f%%",
                    pool_name,
                    limit_id,
                    daily_loss * 100,
                    max_pos * 100,
                    max_port * 100,
                )
            else:
                result = conn.execute(
                    text(
                        """
                        INSERT INTO public.dim_risk_limits
                            (pool_name, daily_loss_pct_threshold, max_position_pct, max_portfolio_pct)
                        VALUES (:pool_name, :daily_loss, :max_pos, :max_port)
                        RETURNING limit_id
                        """
                    ),
                    {
                        "pool_name": pool_name,
                        "daily_loss": daily_loss,
                        "max_pos": max_pos,
                        "max_port": max_port,
                    },
                )
                inserted_id = result.fetchone()[0]
                action = "inserted"
                logger.info(
                    "INSERTED dim_risk_limits: pool_name=%s, limit_id=%s, "
                    "daily_loss=%.2f%%, max_pos=%.0f%%, max_port=%.0f%%",
                    pool_name,
                    inserted_id,
                    daily_loss * 100,
                    max_pos * 100,
                    max_port * 100,
                )

            seeded.append(
                {
                    "pool_name": pool_name,
                    "action": action,
                    "daily_loss_pct_threshold": daily_loss,
                    "max_position_pct": max_pos,
                    "max_portfolio_pct": max_port,
                }
            )

    return seeded


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_pool_caps_md(
    output_dir: Path,
    derivation: Dict[str, Any],
    pool_daily_loss: Dict[str, float],
    seeded: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """
    Write POOL_CAPS.md to output_dir.

    Returns path to written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "POOL_CAPS.md"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build strategy table rows from source_data
    strategy_rows = "\n".join(
        f"| {row['strategy_name']} | {row['max_drawdown_mean'] * 100:.1f}% | "
        f"{row['max_drawdown_worst'] * 100:.1f}% |"
        for row in derivation["source_data"]
    )

    # Build pool definitions table
    pool_rows = ""
    enforced_map = {
        "conservative": "No (defined only)",
        "core": "No (defined only)",
        "opportunistic": "No (defined only)",
        "aggregate": "YES",
    }
    for pool_name, pool_def in POOL_DEFINITIONS.items():
        dl = pool_daily_loss[pool_name] * 100
        mp = pool_def["max_position_pct"] * 100
        mport = pool_def["max_portfolio_pct"] * 100
        dd_vision = pool_def["dd_target_vision"] * 100
        enforced = enforced_map[pool_name]
        pool_rows += (
            f"| {pool_name.capitalize()} | {dl:.2f}% | {mp:.0f}% | {mport:.0f}% | "
            f"<= {dd_vision:.0f}% | {enforced} |\n"
        )

    # DB seeding note
    if seeded is not None:
        db_note = "\n## DB Seeding\n\nPool rows seeded to `dim_risk_limits`:\n\n"
        db_note += "| Pool | Action | daily_loss_pct_threshold | max_position_pct | max_portfolio_pct |\n"
        db_note += "|------|--------|--------------------------|------------------|-------------------|\n"
        for row in seeded:
            db_note += (
                f"| {row['pool_name']} | {row['action']} | "
                f"{row['daily_loss_pct_threshold'] * 100:.2f}% | "
                f"{row['max_position_pct'] * 100:.0f}% | "
                f"{row['max_portfolio_pct'] * 100:.0f}% |\n"
            )
    else:
        db_note = "\n## DB Seeding\n\nNot run. Use `--seed-db` to write pool rows to `dim_risk_limits`.\n"

    content = f"""# Pool-Level Cap Definitions

Generated: {timestamp}
Data source: {derivation["data_source"]}

## Derivation

### Input Data (Phase 42 Bake-Off)

| Strategy | MaxDD Mean | MaxDD Worst |
|----------|------------|-------------|
{strategy_rows}

### V1 Sizing Impact

Position sizing fraction: {derivation["sizing_fraction"] * 100:.0f}%
Expected portfolio drawdown at V1 sizing: {derivation["expected_dd_pct"]:.2f}%
Safety buffer: {derivation["safety_buffer"]:.1f}x
Base pool loss (expected_dd * safety_buffer): {derivation["base_loss_pct"]:.2f}%

### Pool Definitions

| Pool | Daily Loss Cap | Max Position % | Max Portfolio % | DD Target (Vision) | Enforced in V1 |
|------|---------------|----------------|-----------------|--------------------|--------------------|
{pool_rows}
## V1 Enforcement

During V1 paper trading (single portfolio):
- ONLY the aggregate row is actively enforced by Phase 46 RiskEngine
- Pool-specific rows exist for documentation and future multi-pool deployment
- RiskEngine MUST query: `WHERE pool_name = 'aggregate' OR (pool_name IS NULL AND asset_id IS NULL AND strategy_id IS NULL)`
- Pool-specific rows (conservative/core/opportunistic) are NOT read by RiskEngine during V1
{db_note}
## Future Multi-Pool

When transitioning to multi-pool:
1. Assign strategies to pools in dim_risk_limits (new rows with asset_id + pool_name)
2. Update RiskEngine to check pool-specific rows for each strategy
3. Pool allocation/rebalancing logic is Phase 52+ scope
"""

    report_path.write_text(content, encoding="utf-8")
    logger.info("POOL_CAPS.md written to %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="define_pool_caps",
        description=(
            "Derive pool-level loss caps from Phase 42 bake-off MaxDD data "
            "and optionally seed dim_risk_limits. Generates POOL_CAPS.md policy document."
        ),
    )
    parser.add_argument(
        "--seed-db",
        action="store_true",
        dest="seed_db",
        help="Write pool cap rows to dim_risk_limits (default: report only).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/loss_limits/",
        dest="output_dir",
        help="Report output directory (default: reports/loss_limits/).",
    )
    parser.add_argument(
        "--sizing-fraction",
        type=float,
        default=0.10,
        dest="sizing_fraction",
        help="V1 position sizing fraction (default: 0.10 = 10%%).",
    )
    parser.add_argument(
        "--safety-buffer",
        type=float,
        default=2.0,
        dest="safety_buffer",
        help="Safety multiplier for caps (default: 2.0).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        dest="db_url",
        help="Database URL (overrides db_config.env and environment variables).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print configuration and exit without DB/file operations.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.dry_run:
        print("=== define_pool_caps DRY RUN ===")
        print(
            f"  sizing_fraction : {args.sizing_fraction:.2f} ({args.sizing_fraction * 100:.0f}%)"
        )
        print(f"  safety_buffer   : {args.safety_buffer:.1f}x")
        print(f"  output_dir      : {args.output_dir}")
        print(f"  seed_db         : {args.seed_db}")
        print()
        print("Pool definitions:")
        for pool_name, pool_def in POOL_DEFINITIONS.items():
            print(
                f"  {pool_name:15s}  dd_target={pool_def['dd_target_vision'] * 100:.0f}%  "
                f"max_pos={pool_def['max_position_pct'] * 100:.0f}%  "
                f"max_port={pool_def['max_portfolio_pct'] * 100:.0f}%"
            )
        print()
        print("Empirical bake-off fallback:")
        for row in _EMPIRICAL_BAKEOFF:
            print(
                f"  {row['strategy_name']:20s}  "
                f"MaxDD mean={row['max_drawdown_mean'] * 100:.1f}%  "
                f"MaxDD worst={row['max_drawdown_worst'] * 100:.1f}%"
            )
        return 0

    # Resolve output directory relative to project root
    output_dir = (
        Path(args.output_dir)
        if Path(args.output_dir).is_absolute()
        else _PROJECT_ROOT / args.output_dir
    )

    # Try to load bake-off data from DB; fall back to empirical
    bakeoff_data: Optional[List[Dict[str, Any]]] = None
    engine = None
    try:
        engine = _get_engine(args.db_url)
        db_rows = _load_bakeoff_from_db(engine)
        if db_rows:
            bakeoff_data = db_rows
            logger.info("Loaded %d bake-off rows from DB", len(db_rows))
        else:
            logger.warning(
                "strategy_bakeoff_results not available or empty for target strategies. "
                "Using empirical fallback values from STRATEGY_SELECTION.md."
            )
    except Exception as exc:
        logger.warning(
            "Could not connect to DB for bake-off data: %s. "
            "Using empirical fallback values.",
            exc,
        )

    # Derive caps
    derivation, pool_daily_loss = derive_caps(
        sizing_fraction=args.sizing_fraction,
        safety_buffer=args.safety_buffer,
        bakeoff_data=bakeoff_data,
    )

    # Seed DB if requested
    seeded: Optional[List[Dict[str, Any]]] = None
    if args.seed_db:
        if engine is None:
            try:
                engine = _get_engine(args.db_url)
            except Exception as exc:
                logger.error("Cannot seed DB without connection: %s", exc)
                return 1
        try:
            seeded = seed_dim_risk_limits(engine, pool_daily_loss)
            print(f"\nSeeded {len(seeded)} pool rows to dim_risk_limits:")
            for row in seeded:
                print(
                    f"  [{row['action'].upper():8s}] pool_name={row['pool_name']:15s}  "
                    f"daily_loss={row['daily_loss_pct_threshold'] * 100:.2f}%  "
                    f"max_pos={row['max_position_pct'] * 100:.0f}%  "
                    f"max_port={row['max_portfolio_pct'] * 100:.0f}%"
                )
        except Exception as exc:
            logger.error("Failed to seed dim_risk_limits: %s", exc)
            return 1

    # Generate report
    report_path = generate_pool_caps_md(output_dir, derivation, pool_daily_loss, seeded)
    print(f"\nPOOL_CAPS.md written to: {report_path}")

    # Print summary
    print("\n=== Pool Cap Summary ===")
    print(f"  Avg MaxDD mean (bake-off): {derivation['avg_dd_mean_pct']:.1f}%")
    print(
        f"  Expected portfolio DD at {derivation['sizing_fraction'] * 100:.0f}% sizing: "
        f"{derivation['expected_dd_pct']:.2f}%"
    )
    print(f"  Safety buffer: {derivation['safety_buffer']:.1f}x")
    print()
    for pool_name, daily_loss in pool_daily_loss.items():
        enforced = " [ENFORCED V1]" if pool_name == "aggregate" else " [defined only]"
        print(
            f"  {pool_name:15s}  daily_loss={daily_loss * 100:.2f}%"
            f"  max_pos={POOL_DEFINITIONS[pool_name]['max_position_pct'] * 100:.0f}%"
            f"  max_port={POOL_DEFINITIONS[pool_name]['max_portfolio_pct'] * 100:.0f}%"
            f"{enforced}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
