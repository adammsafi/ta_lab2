# src/ta_lab2/regimes/telemetry.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import csv
from typing import Optional, Dict, Any


@dataclass
class RegimeSnapshot:
    ts: str
    symbol: str
    L0: Optional[str]
    L1: Optional[str]
    L2: Optional[str]
    L3: Optional[str]
    size_mult: float
    stop_mult: float
    orders: str
    pyramids: bool
    gross_cap: float


def append_snapshot(
    path: Path, snap: RegimeSnapshot, extra: Optional[Dict[str, Any]] = None
) -> None:
    """
    Append one row (creating the file with header if new). Extras (e.g., pnl) can be included.
    """
    row = asdict(snap)
    if extra:
        row.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new_file:
            writer.writeheader()
        writer.writerow(row)
