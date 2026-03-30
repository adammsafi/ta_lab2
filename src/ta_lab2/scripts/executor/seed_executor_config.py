#!/usr/bin/env python
"""
Seed dim_executor_config from YAML.

Loads executor strategy configurations from a YAML seed file, resolves
signal_name -> signal_id from dim_signals, and inserts rows into
dim_executor_config using ON CONFLICT DO NOTHING (idempotent).

Usage:
    python -m ta_lab2.scripts.executor.seed_executor_config
    python -m ta_lab2.scripts.executor.seed_executor_config --config path/to/config.yaml
    python -m ta_lab2.scripts.executor.seed_executor_config --seed-watermarks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import resolve_db_url

# Default seed file location relative to project root
# parents[4] = ta_lab2/ (project root), counting from:
#   parents[0] = executor/
#   parents[1] = scripts/
#   parents[2] = ta_lab2/
#   parents[3] = src/
#   parents[4] = ta_lab2/ (project root)
_DEFAULT_SEED_FILE = (
    Path(__file__).resolve().parents[4] / "configs" / "executor_config_seed.yaml"
)

# Columns to INSERT into dim_executor_config (matches DDL from Phase 45-01)
_INSERT_SQL = text(
    """
    INSERT INTO public.dim_executor_config (
        config_name,
        signal_type,
        signal_id,
        is_active,
        exchange,
        environment,
        sizing_mode,
        position_fraction,
        max_position_fraction,
        fill_price_mode,
        slippage_mode,
        slippage_base_bps,
        slippage_noise_sigma,
        volume_impact_factor,
        rejection_rate,
        partial_fill_rate,
        execution_delay_bars,
        cadence_hours
    )
    VALUES (
        :config_name,
        :signal_type,
        :signal_id,
        :is_active,
        :exchange,
        :environment,
        :sizing_mode,
        :position_fraction,
        :max_position_fraction,
        :fill_price_mode,
        :slippage_mode,
        :slippage_base_bps,
        :slippage_noise_sigma,
        :volume_impact_factor,
        :rejection_rate,
        :partial_fill_rate,
        :execution_delay_bars,
        :cadence_hours
    )
    ON CONFLICT (config_name) DO NOTHING
    """
)

_RESOLVE_SIGNAL_SQL = text(
    """
    SELECT signal_id
    FROM public.dim_signals
    WHERE signal_name = :signal_name
    LIMIT 1
    """
)


def _resolve_signal_id(conn, signal_name: str) -> int | None:
    """Look up signal_id from dim_signals by name. Returns None if not found."""
    row = conn.execute(_RESOLVE_SIGNAL_SQL, {"signal_name": signal_name}).fetchone()
    return row.signal_id if row else None


def seed_configs(db_url: str, seed_file: Path) -> dict:
    """
    Load YAML and seed dim_executor_config.

    Returns a summary dict with keys: seeded, already_existed, skipped_no_signal.
    """
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_file}")

    with open(seed_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    configs = data.get("executor_configs", [])
    if not configs:
        print("[WARNING] No executor_configs found in seed file")
        return {"seeded": 0, "already_existed": 0, "skipped_no_signal": 0}

    engine = create_engine(db_url, poolclass=NullPool)
    summary = {"seeded": 0, "already_existed": 0, "skipped_no_signal": 0}

    try:
        with engine.begin() as conn:
            for cfg in configs:
                config_name = cfg["config_name"]
                signal_name = cfg.get("signal_name")

                # Resolve signal_id
                if not signal_name:
                    print(
                        f"[WARNING] Config '{config_name}' has no signal_name -- skipping"
                    )
                    summary["skipped_no_signal"] += 1
                    continue

                signal_id = _resolve_signal_id(conn, signal_name)
                if signal_id is None:
                    print(
                        f"[WARNING] Signal '{signal_name}' not found in dim_signals "
                        f"for config '{config_name}' -- skipping"
                    )
                    summary["skipped_no_signal"] += 1
                    continue

                # Build insert params (skip YAML-only metadata keys)
                params = {
                    "config_name": config_name,
                    "signal_type": cfg["signal_type"],
                    "signal_id": signal_id,
                    "is_active": cfg.get("is_active", True),
                    "exchange": cfg.get("exchange", "paper"),
                    "environment": cfg.get("environment", "sandbox"),
                    "sizing_mode": cfg.get("sizing_mode", "fixed_fraction"),
                    "position_fraction": float(cfg.get("position_fraction", 0.10)),
                    "max_position_fraction": float(
                        cfg.get("max_position_fraction", 0.20)
                    ),
                    "fill_price_mode": cfg.get("fill_price_mode", "next_bar_open"),
                    "slippage_mode": cfg.get("slippage_mode", "lognormal"),
                    "slippage_base_bps": float(cfg.get("slippage_base_bps", 3.0)),
                    "slippage_noise_sigma": float(cfg.get("slippage_noise_sigma", 0.5)),
                    "volume_impact_factor": float(cfg.get("volume_impact_factor", 0.1)),
                    "rejection_rate": float(cfg.get("rejection_rate", 0.0)),
                    "partial_fill_rate": float(cfg.get("partial_fill_rate", 0.0)),
                    "execution_delay_bars": int(cfg.get("execution_delay_bars", 0)),
                    "cadence_hours": float(cfg.get("cadence_hours", 26.0)),
                }

                result = conn.execute(_INSERT_SQL, params)
                rows_affected = result.rowcount

                if rows_affected > 0:
                    print(
                        f"[OK] Seeded config '{config_name}' "
                        f"(signal_id={signal_id}, signal_name='{signal_name}')"
                    )
                    summary["seeded"] += 1
                else:
                    print(
                        f"[SKIP] Config '{config_name}' already exists (ON CONFLICT DO NOTHING)"
                    )
                    summary["already_existed"] += 1

    finally:
        engine.dispose()

    return summary


def seed_watermarks(db_url: str) -> dict:
    """
    Set last_processed_signal_ts = MAX(ts) for active configs with NULL watermark.

    Prevents historical signal replay on first executor run. Only updates
    configs where last_processed_signal_ts IS NULL (safe to re-run on configs
    that already have a watermark).

    Returns a summary dict with keys: watermarks_set, already_set, no_signals.
    """
    from ta_lab2.executor.signal_reader import SIGNAL_TABLE_MAP  # noqa: PLC0415

    engine = create_engine(db_url, poolclass=NullPool)
    summary = {"watermarks_set": 0, "already_set": 0, "no_signals": 0}

    try:
        with engine.begin() as conn:
            # Load all active configs (with and without watermarks)
            rows = conn.execute(
                text(
                    "SELECT config_id, config_name, signal_type, signal_id, "
                    "last_processed_signal_ts "
                    "FROM public.dim_executor_config WHERE is_active = TRUE"
                )
            ).fetchall()

            for row in rows:
                if row.last_processed_signal_ts is not None:
                    print(
                        f"[SKIP] config_id={row.config_id} ({row.config_name}) "
                        f"already has watermark={row.last_processed_signal_ts}"
                    )
                    summary["already_set"] += 1
                    continue

                signal_table = SIGNAL_TABLE_MAP.get(row.signal_type)
                if not signal_table:
                    print(
                        f"[SKIP] Unknown signal_type '{row.signal_type}' "
                        f"for config_id={row.config_id} ({row.config_name})"
                    )
                    summary["no_signals"] += 1
                    continue

                # Get MAX(ts) from signal table for this signal_id
                # signal_table comes from SIGNAL_TABLE_MAP (hardcoded dict),
                # so f-string interpolation is safe from SQL injection.
                max_ts_row = conn.execute(
                    text(
                        f"SELECT MAX(ts) AS max_ts FROM public.{signal_table} "  # noqa: S608
                        "WHERE signal_id = :signal_id"
                    ),
                    {"signal_id": row.signal_id},
                ).fetchone()

                if max_ts_row and max_ts_row.max_ts is not None:
                    conn.execute(
                        text(
                            "UPDATE public.dim_executor_config "
                            "SET last_processed_signal_ts = :max_ts "
                            "WHERE config_id = :config_id"
                        ),
                        {"max_ts": max_ts_row.max_ts, "config_id": row.config_id},
                    )
                    print(
                        f"[OK] Watermark set for config_id={row.config_id} "
                        f"({row.config_name}): {max_ts_row.max_ts}"
                    )
                    summary["watermarks_set"] += 1
                else:
                    print(
                        f"[INFO] No signals yet for config_id={row.config_id} "
                        f"({row.config_name}) in {signal_table} -- watermark not set"
                    )
                    summary["no_signals"] += 1

    finally:
        engine.dispose()

    return summary


def main(argv: list[str] | None = None) -> int:
    """Main entry point for seed executor config CLI."""
    p = argparse.ArgumentParser(
        description=(
            "Seed dim_executor_config from YAML. "
            "Resolves signal_name -> signal_id from dim_signals. "
            "Uses ON CONFLICT DO NOTHING for idempotency."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Seed from default configs/executor_config_seed.yaml
  python -m ta_lab2.scripts.executor.seed_executor_config

  # Seed from custom path
  python -m ta_lab2.scripts.executor.seed_executor_config --config /path/to/seed.yaml

  # Seed configs AND set watermarks to prevent historical replay
  python -m ta_lab2.scripts.executor.seed_executor_config --seed-watermarks

  # Set watermarks only (no YAML seeding)
  python -m ta_lab2.scripts.executor.seed_executor_config --watermarks-only
        """,
    )

    p.add_argument(
        "--config",
        metavar="YAML_PATH",
        default=str(_DEFAULT_SEED_FILE),
        help=f"Path to YAML seed file (default: {_DEFAULT_SEED_FILE})",
    )
    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env via resolve_db_url)",
    )
    p.add_argument(
        "--seed-watermarks",
        action="store_true",
        default=False,
        help=(
            "After seeding configs, set last_processed_signal_ts = MAX(ts) for "
            "active configs with NULL watermark. Prevents historical signal replay "
            "on first executor run."
        ),
    )
    p.add_argument(
        "--watermarks-only",
        action="store_true",
        default=False,
        help="Only run watermark seeding; skip YAML config seeding.",
    )

    args = p.parse_args(argv)

    # Resolve DB URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # --- Config seeding ---
    if not args.watermarks_only:
        seed_file = Path(args.config)
        print(f"Seeding executor configs from: {seed_file}")

        try:
            summary = seed_configs(db_url, seed_file)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] Seed failed: {exc}", file=sys.stderr)
            return 1

        print(
            f"\nSeed complete: {summary['seeded']} seeded, "
            f"{summary['already_existed']} already existed, "
            f"{summary['skipped_no_signal']} skipped (signal not found)"
        )

    # --- Watermark seeding ---
    if args.seed_watermarks or args.watermarks_only:
        print("\nSeeding watermarks (setting last_processed_signal_ts = MAX(ts))...")

        try:
            wm_summary = seed_watermarks(db_url)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] Watermark seed failed: {exc}", file=sys.stderr)
            return 1

        print(
            f"\nWatermark seed complete: {wm_summary['watermarks_set']} set, "
            f"{wm_summary['already_set']} already set, "
            f"{wm_summary['no_signals']} skipped (no signals or unknown type)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
