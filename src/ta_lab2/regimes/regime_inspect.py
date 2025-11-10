# src/ta_lab2/cli/regime_inspect.py
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

from ta_lab2.regimes import (
    assess_data_budget,
    label_layer_monthly,
    label_layer_weekly,
    label_layer_daily,
    label_layer_intraday,
    resolve_policy,
    load_policy_table,
    DEFAULT_POLICY_TABLE,
)

def _read_df(path: Path) -> pd.DataFrame:
    # Minimal csv reader; expects 'close' and any precomputed EMA/ATR columns you use
    return pd.read_csv(path).sort_values("timestamp").set_index("timestamp")

def main() -> None:
    ap = argparse.ArgumentParser(description="Inspect multi-TF regime and resolved policy")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--monthly", type=Path)
    ap.add_argument("--weekly", type=Path)
    ap.add_argument("--daily", type=Path)
    ap.add_argument("--intraday", type=Path)
    ap.add_argument("--policy", type=Path, help="Optional YAML overlay for policy")
    args = ap.parse_args()

    df_m = _read_df(args.monthly) if args.monthly and args.monthly.exists() else None
    df_w = _read_df(args.weekly)  if args.weekly and args.weekly.exists() else None
    df_d = _read_df(args.daily)   if args.daily and args.daily.exists() else None
    df_i = _read_df(args.intraday) if args.intraday and args.intraday.exists() else None

    ctx = assess_data_budget(monthly=df_m, weekly=df_w, daily=df_d, intraday=df_i)
    mode = ctx.feature_tier

    L0 = label_layer_monthly(df_m, mode=mode).iloc[-1] if (df_m is not None and ctx.enabled_layers["L0"]) else None
    L1 = label_layer_weekly(df_w,  mode=mode).iloc[-1] if (df_w is not None and ctx.enabled_layers["L1"]) else None
    L2 = label_layer_daily(df_d,   mode=mode).iloc[-1] if (df_d is not None and ctx.enabled_layers["L2"]) else None
    L3 = label_layer_intraday(df_i).iloc[-1]          if (df_i is not None and ctx.enabled_layers["L3"]) else None

    # Load and show active policy table (optional)
    table = load_policy_table(str(args.policy)) if args.policy else DEFAULT_POLICY_TABLE

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

if __name__ == "__main__":
    main()
