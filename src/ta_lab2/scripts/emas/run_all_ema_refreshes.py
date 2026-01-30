# -*- coding: utf-8 -*-
"""
Created on Sat Dec 20 15:53:08 2025

@author: asafi
"""

from __future__ import annotations

"""
run_all_ema_refreshes.py

Run your EMA refresh runners sequentially (in-process) using runpy so:
- you can keep one Python session (Spyder-friendly),
- each script still sees a normal CLI argv,
- failures stop the chain (unless you pass --continue-on-error).

Targets (in order):
1) refresh_cmc_ema_multi_tf_from_bars.py
2) refresh_cmc_ema_multi_tf_cal_from_bars.py
3) refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py
4) refresh_cmc_ema_multi_tf_v2.py

These are the files you uploaded:
- refresh_cmc_ema_multi_tf_from_bars.py :contentReference[oaicite:0]{index=0}
- refresh_cmc_ema_multi_tf_cal_from_bars.py :contentReference[oaicite:1]{index=1}
- refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py :contentReference[oaicite:2]{index=2}
- refresh_cmc_ema_multi_tf_v2.py :contentReference[oaicite:3]{index=3}

Usage examples:

# simplest:
python run_all_ema_refreshes.py

# override ids + range:
python run_all_ema_refreshes.py --ids 1,52 --start 2024-01-01 --end 2025-12-01

# use periods from LUT everywhere that supports it:
python run_all_ema_refreshes.py --periods lut

# run cal + cal_anchor both schemes:
python run_all_ema_refreshes.py --cal-scheme both --anchor-scheme both

Notes:
- Requires TARGET_DB_URL to be set (your runners expect it).
- The runners differ slightly in flags; this wrapper maps your global flags
  onto the appropriate per-script argv.
"""

import argparse
import os
import runpy
import shlex
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ta_lab2.scripts.emas.logging_config import setup_logging, add_logging_args


# ---- Update these if you move the files somewhere else ----
SCRIPTS = {
    "multi_tf": r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\refresh_cmc_ema_multi_tf_from_bars.py",
    "cal": r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\refresh_cmc_ema_multi_tf_cal_from_bars.py",
    "cal_anchor": r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py",
    "v2": r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\refresh_cmc_ema_multi_tf_v2.py",
}



@dataclass
class Step:
    name: str
    path: str
    argv: List[str]


def _require_env() -> None:
    """
    Check if database URL is available from db_config.env or environment variables.

    Note: resolve_db_url() prioritizes db_config.env file, so environment variables
    are no longer required. This function now only validates that at least one source exists.
    """
    from pathlib import Path

    # Check for db_config.env file first
    current = Path.cwd()
    for _ in range(5):
        env_file = current / "db_config.env"
        if env_file.exists():
            return  # File exists, we're good
        current = current.parent

    # Fall back to environment variables
    if os.getenv("TARGET_DB_URL") or os.getenv("MARKETDATA_DB_URL"):
        return  # Environment variable set, we're good

    raise RuntimeError(
        "No database URL found. Either:\n"
        "  1. Create db_config.env file with TARGET_DB_URL=postgresql://...\n"
        "  2. Set TARGET_DB_URL or MARKETDATA_DB_URL environment variable"
    )


def run_validation(args, logger) -> bool:
    """Run rowcount validation on unified EMA table."""
    from ta_lab2.scripts.emas.validate_ema_rowcounts import validate_rowcounts, summarize_validation
    from ta_lab2.notifications.telegram import send_validation_alert, is_configured
    from ta_lab2.config import TARGET_DB_URL
    from sqlalchemy import create_engine

    logger.info("Running post-refresh rowcount validation...")

    if not TARGET_DB_URL:
        logger.error("TARGET_DB_URL not set - cannot run validation")
        return False

    db_url = TARGET_DB_URL
    engine = create_engine(db_url)

    # Use same date range as refresh
    start = args.start
    end = args.end or datetime.now().strftime("%Y-%m-%d")

    # Parse periods for validation
    if args.periods == "lut":
        # For LUT, use common periods for validation
        periods = [9, 10, 20, 50]
    else:
        periods = [int(x.strip()) for x in args.periods.split(",")]

    # Validate unified table
    try:
        df = validate_rowcounts(
            engine=engine,
            table="cmc_ema_multi_tf_u",
            schema="public",
            ids=None,  # all
            tfs=None,  # all canonical
            periods=periods,
            start_date=start,
            end_date=end,
            db_url=db_url
        )
    except Exception as e:
        logger.error(f"Validation failed with error: {e}", exc_info=True)
        return False

    summary = summarize_validation(df)

    if summary["gaps"] > 0 or summary["duplicates"] > 0:
        logger.warning(f"Validation found issues: {summary['gaps']} gaps, {summary['duplicates']} duplicates")

        if args.alert_on_validation_error and is_configured():
            send_validation_alert(summary)
            logger.info("Telegram alert sent")
        elif args.alert_on_validation_error:
            logger.warning("Telegram not configured - skipping alert")

        return False

    logger.info(f"Validation passed: {summary['ok']}/{summary['total']} checks OK")
    return True


def _run_script(step: Step, logger) -> None:
    logger.info(f"Starting step: {step.name}")
    logger.debug(f"Script path: {step.path}")
    logger.debug(f"Arguments: {' '.join(shlex.quote(a) for a in step.argv)}")

    old_argv = sys.argv[:]
    t0 = time.time()
    try:
        sys.argv = [step.path, *step.argv]
        # Run as if "python <file>.py <args...>"
        runpy.run_path(step.path, run_name="__main__")
    except SystemExit as e:
        # Many scripts call SystemExit; treat nonzero as error.
        code = int(e.code) if e.code is not None else 0
        if code != 0:
            raise RuntimeError(f"Script exited with code {code}") from e
    finally:
        sys.argv = old_argv

    dt = time.time() - t0
    logger.info(f"Completed step: {step.name} ({dt:.1f}s)")


def build_steps(args: argparse.Namespace) -> List[Step]:
    # Global values
    ids = args.ids
    start = args.start
    end = args.end
    periods = args.periods

    steps: List[Step] = []

    # 1) cmc_ema_multi_tf (tf_day)
    # refresh_cmc_ema_multi_tf_from_bars.py supports: --ids, --start, --end, --periods (incl lut), --tfs, --out-table, --bars-table, --no-update
    steps.append(
        Step(
            name="multi_tf",
            path=SCRIPTS["multi_tf"],
            argv=[
                "--ids",
                ids,
                "--start",
                start,
                *(["--end", end] if end else []),
                "--periods",
                periods,
                *(["--no-update"] if args.no_update else []),
            ],
        )
    )

    # 2) cmc_ema_multi_tf_cal_{us|iso}
    # refresh_cmc_ema_multi_tf_cal_from_bars.py supports: --ids, --periods (incl lut), --scheme us|iso|both, --start, --end, --full-refresh
    cal_scheme = args.cal_scheme.lower()
    cal_argv = [
        "--ids",
        ids,
        "--scheme",
        cal_scheme,
        *(["--start", start] if start else []),  # script accepts None; we pass start for consistency
        *(["--end", end] if end else []),
        "--periods",
        periods,
        *(["--full-refresh"] if args.full_refresh else []),
    ]
    steps.append(Step(name="cal", path=SCRIPTS["cal"], argv=cal_argv))

    # 3) cmc_ema_multi_tf_cal_anchor_{us|iso}
    # refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py supports: --ids, --scheme us|iso|both, --start, --end, --periods (incl lut), --no-update
    anchor_scheme = args.anchor_scheme.lower()
    steps.append(
        Step(
            name="cal_anchor",
            path=SCRIPTS["cal_anchor"],
            argv=[
                "--ids",
                ids,
                "--scheme",
                anchor_scheme,
                "--start",
                start,
                *(["--end", end] if end else []),
                "--periods",
                periods,
                *(["--no-update"] if args.no_update else []),
                *(["--quiet"] if args.quiet else []),
            ],
        )
    )

    # 4) cmc_ema_multi_tf_v2 (daily-space)
    # refresh_cmc_ema_multi_tf_v2.py supports: --ids, --periods (incl lut), --alignment-type, --include-noncanonical, --price-table/out-table
    v2_argv = [
        "--ids",
        ids,
        "--periods",
        periods,
        "--alignment-type",
        args.v2_alignment_type,
        *(["--include-noncanonical"] if args.v2_include_noncanonical else []),
        "--price-schema",
        args.price_schema,
        "--price-table",
        args.price_table,
        "--out-schema",
        args.out_schema,
        "--out-table",
        args.v2_out_table,
    ]
    steps.append(Step(name="v2", path=SCRIPTS["v2"], argv=v2_argv))

    # Optional: allow skipping steps
    if args.only:
        keep = {x.strip().lower() for x in args.only.split(",") if x.strip()}
        steps = [s for s in steps if s.name.lower() in keep]

    return steps


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run all EMA refresh runners sequentially.",
        epilog="""
CONNECTION NOTES: This orchestrator runs multiple scripts in sequence.
The multi_tf script uses parallel workers (default: 4) which may need database connections.
If you see "too many clients already" errors:
  1. Close other database clients (PgAdmin, DBeaver, etc.)
  2. Check active connections: SELECT count(*) FROM pg_stat_activity;
  3. Increase Postgres max_connections if needed
  4. Run scripts individually instead of all at once
        """
    )

    p.add_argument("--ids", default="all", help="all | comma list like 1,52")
    p.add_argument("--start", default="2010-01-01", help="Start date/time for runners that accept it")
    p.add_argument("--end", default="", help="End date/time (optional)")
    p.add_argument(
        "--periods",
        default="lut",
        help="Comma list like 10,21,50 or 'lut' (recommended) to load from public.ema_alpha_lookup",
    )

    p.add_argument("--cal-scheme", default="both", choices=["us", "iso", "both"])
    p.add_argument("--anchor-scheme", default="both", choices=["us", "iso", "both"])

    p.add_argument("--no-update", action="store_true", help="Passes through to scripts that support it")
    p.add_argument("--full-refresh", action="store_true", help="For CAL runner: ignore state and run full/args.start")
    p.add_argument("--continue-on-error", action="store_true")

    # v2-specific knobs
    p.add_argument("--v2-alignment-type", default="tf_day")
    p.add_argument("--v2-include-noncanonical", action="store_true")
    p.add_argument("--price-schema", default="public")
    p.add_argument("--price-table", default="cmc_price_bars_1d", help="V2 price table (default: cmc_price_bars_1d - validated bars)")
    p.add_argument("--out-schema", default="public")
    p.add_argument("--v2-out-table", default="cmc_ema_multi_tf_v2")

    p.add_argument(
        "--only",
        default="",
        help="Optional subset: comma list of step names from {multi_tf,cal,cal_anchor,v2}",
    )

    # Validation options
    p.add_argument(
        "--validate",
        action="store_true",
        help="Run rowcount validation after refresh completes",
    )
    p.add_argument(
        "--alert-on-validation-error",
        action="store_true",
        help="Send Telegram alert if validation finds issues (requires --validate)",
    )

    add_logging_args(p)

    args = p.parse_args()
    args.end = args.end.strip() or None
    return args


def main() -> int:
    args = parse_args()

    # Setup logging
    logger = setup_logging(
        name="ema_runner",
        level=args.log_level,
        log_file=args.log_file,
        quiet=args.quiet,
        debug=args.debug,
    )

    try:
        _require_env()
    except RuntimeError as e:
        logger.error(f"Environment check failed: {e}")
        return 1

    steps = build_steps(args)

    if not steps:
        logger.warning("No steps selected")
        return 0

    logger.info(f"Running {len(steps)} EMA refresh steps: {[s.name for s in steps]}")
    logger.info(f"Configuration: ids={args.ids}, periods={args.periods}, start={args.start}, end={args.end}")

    failures: List[str] = []
    for i, step in enumerate(steps, 1):
        logger.info(f"Step {i}/{len(steps)}: {step.name}")
        try:
            _run_script(step, logger)
        except Exception as e:
            error_msg = str(e).lower()
            if "too many clients" in error_msg or "max_connections" in error_msg:
                logger.error(
                    f"Step {step.name} FAILED: DATABASE CONNECTION LIMIT REACHED. "
                    f"Try closing other database clients or increase Postgres max_connections. "
                    f"Error: {e}",
                    exc_info=True
                )
            else:
                logger.error(f"Step {step.name} FAILED: {type(e).__name__}: {e}", exc_info=True)

            failures.append(step.name)

            if not args.continue_on_error:
                logger.error("Stopping due to failure (use --continue-on-error to proceed)")
                break
            else:
                logger.warning(f"Continuing despite failure in {step.name}")

    if failures:
        logger.error(f"Completed with {len(failures)} failure(s): {failures}")
        return 1

    logger.info("All steps completed successfully")

    # Run validation if requested
    if args.validate:
        validation_passed = run_validation(args, logger)
        if not validation_passed:
            logger.warning("Validation found issues - check logs for details")
            # Don't fail the overall run, just warn

    return 0


if __name__ == "__main__":
    main()
