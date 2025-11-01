# src/ta_lab2/regimes/run_btc_pipeline.py
from __future__ import annotations
from pathlib import Path
from typing import Any
import pandas as pd

# Import the high-level BTC pipeline from pipelines (keeps orchestration unified)
from ta_lab2.pipelines.btc_pipeline import run_btc_pipeline as _btc_core


def run_btc_pipeline(
    csv_path: str | Path,
    out_dir: str | Path,
    ema_windows: list[int] | None = None,
    resample: dict | None = None,
    *,
    do_calendar: bool = True,
    do_indicators: bool = True,
    do_returns: bool = True,
    do_volatility: bool = True,
    do_ema: bool = True,
    do_regimes: bool = True,
    do_segments: bool = True,
    config: dict | None = None,
) -> dict[str, Any]:
    """
    Orchestrate the BTC pipeline end-to-end.
      1) Load CSV from csv_path
      2) Compute all requested features / regimes
      3) Write outputs to out_dir
      4) Return a structured result dict (data + metadata)

    This wrapper keeps the CLI and tests portable while delegating core logic
    to src/ta_lab2/pipelines/btc_pipeline.py (the canonical implementation).
    """

    csv_path = Path(csv_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1) Load data ----
    df = pd.read_csv(csv_path)

    # ---- 2) Delegate to the main pipeline ----
    result = _btc_core(
        df,
        price_cols=("open", "high", "low", "close"),
        ema_windows=tuple(ema_windows or (21, 50, 100, 200)),
        returns_modes=("log", "pct"),
        returns_windows=(30, 60, 90),
        resample=resample.get("freq") if isinstance(resample, dict) else None,
        do_calendar=do_calendar,
        do_indicators=do_indicators,
        do_returns=do_returns,
        do_volatility=do_volatility,
        do_ema=do_ema,
        do_regimes=do_regimes,
        do_segments=do_segments,
        config=config,
    )

    # ---- 3) Persist key outputs (parquet for speed) ----
    if isinstance(result, dict) and "data" in result:
        df_out = result["data"]
        if isinstance(df_out, pd.DataFrame):
            df_out.to_parquet(out_dir / "daily_en.parquet", index=False)
    if isinstance(result, dict) and "regime_major" in result:
        rm = result["regime_major"]
        if isinstance(rm, pd.DataFrame):
            rm.to_parquet(out_dir / "daily_regimes.parquet", index=False)

    # ---- 4) Minimal fallback if core returned primitive ----
    if not isinstance(result, dict):
        result = {"data": df, "rows": len(df), "out_dir": str(out_dir)}

    # ---- 5) Return result summary ----
    return {
        "rows": len(result.get("data", df)),
        "out_dir": str(out_dir),
        "keys": list(result.keys()),
    }


if __name__ == "__main__":
    raise SystemExit("Use CLI entry points or import run_btc_pipeline() from code.")
