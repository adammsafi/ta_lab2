# src/ta_lab2/time/specs.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence, Optional, Dict, Set, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# -----------------------------
# Enums / semantic primitives
# -----------------------------


class CalendarScheme(str, Enum):
    """Calendar convention for alignment/anchoring logic."""
    NONE = "NONE"   # for tf-day tables
    US = "US"
    ISO = "ISO"
    CAL = "CAL"     # optional catch-all if you ever use it


class TimeframeFamily(str, Enum):
    """High-level timeframe semantics family."""
    TF_DAY = "TF_DAY"            # fixed-day buckets (e.g., 5D, 30D, 360D)
    CAL = "CAL"                  # calendar-aligned (full periods only)
    CAL_ANCHOR = "CAL_ANCHOR"    # calendar-anchored (partial at dataset edges allowed)


class PartialPolicy(str, Enum):
    """Table-level partial-bar policy."""
    NONE = "NONE"
    START_END_ALLOWED = "START_END_ALLOWED"


# -----------------------------
# Timeframe spec (from dim_timeframe)
# -----------------------------


@dataclass(frozen=True, slots=True)
class TimeframeSpec:
    """
    Single-source-of-truth semantic spec for a timeframe row in dim_timeframe.

    This mirrors the schema additions you made:
      - calendar_scheme
      - allow_partial_start / allow_partial_end
      - tf_days_min / tf_days_max

    Note: other legacy dim_timeframe columns can be added here later if needed.
    """
    tf: str
    calendar_scheme: Optional[str] = None
    allow_partial_start: bool = False
    allow_partial_end: bool = False
    tf_days_min: Optional[int] = None
    tf_days_max: Optional[int] = None

    def scheme(self) -> CalendarScheme:
        raw = (self.calendar_scheme or "").strip().upper()
        if not raw:
            return CalendarScheme.NONE
        # allow "CAL_US" style strings if you ever store those; normalize a bit
        if raw in ("US",):
            return CalendarScheme.US
        if raw in ("ISO",):
            return CalendarScheme.ISO
        if raw in ("CAL",):
            return CalendarScheme.CAL
        # fall back to string enum if matches
        try:
            return CalendarScheme(raw)  # type: ignore[arg-type]
        except Exception:
            # unknown schemes still allowed, but treated as CAL bucket
            return CalendarScheme.CAL

    def allows_partial(self) -> bool:
        return bool(self.allow_partial_start or self.allow_partial_end)

    def tf_days_bounds(self) -> Tuple[Optional[int], Optional[int]]:
        return (self.tf_days_min, self.tf_days_max)

    def realized_tf_days_ok(self, tf_days: Optional[int]) -> bool:
        """
        Check tf_days against [tf_days_min, tf_days_max] when present.
        """
        if tf_days is None:
            return False
        lo, hi = self.tf_days_bounds()
        if lo is not None and tf_days < lo:
            return False
        if hi is not None and tf_days > hi:
            return False
        return True


# -----------------------------
# Table spec (declared/configured)
# -----------------------------


@dataclass(frozen=True, slots=True)
class TableSpec:
    """
    Semantic spec for a specific bars table. This is what prevents drift.

    The refresh + QA + EMA layers should take a TableSpec + TimeframeSpec(s)
    and obey them; no calendar logic should be inferred elsewhere.
    """
    table_name: str
    family: TimeframeFamily
    calendar_scheme: CalendarScheme = CalendarScheme.NONE
    partial_policy: PartialPolicy = PartialPolicy.NONE

    # Allowed timeframes for this table. If non-empty, treat as allowlist.
    timeframe_allowlist: Tuple[str, ...] = ()

    # Optional extra guardrails (useful for QA/invariants)
    disallow_timeframes: Tuple[str, ...] = ()

    def allows_partials(self) -> bool:
        return self.partial_policy == PartialPolicy.START_END_ALLOWED

    def is_calendar(self) -> bool:
        return self.family in (TimeframeFamily.CAL, TimeframeFamily.CAL_ANCHOR)

    def is_anchored(self) -> bool:
        return self.family == TimeframeFamily.CAL_ANCHOR

    def assert_tf_allowed(self, tf: str) -> None:
        if self.timeframe_allowlist and tf not in self.timeframe_allowlist:
            raise ValueError(
                f"{self.table_name}: timeframe '{tf}' not in allowlist "
                f"({len(self.timeframe_allowlist)} allowed)."
            )
        if self.disallow_timeframes and tf in self.disallow_timeframes:
            raise ValueError(f"{self.table_name}: timeframe '{tf}' is explicitly disallowed.")


# -----------------------------
# Registry (your five tables)
# -----------------------------


def default_bars_table_registry() -> Dict[str, TableSpec]:
    """
    Central, explicit registry. Keep this in sync with your design decision:

      - cmc_price_bars_multi_tf must NOT emit *_CAL timeframes
      - calendar semantics are reserved for *_cal* tables
    """
    return {
        # 1) TF_DAY based, NOT calendar-aligned
        "cmc_price_bars_multi_tf": TableSpec(
            table_name="cmc_price_bars_multi_tf",
            family=TimeframeFamily.TF_DAY,
            calendar_scheme=CalendarScheme.NONE,
            partial_policy=PartialPolicy.NONE,
            # Leave allowlist empty to allow any TF_DAY style TFs,
            # but explicitly disallow any CAL-labelled TFs if they exist.
            disallow_timeframes=(
                "1W_CAL", "2W_CAL", "3W_CAL", "4W_CAL",
                "1M_CAL", "3M_CAL", "6M_CAL", "12M_CAL",
                "1W_ANCHOR", "1M_ANCHOR", "12M_ANCHOR",
            ),
        ),

        # 2) Calendar-aligned (US), full periods only
        "cmc_price_bars_multi_tf_cal_us": TableSpec(
            table_name="cmc_price_bars_multi_tf_cal_us",
            family=TimeframeFamily.CAL,
            calendar_scheme=CalendarScheme.US,
            partial_policy=PartialPolicy.NONE,
        ),

        # 3) Calendar-aligned (ISO), full periods only
        "cmc_price_bars_multi_tf_cal_iso": TableSpec(
            table_name="cmc_price_bars_multi_tf_cal_iso",
            family=TimeframeFamily.CAL,
            calendar_scheme=CalendarScheme.ISO,
            partial_policy=PartialPolicy.NONE,
        ),

        # 4) Calendar-anchored (US), partial at dataset edges allowed
        "cmc_price_bars_multi_tf_cal_anchor_us": TableSpec(
            table_name="cmc_price_bars_multi_tf_cal_anchor_us",
            family=TimeframeFamily.CAL_ANCHOR,
            calendar_scheme=CalendarScheme.US,
            partial_policy=PartialPolicy.START_END_ALLOWED,
        ),

        # 5) Calendar-anchored (ISO), partial at dataset edges allowed
        "cmc_price_bars_multi_tf_cal_anchor_iso": TableSpec(
            table_name="cmc_price_bars_multi_tf_cal_anchor_iso",
            family=TimeframeFamily.CAL_ANCHOR,
            calendar_scheme=CalendarScheme.ISO,
            partial_policy=PartialPolicy.START_END_ALLOWED,
        ),
    }


# -----------------------------
# Loader for dim_timeframe
# -----------------------------


DIM_TIMEFRAME_SELECT_SQL = """
SELECT
    tf,
    calendar_scheme,
    allow_partial_start,
    allow_partial_end,
    tf_days_min,
    tf_days_max
FROM public.dim_timeframe
"""


@dataclass(slots=True)
class TimeSpecStore:
    """
    In-memory store of TimeframeSpec + TableSpec.

    This is the object you pass around to refresh/QA/EMA code so they stop
    inferring semantics and start obeying specs.
    """
    timeframes: Dict[str, TimeframeSpec] = field(default_factory=dict)
    tables: Dict[str, TableSpec] = field(default_factory=default_bars_table_registry)

    def get_tf(self, tf: str) -> TimeframeSpec:
        try:
            return self.timeframes[tf]
        except KeyError as e:
            raise KeyError(
                f"Timeframe '{tf}' not found in dim_timeframe; "
                f"add it before using it anywhere."
            ) from e

    def get_table(self, table_name: str) -> TableSpec:
        try:
            return self.tables[table_name]
        except KeyError as e:
            raise KeyError(
                f"TableSpec for '{table_name}' not found. "
                f"Add it to default_bars_table_registry()."
            ) from e

    def assert_tf_allowed_for_table(self, table_name: str, tf: str) -> None:
        table = self.get_table(table_name)
        table.assert_tf_allowed(tf)

    def list_timeframes(self) -> Tuple[str, ...]:
        return tuple(sorted(self.timeframes.keys()))

    def list_tables(self) -> Tuple[str, ...]:
        return tuple(sorted(self.tables.keys()))

    def timeframes_for_table(self, table_name: str, *, tfs: Optional[Iterable[str]] = None) -> Tuple[TimeframeSpec, ...]:
        """
        Return TimeframeSpecs for a table, optionally restricted to `tfs`,
        and enforce allowlist/disallow rules.
        """
        table = self.get_table(table_name)
        if tfs is None:
            # If the table has an explicit allowlist, use it; otherwise return all
            # and let higher-level code decide which TFs it wants to process.
            chosen = list(table.timeframe_allowlist) if table.timeframe_allowlist else list(self.timeframes.keys())
        else:
            chosen = list(tfs)

        out: list[TimeframeSpec] = []
        for tf in chosen:
            table.assert_tf_allowed(tf)
            out.append(self.get_tf(tf))
        return tuple(out)


def _make_engine(db_url: str | None) -> Engine:
    if not db_url or not db_url.strip():
        raise ValueError("db_url is required to load dim_timeframe specs.")
    return create_engine(db_url)


def load_time_specs(*, engine: Engine | None = None, db_url: str | None = None) -> TimeSpecStore:
    """
    Load TimeframeSpec rows from public.dim_timeframe and return a TimeSpecStore.

    Usage:
        store = load_time_specs(db_url=TARGET_DB_URL)
        tf_spec = store.get_tf("12M_CAL")
        table_spec = store.get_table("cmc_price_bars_multi_tf_cal_iso")
    """
    eng = engine or _make_engine(db_url)
    rows = []
    with eng.connect() as conn:
        rows = conn.execute(text(DIM_TIMEFRAME_SELECT_SQL)).mappings().all()

    tfs: Dict[str, TimeframeSpec] = {}
    for r in rows:
        tf = str(r["tf"])
        tfs[tf] = TimeframeSpec(
            tf=tf,
            calendar_scheme=r.get("calendar_scheme"),
            allow_partial_start=bool(r.get("allow_partial_start", False)),
            allow_partial_end=bool(r.get("allow_partial_end", False)),
            tf_days_min=r.get("tf_days_min"),
            tf_days_max=r.get("tf_days_max"),
        )

    return TimeSpecStore(timeframes=tfs)


# -----------------------------
# Convenience helpers
# -----------------------------


def require_specs_for_tfs(store: TimeSpecStore, tfs: Iterable[str]) -> None:
    """
    Hard-stop guard: ensure every tf exists in dim_timeframe.
    """
    missing = [tf for tf in tfs if tf not in store.timeframes]
    if missing:
        raise KeyError(
            "Missing dim_timeframe rows for: "
            + ", ".join(sorted(missing))
        )


def assert_table_tf_invariants(
    store: TimeSpecStore,
    table_name: str,
    tfs: Iterable[str],
) -> None:
    """
    Hard-stop guard: ensure tf list is valid for a given table spec.
    """
    table = store.get_table(table_name)
    for tf in tfs:
        table.assert_tf_allowed(tf)
        _ = store.get_tf(tf)  # also enforces presence in dim_timeframe
