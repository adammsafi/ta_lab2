# -*- coding: utf-8 -*-
"""
fedtools2.etl — CLI entrypoint.
Consolidates FEDFUNDS, DFEDTAR, DFEDTARL, DFEDTARU into a unified daily dataset,
writes CSV outputs, and (optionally) calls a user-supplied SQL writer to persist
the snapshot and append a run log.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd
import yaml

from fedtools2.utils.io import read_csv, ensure_dir
from fedtools2.utils.consolidation import combine_timeframes, missing_ranges


# -----------------------
# Config helpers
# -----------------------
def _load_config(cfg_path: Path | None) -> dict:
    """
    Load YAML config. If cfg_path is None, load the package default:
    fedtools2/config/default.yaml
    """
    if cfg_path is None:
        cfg_path = Path(__file__).with_suffix("").parent / "config" / "default.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_fed_dir(cfg: dict) -> Path:
    """
    Determine the directory that contains the four FRED CSVs:
      - FEDFUNDS.csv
      - DFEDTAR.csv
      - DFEDTARL.csv
      - DFEDTARU.csv

    Priority:
      1) cfg["fed_data_dir"] if present and exists
      2) env FEDTOOLS2_FED_DATA_DIR
      3) common local fallback (only if it exists)
      4) raise with a clear message
    """
    candidates: list[Optional[Path]] = []

    v = cfg.get("fed_data_dir")
    if v:
        candidates.append(Path(v))

    env_v = os.getenv("FEDTOOLS2_FED_DATA_DIR")
    if env_v:
        candidates.append(Path(env_v))

    # Adam's common path from earlier runs; use only if it actually exists.
    candidates.append(Path(r"C:\Users\asafi\Downloads\FinancialData\FedData"))

    for p in candidates:
        if p and p.exists():
            return p

    raise FileNotFoundError(
        "fed_data_dir not found. Set it in your YAML config (key: 'fed_data_dir') "
        "or define the FEDTOOLS2_FED_DATA_DIR environment variable to the folder "
        "that contains FEDFUNDS.csv / DFEDTAR*.csv."
    )


# -----------------------
# Core build
# -----------------------
def build_dataset(cfg: dict) -> pd.DataFrame:
    # Paths & toggles
    FED_DATA_DIR = _resolve_fed_dir(cfg)
    OUTPUT_DIR = Path(cfg.get("output_dir", "./output"))
    ensure_dir(OUTPUT_DIR)

    # Load CSVs
    fedfunds = read_csv(FED_DATA_DIR / "FEDFUNDS.csv")   # ['observation_date','FEDFUNDS']
    dfedtaru = read_csv(FED_DATA_DIR / "DFEDTARU.csv")   # ['observation_date','DFEDTARU']
    dfedtarl = read_csv(FED_DATA_DIR / "DFEDTARL.csv")   # ['observation_date','DFEDTARL']
    dfedtar  = read_csv(FED_DATA_DIR / "DFEDTAR.csv")    # ['observation_date','DFEDTAR']

    # Merge targets (single-era + range-era)
    merged_targets = combine_timeframes(
        dfs=[dfedtar, dfedtarl, dfedtaru],
        names=["DFEDTAR", "DFEDTARL", "DFEDTARU"],
        persist=True,
    )

    # Stop persisting DFEDTAR after the cutoff (keep NaN so dtype stays numeric)
    cutoff = pd.Timestamp(cfg.get("dfedtar_cutoff", "2008-12-15"))
    col = "DFEDTAR_DFEDTAR"
    merged_targets.loc[merged_targets.index > cutoff, col] = np.nan

    # TARGET_MID = DFEDTAR where available; otherwise midpoint of bounds
    merged_targets["TARGET_MID"] = merged_targets[col].where(
        ~merged_targets[col].isna(),
        (merged_targets["DFEDTARL_DFEDTARL"] + merged_targets["DFEDTARU_DFEDTARU"]) / 2.0,
    ).astype(float)

    # TARGET_SPREAD
    merged_targets["TARGET_SPREAD"] = (
        merged_targets["DFEDTARU_DFEDTARU"] - merged_targets["DFEDTARL_DFEDTARL"]
    )

    # FEDFUNDS monthly → daily ffill
    fedfunds["observation_date"] = pd.to_datetime(fedfunds["observation_date"])
    fedfunds = fedfunds.set_index("observation_date").sort_index()
    fedfunds_daily = fedfunds.resample("D").ffill()

    # Merge all & normalize has_* flags
    merged_all = merged_targets.join(fedfunds_daily, how="outer")
    has_cols = [c for c in merged_all.columns if c.startswith("has_")]
    if has_cols:
        merged_all[has_cols] = merged_all[has_cols].astype("boolean").fillna(False)

    # Regime labels
    merged_all["regime"] = pd.cut(
        merged_all.index,
        bins=[
            pd.Timestamp("1954-01-01"),
            pd.Timestamp("1982-09-26"),
            pd.Timestamp("2008-12-15"),
            pd.Timestamp("2099-12-31"),
        ],
        labels=["pre-target", "single-target", "target-range"],
    )

    return merged_all


# -----------------------
# Output helpers
# -----------------------
def save_outputs(df: pd.DataFrame, cfg: dict) -> Path:
    out_dir = Path(cfg.get("output_dir", "./output"))
    ensure_dir(out_dir)

    ts_path = out_dir / f"FED_Merged_{datetime.now():%Y%m%d_%H%M%S}.csv"
    df.to_csv(ts_path, index=True)

    if cfg.get("write_latest_copy", True):
        latest = out_dir / cfg.get("latest_filename", "FED_Merged_latest.csv")
        df.to_csv(latest, index=True)
        print(f"Also wrote: {latest}")

    print(f"Saved: {ts_path}")
    return ts_path


def _maybe_call_sql_sink(df: pd.DataFrame, cfg: dict, save_path: Path) -> None:
    """
    If cfg['sql']['enabled'] is True, dynamically import the user-provided
    writer function and call it with (df, conn_str, base_table, log_table, meta).
    """
    sql_cfg: Dict = cfg.get("sql", {}) or {}
    if not sql_cfg.get("enabled", False):
        return

    writer_path = sql_cfg.get("writer")
    if not writer_path or ":" not in writer_path:
        raise ValueError("sql.writer must be 'module:function', e.g. 'sql_sink_example:write_dataframe_and_log'")

    mod_name, fn_name = writer_path.split(":", 1)
    import importlib

    writer_mod = importlib.import_module(mod_name)
    writer_fn = getattr(writer_mod, fn_name)

    meta = {
        "run_ts": datetime.now().isoformat(timespec="seconds"),
        "row_count": int(df.shape[0]),
        "col_count": int(df.shape[1]),
        "min_date": df.index.min().isoformat() if len(df.index) else None,
        "max_date": df.index.max().isoformat() if len(df.index) else None,
        "output_path": str(save_path),
        "package": "fedtools2",
        "version": "0.1.0",
    }

    writer_fn(
        df=df,
        conn_str=sql_cfg.get("conn_str"),
        base_table=sql_cfg.get("base_table", "fed_targets_daily"),
        log_table=sql_cfg.get("log_table", "fed_targets_runs"),
        meta=meta,
    )


# -----------------------
# CLI
# -----------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Consolidate Federal Reserve rate datasets into a unified daily CSV."
    )
    parser.add_argument("--config", type=Path, default=None, help="Path to YAML config.")
    parser.add_argument("--plot", action="store_true", help="Show quick validation plot.")
    parser.add_argument("--verbose-missing", action="store_true", help="Print missing-range diagnostics.")
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    if args.plot:
        cfg["plot_quicklook"] = True
    if args.verbose_missing:
        cfg["verbose_missing"] = True

    df = build_dataset(cfg)

    # Optional: diagnostics
    if cfg.get("verbose_missing", False):
        for name in ["DFEDTAR", "DFEDTARL", "DFEDTARU"]:
            mask_col = f"has_{name}"
            if mask_col in df.columns:
                mask = ~df[mask_col]
                gaps = missing_ranges(mask)
                if gaps:
                    print(f"\n{name} missing ranges (up to 5):")
                    for s, e in gaps[:5]:
                        print(f"  {s.date()} → {e.date()}")
                    if len(gaps) > 5:
                        print(f"  ... {len(gaps)-5} more omitted.")

    # Optional: quicklook plot
    if cfg.get("plot_quicklook", False):
        try:
            import matplotlib.pyplot as plt
            ax = df[["TARGET_MID", "FEDFUNDS"]].plot(figsize=(11, 5), lw=1.1)
            ax.set_title("Fed Policy Target (Mid) vs Effective Fed Funds Rate")
            ax.set_xlabel("")
            ax.set_ylabel("Percent")
            plt.tight_layout()
            plt.show()
        except Exception as e:
            print("Plot skipped:", e)

    save_path = save_outputs(df, cfg)
    _maybe_call_sql_sink(df, cfg, save_path)


if __name__ == "__main__":
    main()
