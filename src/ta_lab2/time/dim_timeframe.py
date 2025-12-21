from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Iterable, Tuple

import pandas as pd
from sqlalchemy import create_engine


@dataclass(frozen=True)
class TFMeta:
    tf: str
    label: str
    base_unit: str
    tf_qty: int
    tf_days_nominal: int
    alignment_type: str
    calendar_anchor: Optional[str]
    roll_policy: str
    has_roll_flag: bool
    is_intraday: bool
    sort_order: int
    is_canonical: bool

    # New (optional) metadata for calendar schemes and variable/partial windows
    calendar_scheme: Optional[str] = None
    allow_partial_start: bool = False
    allow_partial_end: bool = False
    tf_days_min: Optional[int] = None
    tf_days_max: Optional[int] = None


class DimTimeframe:
    """
    In-memory view of dim_timeframe with some convenience accessors.

    This is intended to be loaded once per process and then reused via
    the _DIM_CACHE / _get_dim helpers below.

    Notes on "new" fields:
      - calendar_scheme: e.g. 'US', 'ISO', 'CAL' (your convention)
      - allow_partial_start/end: whether partial periods are allowed at dataset edges
      - tf_days_min/max: expected realized-day bounds for a TF in bar tables
    """

    def __init__(self, meta: Dict[str, TFMeta]) -> None:
        # keyed by tf, e.g. "1D", "6M_CAL", etc.
        self._meta: Dict[str, TFMeta] = meta

    @classmethod
    def from_db(cls, db_url: str) -> DimTimeframe:
        """
        Load dim_timeframe from the given db_url and build a DimTimeframe.

        We intentionally pull only the columns we care about, in a stable
        order, so the Python side is insulated from extra columns.

        This query includes the newer columns (calendar_scheme, allow_partial_*,
        tf_days_min/max). If they exist but contain NULLs, we handle that.
        """
        engine = create_engine(db_url)

        query = """
            SELECT
                tf,
                label,
                base_unit,
                tf_qty,
                tf_days_nominal,
                alignment_type,
                calendar_anchor,
                roll_policy,
                has_roll_flag,
                is_intraday,
                sort_order,
                is_canonical,

                -- Newer columns (may be NULL depending on migration state)
                calendar_scheme,
                allow_partial_start,
                allow_partial_end,
                tf_days_min,
                tf_days_max
            FROM dim_timeframe
        """

        df = pd.read_sql(query, engine)

        meta: Dict[str, TFMeta] = {}

        def _to_int_opt(x) -> Optional[int]:
            if x is None or (isinstance(x, float) and pd.isna(x)) or pd.isna(x):
                return None
            return int(x)

        def _to_str_opt(x) -> Optional[str]:
            if x is None or pd.isna(x):
                return None
            s = str(x)
            return s if s != "" else None

        def _to_bool(x, default: bool = False) -> bool:
            if x is None or pd.isna(x):
                return default
            return bool(x)

        for _, row in df.iterrows():
            m = TFMeta(
                tf=row["tf"],
                label=row["label"],
                base_unit=row["base_unit"],
                tf_qty=int(row["tf_qty"]),
                tf_days_nominal=int(row["tf_days_nominal"]),
                alignment_type=row["alignment_type"],
                calendar_anchor=_to_str_opt(row.get("calendar_anchor")),
                roll_policy=row["roll_policy"],
                has_roll_flag=bool(row["has_roll_flag"]),
                is_intraday=bool(row["is_intraday"]),
                sort_order=int(row["sort_order"]),
                is_canonical=bool(row["is_canonical"]),

                # New fields
                calendar_scheme=_to_str_opt(row.get("calendar_scheme")),
                allow_partial_start=_to_bool(row.get("allow_partial_start"), default=False),
                allow_partial_end=_to_bool(row.get("allow_partial_end"), default=False),
                tf_days_min=_to_int_opt(row.get("tf_days_min")),
                tf_days_max=_to_int_opt(row.get("tf_days_max")),
            )
            meta[m.tf] = m

        return cls(meta)

    # --- core accessors on the in-memory map ---

    def tf_days(self, tf: str) -> int:
        """
        Return the nominal number of days for a timeframe (tf_days_nominal).
        """
        try:
            return self._meta[tf].tf_days_nominal
        except KeyError:
            raise KeyError(f"Unknown timeframe tf={tf!r} in DimTimeframe")

    def alignment(self, tf: str) -> str:
        """
        Return the alignment_type for a timeframe, e.g. 'tf_day' or 'calendar'.
        """
        try:
            return self._meta[tf].alignment_type
        except KeyError:
            raise KeyError(f"Unknown timeframe tf={tf!r} in DimTimeframe")

    def calendar_anchor(self, tf: str) -> Optional[str]:
        """
        Return the calendar_anchor for a timeframe, e.g. 'EOM', 'EOQ', 'EOY', 'ISO-WEEK'.
        """
        try:
            return self._meta[tf].calendar_anchor
        except KeyError:
            raise KeyError(f"Unknown timeframe tf={tf!r} in DimTimeframe")

    def list_tfs(
        self,
        alignment_type: Optional[str] = None,
        canonical_only: bool = False,
    ) -> Iterable[str]:
        """
        List timeframes, optionally filtered by alignment_type and/or is_canonical.

        alignment_type:
            - None: no filter
            - 'tf_day' or 'calendar': filter to that alignment_type

        canonical_only:
            - False: include all
            - True: only rows where is_canonical = True
        """
        values = list(self._meta.values())

        if alignment_type is not None:
            values = [m for m in values if m.alignment_type == alignment_type]

        if canonical_only:
            values = [m for m in values if m.is_canonical]

        # sort by sort_order, then tf for deterministic ordering
        values.sort(key=lambda m: (m.sort_order, m.tf))
        return [m.tf for m in values]

    # --- NEW accessors (do not change any existing semantics above) ---

    def calendar_scheme(self, tf: str) -> Optional[str]:
        """
        Return calendar_scheme, e.g. 'US', 'ISO', 'CAL' (depends on your convention).
        """
        try:
            return self._meta[tf].calendar_scheme
        except KeyError:
            raise KeyError(f"Unknown timeframe tf={tf!r} in DimTimeframe")

    def allows_partial(self, tf: str) -> Tuple[bool, bool]:
        """
        Return (allow_partial_start, allow_partial_end).
        """
        try:
            m = self._meta[tf]
            return (m.allow_partial_start, m.allow_partial_end)
        except KeyError:
            raise KeyError(f"Unknown timeframe tf={tf!r} in DimTimeframe")

    def tf_days_bounds(self, tf: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Return (tf_days_min, tf_days_max).

        If these are NULL in the table, callers will get (None, None) and can
        decide how to handle it (e.g., fallback to nominal).
        """
        try:
            m = self._meta[tf]
            return (m.tf_days_min, m.tf_days_max)
        except KeyError:
            raise KeyError(f"Unknown timeframe tf={tf!r} in DimTimeframe")

    def tf_days_bounds_or_nominal(self, tf: str) -> Tuple[int, int]:
        """
        Return (min_days, max_days), falling back to tf_days_nominal if NULL.

        This is useful for QA joins where you'd prefer a deterministic bound even
        if you haven't populated tf_days_min/max yet.
        """
        m = self._meta.get(tf)
        if m is None:
            raise KeyError(f"Unknown timeframe tf={tf!r} in DimTimeframe")

        lo = m.tf_days_min if m.tf_days_min is not None else m.tf_days_nominal
        hi = m.tf_days_max if m.tf_days_max is not None else m.tf_days_nominal
        return (lo, hi)

    def realized_tf_days_ok(self, tf: str, tf_days: int) -> bool:
        """
        Check whether a realized tf_days value (from bar tables) is within bounds.

        - If bounds are NULL, this falls back to tf_days_nominal exact match.
        """
        lo, hi = self.tf_days_bounds_or_nominal(tf)
        return lo <= int(tf_days) <= hi


# --- module-level cache + simple helpers for scripts ---

_DIM_CACHE: DimTimeframe | None = None


def _get_dim(db_url: str) -> DimTimeframe:
    """
    Lazy-load and cache DimTimeframe for this process using db_url.
    """
    global _DIM_CACHE
    if _DIM_CACHE is None:
        _DIM_CACHE = DimTimeframe.from_db(db_url)
    return _DIM_CACHE


def get_tf_days(tf: str, db_url: str) -> int:
    """
    Convenience wrapper to get tf_days_nominal for a timeframe.
    """
    return _get_dim(db_url).tf_days(tf)


def get_alignment_type(tf: str, db_url: str) -> str:
    """
    Convenience wrapper to get alignment_type for a timeframe.
    """
    return _get_dim(db_url).alignment(tf)


def list_tfs(
    db_url: str,
    alignment_type: str | None = None,
    canonical_only: bool = True,
) -> list[str]:
    """
    Convenience wrapper to list timeframes in dim_timeframe, with filters.

    canonical_only defaults to True here because most EMA scripts
    care about the canonical set (the ones actually used in pipelines).
    """
    return list(
        _get_dim(db_url).list_tfs(
            alignment_type=alignment_type,
            canonical_only=canonical_only,
        )
    )


# --- NEW module-level helpers (additive; does not remove/alter old ones) ---

def get_tf_days_bounds(tf: str, db_url: str) -> tuple[Optional[int], Optional[int]]:
    """
    Convenience wrapper to get (tf_days_min, tf_days_max) for a timeframe.
    """
    return _get_dim(db_url).tf_days_bounds(tf)


def get_tf_days_bounds_or_nominal(tf: str, db_url: str) -> tuple[int, int]:
    """
    Convenience wrapper to get (min_days, max_days), falling back to nominal.
    """
    return _get_dim(db_url).tf_days_bounds_or_nominal(tf)


def allows_partial(tf: str, db_url: str) -> tuple[bool, bool]:
    """
    Convenience wrapper to get (allow_partial_start, allow_partial_end).
    """
    return _get_dim(db_url).allows_partial(tf)


def get_calendar_scheme(tf: str, db_url: str) -> Optional[str]:
    """
    Convenience wrapper to get calendar_scheme.
    """
    return _get_dim(db_url).calendar_scheme(tf)


def realized_tf_days_ok(tf: str, tf_days: int, db_url: str) -> bool:
    """
    Convenience wrapper to check realized tf_days is within bounds for tf.
    """
    return _get_dim(db_url).realized_tf_days_ok(tf=tf, tf_days=tf_days)
