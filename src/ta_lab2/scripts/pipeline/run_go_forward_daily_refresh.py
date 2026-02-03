from __future__ import annotations

"""
run_go_forward_daily_refresh.py

Go-forward orchestrator with STEP-BASED state.

Behavior:
- Reads daily_max = MAX(timestamp) from public.cmc_price_histories7.
- For each step, checks its own watermark in public.ta_lab2_pipeline_state.
  - If step_watermark >= daily_max and not --force, the step is skipped.
  - If the step runs and succeeds, its watermark is advanced to daily_max.
- This prevents rerunning expensive early steps when a later step fails.

Additions in this version:
- Allows forwarding "full rebuild" + multiprocessing flags to BOTH bars and EMA steps:
  - --bars-full-rebuild / --emas-full-rebuild (or --full-rebuild for both)
  - --parallel
  - --num-processes N
- Full rebuild implies a forced run for the affected steps (ignores watermark), unless you
  explicitly want watermark gating (not recommended for full rebuild).

Notes:
- Requires TARGET_DB_URL set in env.

Run examples:
  # Normal incremental pipeline
  python run_go_forward_daily_refresh.py

  # Bars only, parallel, 8 processes
  python run_go_forward_daily_refresh.py --bars-only --parallel --num-processes 8

  # Force all selected steps regardless of state (still incremental inside scripts)
  python run_go_forward_daily_refresh.py --force

  # Full rebuild bars + emas (implies force for those steps)
  python run_go_forward_daily_refresh.py --full-rebuild --parallel --num-processes 8

  # Full rebuild bars only
  python run_go_forward_daily_refresh.py --bars-only --bars-full-rebuild --parallel --num-processes 8
"""

import argparse
import os
import runpy
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ----------------------------
# DB / State
# ----------------------------

DAILY_TABLE = "public.cmc_price_histories7"
STATE_TABLE = "public.ta_lab2_pipeline_state"

# A "base" key for this orchestrator; each step appends :<step_name>
STATE_KEY_BASE = "go_forward_daily_refresh:last_daily_max_ts"


def _log(msg: str) -> None:
    print(f"[go_forward] {msg}")


def _require_env() -> None:
    if not os.getenv("TARGET_DB_URL"):
        raise RuntimeError("TARGET_DB_URL env var is required.")


def get_engine() -> Engine:
    return create_engine(os.environ["TARGET_DB_URL"], future=True)


def ensure_state_table(engine: Engine) -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
      state_key   text PRIMARY KEY,
      state_value timestamptz NULL,
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))


def _state_key_for_step(step_name: str) -> str:
    return f"{STATE_KEY_BASE}:{step_name}"


def get_state(engine: Engine, state_key: str) -> Optional[pd.Timestamp]:
    q = text(f"SELECT state_value FROM {STATE_TABLE} WHERE state_key = :k;")
    df = pd.read_sql(q, engine, params={"k": state_key})
    if df.empty or pd.isna(df.loc[0, "state_value"]):
        return None
    return pd.to_datetime(df.loc[0, "state_value"], utc=True)


def set_state(engine: Engine, state_key: str, ts: pd.Timestamp) -> None:
    q = text(
        f"""
        INSERT INTO {STATE_TABLE} (state_key, state_value, updated_at)
        VALUES (:k, :v, now())
        ON CONFLICT (state_key) DO UPDATE SET
          state_value = EXCLUDED.state_value,
          updated_at  = now();
        """
    )
    with engine.begin() as conn:
        conn.execute(q, {"k": state_key, "v": ts.to_pydatetime()})


def get_daily_max_ts(engine: Engine) -> Optional[pd.Timestamp]:
    q = text(f'SELECT MAX("timestamp") AS mx FROM {DAILY_TABLE};')
    df = pd.read_sql(q, engine)
    mx = df.loc[0, "mx"]
    if pd.isna(mx):
        return None
    return pd.to_datetime(mx, utc=True)


def bars_state_has_any_rows(engine: Engine, state_table: str, ids: str) -> bool:
    """
    Return True if the given bar state table has at least 1 row (optionally scoped to ids).
    ids is the same string passed to bar scripts: "all" or space/comma-separated ids.
    """
    if ids == "all":
        q = text(f"SELECT 1 FROM {state_table} LIMIT 1;")
        with engine.connect() as c:
            return c.execute(q).first() is not None

    # Parse ids similarly to your scripts (simple/robust parsing)
    # Accept comma or whitespace separated.
    parts = [p for p in ids.replace(",", " ").split() if p.strip()]
    id_list = [int(p) for p in parts]

    # Use ANY(:ids) for PG array match
    q = text(f"SELECT 1 FROM {state_table} WHERE id = ANY(:ids) LIMIT 1;")
    with engine.connect() as c:
        return c.execute(q, {"ids": id_list}).first() is not None


# ----------------------------
# Script runner (in-process)
# ----------------------------


@dataclass
class Step:
    name: str
    path: Path
    argv: List[str]
    kind: str  # "bars" | "ema" | "other"


def run_step(step: Step) -> None:
    _log(f"=== [{step.name}] RUN ===")
    _log(f"[{step.name}] path: {step.path}")
    _log(f"[{step.name}] argv: {' '.join(shlex.quote(a) for a in step.argv)}")

    old_argv = sys.argv[:]
    t0 = time.time()
    try:
        sys.argv = [str(step.path), *step.argv]
        runpy.run_path(str(step.path), run_name="__main__")
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
        if code != 0:
            raise RuntimeError(f"[{step.name}] exited with code {code}") from e
    finally:
        sys.argv = old_argv

    _log(f"[{step.name}] OK ({time.time() - t0:.1f}s)")


# ----------------------------
# Arg forwarding helpers
# ----------------------------


def _add_parallel_args(
    argv: List[str], parallel: bool, num_processes: Optional[int]
) -> List[str]:
    # Bars scripts generally don't implement --parallel; they use --num-processes only.
    out = list(argv)
    if num_processes is not None:
        out.extend(["--num-processes", str(num_processes)])
    return out


def _add_full_rebuild_arg(argv: List[str], full_rebuild: bool) -> List[str]:
    out = list(argv)
    if full_rebuild:
        out.append("--full-rebuild")
    return out


def build_steps(
    repo_root: Path,
    ids: str,
    periods: str,
    bars_only: bool,
    bars_full_rebuild: bool,
    emas_full_rebuild: bool,
    parallel: bool,
    num_processes: Optional[int],
) -> List[Step]:
    """
    We pass:
    - bars scripts: --ids <ids> plus optional --full-rebuild and --parallel/--num-processes
    - EMA orchestrator: --ids <ids> --periods <periods> plus optional --full-rebuild and --parallel/--num-processes
    - _u sync: --use-ingested-at only (no rebuild/parallel flags)
    """
    bars_dir = repo_root / "src" / "ta_lab2" / "scripts" / "bars"
    emas_dir = repo_root / "src" / "ta_lab2" / "scripts" / "emas"

    # Bars
    steps: List[Step] = []
    bars_scripts = [
        ("bars_multi_tf", "refresh_cmc_price_bars_multi_tf.py"),
        ("bars_cal_us", "refresh_cmc_price_bars_multi_tf_cal_us.py"),
        ("bars_cal_iso", "refresh_cmc_price_bars_multi_tf_cal_iso.py"),
        ("bars_cal_anchor_us", "refresh_cmc_price_bars_multi_tf_cal_anchor_us.py"),
        ("bars_cal_anchor_iso", "refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py"),
    ]

    for name, fname in bars_scripts:
        argv = ["--ids", ids]
        argv = _add_full_rebuild_arg(argv, bars_full_rebuild)

        if name == "bars_multi_tf":
            # multi_tf script does NOT accept --parallel (it only supports --num-processes)
            if num_processes is not None:
                argv.extend(["--num-processes", str(num_processes)])
        else:
            argv = _add_parallel_args(
                argv, parallel=parallel, num_processes=num_processes
            )

        steps.append(Step(name=name, path=bars_dir / fname, argv=argv, kind="bars"))

    if bars_only:
        return steps

    # EMAs (orchestrator)
    ema_argv = ["--ids", ids, "--periods", periods]
    ema_argv = _add_full_rebuild_arg(ema_argv, emas_full_rebuild)
    ema_argv = _add_parallel_args(
        ema_argv, parallel=parallel, num_processes=num_processes
    )
    steps.append(
        Step("emas_all", emas_dir / "run_all_ema_refreshes.py", ema_argv, kind="ema")
    )

    # _u sync (keep simple)
    steps.append(
        Step(
            "ema_u_sync",
            emas_dir / "sync_cmc_ema_multi_tf_u.py",
            ["--use-ingested-at"],
            kind="other",
        )
    )

    return steps


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Go-forward pipeline runner (step-based state)."
    )

    ap.add_argument("--ids", default="all", help="Ids to run (default: all).")
    ap.add_argument("--periods", default="lut", help="EMA periods (default: lut).")
    ap.add_argument(
        "--repo-root",
        default="",
        help="Optional path to repo root. If omitted, inferred as 4 levels up from this file.",
    )

    ap.add_argument(
        "--force",
        action="store_true",
        help="Run steps even if no new daily data is detected for them.",
    )
    ap.add_argument(
        "--bars-only",
        action="store_true",
        help="Only run the 5 bar refresh steps; skip EMAs and _u sync.",
    )

    # New: rebuild / multiprocessing controls (forwarded)
    ap.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Enable full rebuild for BOTH bars and emas (equivalent to --bars-full-rebuild --emas-full-rebuild).",
    )
    ap.add_argument(
        "--bars-full-rebuild",
        action="store_true",
        help="Forward --full-rebuild to all BAR steps.",
    )
    ap.add_argument(
        "--bars-full-rebuild-if-no-state",
        action="store_true",
        help="For BAR steps only: if the bar script's *state table* has no rows for the selected ids, run that step as --full-rebuild.",
    )
    ap.add_argument(
        "--emas-full-rebuild",
        action="store_true",
        help="Forward --full-rebuild to EMA orchestrator step.",
    )
    ap.add_argument(
        "--parallel",
        action="store_true",
        help="Forward --parallel to bars and EMA orchestrator steps.",
    )
    ap.add_argument(
        "--num-processes",
        type=int,
        default=None,
        help="Forward --num-processes N (requires --parallel). If omitted, scripts decide their default.",
    )

    args = ap.parse_args()

    if args.num_processes is not None and args.num_processes <= 0:
        raise ValueError("--num-processes must be a positive integer.")

    # ----------------------------
    # NEW CLI LOGIC:
    # If user provides --num-processes, implicitly enable --parallel.
    # ----------------------------
    parallel = bool(args.parallel or (args.num_processes is not None))

    # Expand convenience flag
    bars_full_rebuild = bool(args.bars_full_rebuild or args.full_rebuild)
    emas_full_rebuild = bool(args.emas_full_rebuild or args.full_rebuild)

    _require_env()
    engine = get_engine()
    ensure_state_table(engine)

    daily_max = get_daily_max_ts(engine)
    if daily_max is None:
        _log(f"No rows found in {DAILY_TABLE}. Nothing to do.")
        return

    here = Path(__file__).resolve()
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        # expected: repo/src/ta_lab2/scripts/pipeline/this_file.py  => go up 4 to repo_root
        repo_root = here.parents[4]

    steps = build_steps(
        repo_root=repo_root,
        ids=args.ids,
        periods=args.periods,
        bars_only=bool(args.bars_only),
        bars_full_rebuild=bars_full_rebuild,
        emas_full_rebuild=emas_full_rebuild,
        parallel=parallel,  # <-- changed
        num_processes=args.num_processes,
    )

    _log(f"daily_max={daily_max} (from {DAILY_TABLE})")
    _log(
        "flags: "
        f"bars_only={bool(args.bars_only)} "
        f"force={bool(args.force)} "
        f"bars_full_rebuild={bars_full_rebuild} "
        f"bars_full_rebuild_if_no_state={bool(args.bars_full_rebuild_if_no_state)} "
        f"emas_full_rebuild={emas_full_rebuild} "
        f"parallel={parallel} "
        f"num_processes={args.num_processes}"
    )

    any_ran = False
    any_failed = False

    for step in steps:
        if not step.path.exists():
            raise FileNotFoundError(f"Missing script: {step.path}")

        step_key = _state_key_for_step(step.name)
        step_last = get_state(engine, step_key)

        # ----------------------------
        # AUTO full rebuild for bars if no bar-state exists
        # (only when user enabled it, and only if not explicitly bars_full_rebuild already)
        # ----------------------------
        step_full_rebuild = False

        if (
            step.kind == "bars"
            and args.bars_full_rebuild_if_no_state
            and not bars_full_rebuild
        ):
            bars_state_tables = {
                "bars_multi_tf": "public.cmc_price_bars_multi_tf_state",
                "bars_cal_us": "public.cmc_price_bars_multi_tf_cal_us_state",
                "bars_cal_iso": "public.cmc_price_bars_multi_tf_cal_iso_state",
                "bars_cal_anchor_us": "public.cmc_price_bars_multi_tf_cal_anchor_us_state",
                "bars_cal_anchor_iso": "public.cmc_price_bars_multi_tf_cal_anchor_iso_state",
            }

            st = bars_state_tables.get(step.name)
            if st is None:
                raise RuntimeError(f"No bars state-table mapping for step: {step.name}")

            has_state = bars_state_has_any_rows(engine, st, args.ids)
            if not has_state:
                _log(
                    f"[{step.name}] No state rows in {st} for ids={args.ids}; forcing --full-rebuild for this step."
                )
                step_full_rebuild = True
                if "--full-rebuild" not in step.argv:
                    step.argv.append("--full-rebuild")

        # ----------------------------
        # Decide whether to ignore watermark (skip gating)
        # ----------------------------
        ignore_watermark = bool(args.force)
        if step.kind == "bars" and (bars_full_rebuild or step_full_rebuild):
            ignore_watermark = True
        if step.kind == "ema" and emas_full_rebuild:
            ignore_watermark = True

        if (
            (not ignore_watermark)
            and (step_last is not None)
            and (daily_max <= step_last)
        ):
            _log(f"=== [{step.name}] SKIP ===")
            _log(f"[{step.name}] daily_max={daily_max} <= step_last={step_last}")
            continue

        any_ran = True
        try:
            run_step(step)
        except Exception:
            any_failed = True
            raise
        else:
            set_state(engine, step_key, daily_max)
            _log(f"[{step.name}] Updated state {step_key} = {daily_max.isoformat()}")

    # Optional: maintain a "whole pipeline" key as a convenience indicator.
    # We only advance it if all selected steps completed (no failures) and at least one ran.
    if (not any_failed) and any_ran:
        set_state(engine, STATE_KEY_BASE, daily_max)
        _log(f"Done. Updated state {STATE_KEY_BASE} = {daily_max.isoformat()}")
    elif not any_ran:
        _log("No steps needed. All selected steps already caught up. Exiting.")
    else:
        _log("Pipeline did not complete. Not updating overall state key.")


if __name__ == "__main__":
    main()
