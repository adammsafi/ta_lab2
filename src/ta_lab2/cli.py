# src/ta_lab2/cli.py
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import pandas as pd

# NOTE: Your repo uses a root-level config.py; keep that behavior.
from config import load_settings, project_root

# Existing pipeline entry (preserved)
from ta_lab2.regimes.run_btc_pipeline import run_btc_pipeline

# Regime helpers (optional-import safe thanks to try/except in __init__)
from ta_lab2.regimes import (
    assess_data_budget,
    label_layer_monthly,
    label_layer_weekly,
    label_layer_daily,
    label_layer_intraday,
    resolve_policy,                  # back-compat
    load_policy_table,
    DEFAULT_POLICY_TABLE,
)

# NEW: table-aware resolver (additive)
try:
    from ta_lab2.regimes import resolve_policy_from_table
except Exception:
    resolve_policy_from_table = None  # type: ignore

# NEW: feature builder so labelers have EMAs/ATR when needed
try:
    from ta_lab2.regimes.feature_utils import ensure_regime_features
except Exception:
    ensure_regime_features = None  # type: ignore

# ----------------------------
# Utilities
# ----------------------------
def _read_df(path: Path) -> pd.DataFrame:
    """
    Minimal CSV reader for regime-inspect.
    Expects 'timestamp' and 'close' (index becomes timestamp if present).
    Any EMA/ATR columns are optional; if missing, we add them if feature_utils is available.
    """
    df = pd.read_csv(path)
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp").set_index("timestamp")
    else:
        df = df.sort_index()
    return df

def _default_policy_yaml() -> Path:
    """
    Default overlay location matches your repo layout:
    <repo_root>/configs/regime_policies.yaml (next to default.yaml)
    """
    return project_root() / "configs" / "regime_policies.yaml"

# ----------------------------
# Commands
# ----------------------------
def cmd_pipeline(args: argparse.Namespace) -> int:
    """
    Original behavior: load YAML config and run the BTC pipeline.
    """
    settings = load_settings(args.config)

    csv = Path(settings.data_csv)
    out_dir = Path(settings.out_dir)

    result = run_btc_pipeline(
        csv_path=csv,
        out_dir=out_dir,
        ema_windows=settings.ema_windows,
        resample=settings.resample,
    )
    print("Pipeline complete:", result)
    return 0

def _ensure_feats_if_possible(df: pd.DataFrame | None, tf: str) -> pd.DataFrame | None:
    if df is None:
        return None
    if ensure_regime_features is None:
        return df
    return ensure_regime_features(df, tf=tf)

def cmd_regime_inspect(args: argparse.Namespace) -> int:
    """
    Print multi-TF regime labels and the resolved policy.
    Uses YAML overlay if present; otherwise defaults to in-code table.
    """
    df_m = _read_df(args.monthly)  if args.monthly  and args.monthly.exists()  else None
    df_w = _read_df(args.weekly)   if args.weekly   and args.weekly.exists()   else None
    df_d = _read_df(args.daily)    if args.daily    and args.daily.exists()    else None
    df_i = _read_df(args.intraday) if args.intraday and args.intraday.exists() else None

    # Ensure EMAs/ATR exist (no-ops if feature utils unavailable)
    df_m = _ensure_feats_if_possible(df_m, "M")
    df_w = _ensure_feats_if_possible(df_w, "W")
    df_d = _ensure_feats_if_possible(df_d, "D")
    df_i = _ensure_feats_if_possible(df_i, "I")

    ctx = assess_data_budget(monthly=df_m, weekly=df_w, daily=df_d, intraday=df_i)
    mode = ctx.feature_tier

    L0 = label_layer_monthly(df_m, mode=mode).iloc[-1] if (df_m is not None and ctx.enabled_layers["L0"]) else None
    L1 = label_layer_weekly(df_w,  mode=mode).iloc[-1] if (df_w is not None and ctx.enabled_layers["L1"]) else None
    L2 = label_layer_daily(df_d,   mode=mode).iloc[-1] if (df_d is not None and ctx.enabled_layers["L2"]) else None
    L3 = label_layer_intraday(df_i).iloc[-1]          if (df_i is not None and ctx.enabled_layers["L3"]) else None

    # Policy table: CLI arg > default location > in-code defaults
    policy_path = args.policy or _default_policy_yaml()
    table = load_policy_table(str(policy_path)) if policy_path and policy_path.exists() else DEFAULT_POLICY_TABLE

    # Use overlay-aware resolver if available; else fallback to default resolver
    if resolve_policy_from_table is not None:
        pol = resolve_policy_from_table(table, L0=L0, L1=L1, L2=L2, L3=L3)
    else:
        pol = resolve_policy(L0=L0, L1=L1, L2=L2, L3=L3)

    print(f"Symbol: {args.symbol}")
    print(f"Feature tier: {mode}; Bars: {ctx.bars_by_tf}")
    print(f"L0 (Monthly): {L0}")
    print(f"L1 (Weekly):  {L1}")
    print(f"L2 (Daily):   {L2}")
    print(f"L3 (Intra):   {L3}")
    print("Resolved policy:")
    print(f"  size_mult = {pol.size_mult}")
    print(f"  stop_mult = {pol.stop_mult}")
    print(f"  orders    = {pol.orders}")
    print(f"  pyramids  = {pol.pyramids}")
    print(f"  gross_cap = {pol.gross_cap}")
    print(f"  setups    = {pol.setups}")
    return 0

# ----------------------------
# Main
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ta-lab2",
        description="ta_lab2 CLI",
    )
    sub = ap.add_subparsers(dest="cmd")

    # Subcommand: pipeline (preserves your original behavior)
    p_pipeline = sub.add_parser("pipeline", help="Run the BTC pipeline (original default behavior)")
    p_pipeline.add_argument(
        "--config", "-c",
        default="config/default.yaml",
        help="Path to YAML config relative to project root (default: config/default.yaml)",
    )
    p_pipeline.set_defaults(func=cmd_pipeline)

    # Subcommand: regime-inspect (new)
    p_reg = sub.add_parser("regime-inspect", help="Inspect multi-timeframe regimes and resolved policy")
    p_reg.add_argument("--symbol", required=True, help="Symbol label for printing (e.g., BTCUSD)")
    p_reg.add_argument("--monthly",  type=Path, help="CSV with monthly bars (optional)")
    p_reg.add_argument("--weekly",   type=Path, help="CSV with weekly bars (optional)")
    p_reg.add_argument("--daily",    type=Path, help="CSV with daily bars (optional)")
    p_reg.add_argument("--intraday", type=Path, help="CSV with intraday bars (e.g., 4H/1H) (optional)")
    p_reg.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="Optional YAML overlay (defaults to <repo_root>/configs/regime_policies.yaml if present)",
    )
    p_reg.set_defaults(func=cmd_regime_inspect)

    # Back-compat: if no subcommand is given, behave like old CLI (run pipeline)
    ap.add_argument(
        "--config", "-c",
        default="config/default.yaml",
        help=argparse.SUPPRESS,  # hidden; shown on pipeline subcommand
    )
    return ap

def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    # Back-compat path: no subcommand provided -> run pipeline with top-level --config
    if args.cmd is None:
        shim = argparse.Namespace(config=args.config)
        return cmd_pipeline(shim)

    if hasattr(args, "func") and callable(args.func):
        return args.func(args)

    ap.print_help()
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
