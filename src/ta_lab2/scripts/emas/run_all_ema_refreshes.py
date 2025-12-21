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
from typing import List, Optional


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
    if not (os.getenv("TARGET_DB_URL") or os.getenv("MARKETDATA_DB_URL")):
        raise RuntimeError(
            "Neither TARGET_DB_URL nor MARKETDATA_DB_URL is set. "
            "Set TARGET_DB_URL before running this orchestrator."
        )


def _run_script(step: Step) -> None:
    print(f"\n=== [{step.name}] RUN ===")
    print(f"[{step.name}] path: {step.path}")
    print(f"[{step.name}] argv: {' '.join(shlex.quote(a) for a in step.argv)}")

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
            raise RuntimeError(f"[{step.name}] exited with code {code}") from e
    finally:
        sys.argv = old_argv

    dt = time.time() - t0
    print(f"[{step.name}] OK ({dt:.1f}s)")


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
    p = argparse.ArgumentParser(description="Run all EMA refresh runners sequentially.")

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
    p.add_argument("--quiet", action="store_true", help="Reduce output where supported")
    p.add_argument("--continue-on-error", action="store_true")

    # v2-specific knobs
    p.add_argument("--v2-alignment-type", default="tf_day")
    p.add_argument("--v2-include-noncanonical", action="store_true")
    p.add_argument("--price-schema", default="public")
    p.add_argument("--price-table", default="cmc_price_histories7")
    p.add_argument("--out-schema", default="public")
    p.add_argument("--v2-out-table", default="cmc_ema_multi_tf_v2")

    p.add_argument(
        "--only",
        default="",
        help="Optional subset: comma list of step names from {multi_tf,cal,cal_anchor,v2}",
    )

    args = p.parse_args()
    args.end = args.end.strip() or None
    return args


def main() -> int:
    _require_env()
    args = parse_args()
    steps = build_steps(args)

    if not steps:
        print("No steps selected.")
        return 0

    failures: List[str] = []
    for step in steps:
        try:
            _run_script(step)
        except Exception as e:
            print(f"\n!!! [{step.name}] FAILED: {type(e).__name__}")
            print(repr(e))
            failures.append(step.name)

            if not args.continue_on_error:
                break

    if failures:
        print(f"\nDone with failures: {failures}")
        return 1

    print("\nAll steps completed successfully.")
    return 0


if __name__ == "__main__":
    main()
