# tests/test_bar_contract_gap_tests.py
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

import pandas as pd

# Prefer psycopg (v3); fall back to psycopg2
try:
    import psycopg  # type: ignore

    PSYCOPG3 = True
except Exception:
    psycopg = None
    PSYCOPG3 = False

try:
    import psycopg2  # type: ignore

    PSYCOPG2 = True
except Exception:
    psycopg2 = None
    PSYCOPG2 = False


# Contract module (the “source of truth” for these tests)
from ta_lab2.scripts.bars.common_snapshot_contract import (
    assert_one_row_per_local_day,
    can_carry_forward,
    CarryForwardInputs,
    apply_carry_forward,
    compute_missing_days_diagnostics,
    normalize_output_schema,
    enforce_ohlc_sanity,
)

# --------------------------------------------------------------------------------------
# Config (match existing DB test conventions)
# --------------------------------------------------------------------------------------


def _normalize_db_url(url: str) -> str:
    if not url:
        return url
    replacements = (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+psycopg3://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
        "postgres+psycopg3://",
    )
    for prefix in replacements:
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


DB_URL = os.environ.get("TARGET_DB_URL") or os.environ.get("TA_LAB2_DB_URL") or ""
if not DB_URL:
    pytest.skip(
        "DB tests skipped: set TARGET_DB_URL (or TA_LAB2_DB_URL) to run.",
        allow_module_level=True,
    )

DB_URL = _normalize_db_url(DB_URL)

MODE = (
    (
        os.environ.get("TA_LAB2_BAR_TEST_MODE")
        or os.environ.get("BARS_TEST_MODE")
        or "sample"
    )
    .strip()
    .lower()
)
assert MODE in {"sample", "full"}, "TA_LAB2_BAR_TEST_MODE must be 'sample' or 'full'"

# Sampling knobs
MAX_IDS = int(os.environ.get("TA_LAB2_BAR_TEST_MAX_IDS", "25"))
MAX_TFS_PER_TABLE = int(os.environ.get("TA_LAB2_BAR_TEST_MAX_TFS_PER_TABLE", "12"))
MAX_ROWS_SCAN = int(os.environ.get("TA_LAB2_BAR_TEST_MAX_ROWS_SCAN", "50000"))

DEFAULT_TZ = os.environ.get("TA_LAB2_BAR_TEST_TZ", "America/New_York")

BAR_TABLES = [
    "public.cmc_price_bars_1d",
    "public.cmc_price_bars_multi_tf_cal_us",
    "public.cmc_price_bars_multi_tf_cal_iso",
    "public.cmc_price_bars_multi_tf_cal_anchor_us",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso",
    "public.cmc_price_bars_multi_tf",
]

STATE_TABLES = [
    # 1d is special (different schema)
    "public.cmc_price_bars_1d_state",
    # contract-based state tables
    "public.cmc_price_bars_multi_tf_cal_us_state",
    "public.cmc_price_bars_multi_tf_cal_iso_state",
    "public.cmc_price_bars_multi_tf_cal_anchor_us_state",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso_state",
    "public.cmc_price_bars_multi_tf_state",
]


# --------------------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------------------


def _connect():
    if PSYCOPG3:
        return psycopg.connect(DB_URL, autocommit=True)
    if PSYCOPG2:
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        return conn
    raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")


def _fetchall(
    conn, sql: str, params: Optional[Sequence[Any]] = None
) -> List[Tuple[Any, ...]]:
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _has_table(conn, table: str) -> bool:
    schema, name = table.split(".", 1) if "." in table else ("public", table)
    rows = _fetchall(
        conn,
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        LIMIT 1
        """,
        [schema, name],
    )
    return bool(rows)


def _list_columns(conn, table: str) -> List[str]:
    schema, name = table.split(".", 1) if "." in table else ("public", table)
    rows = _fetchall(
        conn,
        """
        SELECT lower(column_name)
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        [schema, name],
    )
    return [r[0] for r in rows]


def _sample_ids(conn, table: str) -> List[int]:
    # Keep it simple and fast: distinct ids limited
    sql = f"SELECT DISTINCT id FROM {table} ORDER BY id LIMIT %s;"
    return [int(r[0]) for r in _fetchall(conn, sql, [MAX_IDS])]


def _sample_tfs(conn, table: str) -> List[str]:
    sql = f"SELECT DISTINCT tf FROM {table} ORDER BY tf LIMIT %s;"
    return [str(r[0]) for r in _fetchall(conn, sql, [MAX_TFS_PER_TABLE])]


# --------------------------------------------------------------------------------------
# 1) Schema normalization / required columns (DB-level)
# --------------------------------------------------------------------------------------

# “Core” bar columns that should exist on *all* bar tables.
# (1d is allowed to be smaller, but should still have these)
REQUIRED_BAR_CORE_COLS = {
    "id",
    "tf",
    "bar_seq",
    "time_open",
    "time_close",
    "time_high",
    "time_low",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "market_cap",
    "is_partial_start",
    "is_partial_end",
    "is_missing_days",
}

# Columns that your snapshot contract normalizer defines (but some tables may omit physically, esp 1d).
# For contract-built snapshot tables (all except 1d), we enforce these too.
REQUIRED_SNAPSHOT_CONTRACT_COLS = {
    "timestamp",
    "last_ts_half_open",
    "pos_in_bar",
    "count_days_remaining",
    "count_days",
    "tf_days",
    "count_missing_days",
    "count_missing_days_start",
    "count_missing_days_end",
    "count_missing_days_interior",
    "missing_days_where",
    "first_missing_day",
    "last_missing_day",
}


@pytest.mark.parametrize("bar_table", BAR_TABLES)
def test_bar_tables_exist_and_have_core_columns(bar_table: str) -> None:
    with _connect() as conn:
        assert _has_table(conn, bar_table), f"Missing bar table: {bar_table}"
        cols = set(_list_columns(conn, bar_table))
        missing = sorted(REQUIRED_BAR_CORE_COLS - cols)
        assert not missing, f"{bar_table} missing required core columns: {missing}"


@pytest.mark.parametrize(
    "bar_table", [t for t in BAR_TABLES if t != "public.cmc_price_bars_1d"]
)
def test_snapshot_tables_have_contract_columns(bar_table: str) -> None:
    """
    Enforce that the snapshot-style bar tables physically store the contract bookkeeping fields.
    (This aligns with the contract REQUIRED_COL_DEFAULTS + upsert_bars filtering.)
    """
    with _connect() as conn:
        cols = set(_list_columns(conn, bar_table))
        missing = sorted(REQUIRED_SNAPSHOT_CONTRACT_COLS - cols)
        assert not missing, f"{bar_table} missing snapshot-contract columns: {missing}"


# --------------------------------------------------------------------------------------
# 2) Contract invariants (DB-level): time_low <= time_close, and OHLC clamps
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bar_table", BAR_TABLES)
def test_no_bad_time_low_after_time_close(bar_table: str) -> None:
    """
    Your contract enforces the explicit bad-timelow fix in enforce_ohlc_sanity.
    This test asserts the DB table has no surviving violations.
    """
    with _connect() as conn:
        sql = f"""
        SELECT COUNT(*)
        FROM {bar_table}
        WHERE time_low IS NOT NULL
          AND time_close IS NOT NULL
          AND time_low > time_close;
        """
        n = int(_fetchall(conn, sql)[0][0])
        assert n == 0, f"{bar_table} has {n} rows with time_low > time_close"


@pytest.mark.parametrize("bar_table", BAR_TABLES)
def test_ohlc_bounds_hold_in_db(bar_table: str) -> None:
    """
    Enforce high >= max(open, close) and low <= min(open, close) for stored bars.
    (Your writers clamp these in enforce_ohlc_sanity.)
    """
    with _connect() as conn:
        sql_hi = f"""
        SELECT COUNT(*)
        FROM {bar_table}
        WHERE high IS NOT NULL
          AND open IS NOT NULL
          AND close IS NOT NULL
          AND high < GREATEST(open, close);
        """
        sql_lo = f"""
        SELECT COUNT(*)
        FROM {bar_table}
        WHERE low IS NOT NULL
          AND open IS NOT NULL
          AND close IS NOT NULL
          AND low > LEAST(open, close);
        """
        n_hi = int(_fetchall(conn, sql_hi)[0][0])
        n_lo = int(_fetchall(conn, sql_lo)[0][0])
        assert n_hi == 0, f"{bar_table} has {n_hi} rows with high < max(open, close)"
        assert n_lo == 0, f"{bar_table} has {n_lo} rows with low > min(open, close)"


# --------------------------------------------------------------------------------------
# 3) Missing-days diagnostics consistency (DB-level)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bar_table", [t for t in BAR_TABLES if t != "public.cmc_price_bars_1d"]
)
def test_missing_days_columns_are_self_consistent(bar_table: str) -> None:
    """
    If is_missing_days is true, count_missing_days should be >= 1.
    And first_missing_day/last_missing_day should be ordered when present.
    """
    with _connect() as conn:
        sql = f"""
        SELECT
          SUM(CASE WHEN is_missing_days AND (count_missing_days IS NULL OR count_missing_days < 1) THEN 1 ELSE 0 END) AS bad_count,
          SUM(CASE WHEN first_missing_day IS NOT NULL AND last_missing_day IS NOT NULL AND first_missing_day > last_missing_day THEN 1 ELSE 0 END) AS bad_order
        FROM {bar_table};
        """
        bad_count, bad_order = _fetchall(conn, sql)[0]
        bad_count = int(bad_count or 0)
        bad_order = int(bad_order or 0)
        assert (
            bad_count == 0
        ), f"{bar_table} has rows with is_missing_days=TRUE but count_missing_days < 1"
        assert (
            bad_order == 0
        ), f"{bar_table} has rows with first_missing_day > last_missing_day"


# --------------------------------------------------------------------------------------
# 4) State table shape + basic sanity (DB-level)
# --------------------------------------------------------------------------------------

REQUIRED_CONTRACT_STATE_COLS = {
    "id",
    "tf",
    "daily_min_seen",
    "daily_max_seen",
    "last_bar_seq",
    "last_time_close",
    "updated_at",
}

REQUIRED_1D_STATE_COLS = {
    "id",
    "last_src_ts",
    "last_run_ts",
    "last_upserted",
    "last_repaired_timehigh",
    "last_repaired_timelow",
    "last_rejected",
}


@pytest.mark.parametrize("state_table", STATE_TABLES)
def test_state_tables_exist_and_have_expected_columns(state_table: str) -> None:
    with _connect() as conn:
        if not _has_table(conn, state_table):
            pytest.skip(f"State table not present: {state_table}")

        cols = set(_list_columns(conn, state_table))

        if state_table.endswith("_1d_state"):
            missing = sorted(REQUIRED_1D_STATE_COLS - cols)
            assert (
                not missing
            ), f"{state_table} missing required 1d state columns: {missing}"
        else:
            missing = sorted(REQUIRED_CONTRACT_STATE_COLS - cols)
            assert (
                not missing
            ), f"{state_table} missing required contract state columns: {missing}"


@pytest.mark.parametrize(
    "state_table", [t for t in STATE_TABLES if not t.endswith("_1d_state")]
)
def test_state_table_basic_sanity(state_table: str) -> None:
    """
    For contract state tables:
    - daily_min_seen <= daily_max_seen when both present
    - last_bar_seq and last_time_close should move together (both NULL or both NOT NULL) in steady-state
    """
    with _connect() as conn:
        if not _has_table(conn, state_table):
            pytest.skip(f"State table not present: {state_table}")

        sql = f"""
        SELECT
          SUM(CASE WHEN daily_min_seen IS NOT NULL AND daily_max_seen IS NOT NULL AND daily_min_seen > daily_max_seen THEN 1 ELSE 0 END) AS bad_range,
          SUM(CASE WHEN (last_bar_seq IS NULL) <> (last_time_close IS NULL) THEN 1 ELSE 0 END) AS bad_pair
        FROM {state_table};
        """
        bad_range, bad_pair = _fetchall(conn, sql)[0]
        assert (
            int(bad_range or 0) == 0
        ), f"{state_table}: daily_min_seen > daily_max_seen"
        assert (
            int(bad_pair or 0) == 0
        ), f"{state_table}: last_bar_seq and last_time_close nullability mismatch"


# --------------------------------------------------------------------------------------
# 5) Pure contract unit tests (no DB): assert_one_row_per_local_day, missing-days, carry-forward, ohlc sanity
# --------------------------------------------------------------------------------------


def test_assert_one_row_per_local_day_detects_duplicate_local_day() -> None:
    """
    Build two UTC timestamps that both fall on the *same* America/New_York local day.
    This must raise per contract invariant.
    """
    # Jan 2 01:00 UTC == Jan 1 20:00 NY (prev day)
    # Jan 2 05:00 UTC == Jan 2 00:00 NY (same local day as Jan 1? depends on DST; pick safer)
    # Use a simple pair that is definitely same NY date:
    # 2025-01-02 05:00 UTC => 2025-01-02 00:00 NY
    # 2025-01-02 23:00 UTC => 2025-01-02 18:00 NY  (same local date)
    df = pd.DataFrame(
        {
            "id": [1, 1],
            "ts": [
                pd.Timestamp("2025-01-02T05:00:00Z"),
                pd.Timestamp("2025-01-02T23:00:00Z"),
            ],
        }
    )
    with pytest.raises(ValueError):
        assert_one_row_per_local_day(df, ts_col="ts", tz=DEFAULT_TZ, id_col="id")


def test_compute_missing_days_diagnostics_interior_gap() -> None:
    """
    Expected [Jan1..Jan5], observed missing Jan3 => interior missing-days.
    """
    d0 = date(2025, 1, 1)
    d4 = date(2025, 1, 5)
    observed = [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 4), date(2025, 1, 5)]
    diag = compute_missing_days_diagnostics(
        bar_start_day_local=d0, snapshot_day_local=d4, observed_days_local=observed
    )
    assert diag["is_missing_days"] is True
    assert int(diag["count_days"]) == 5
    assert int(diag["count_missing_days"]) == 1
    assert pd.to_datetime(diag["first_missing_day"], utc=True).date() == date(
        2025, 1, 3
    )
    assert pd.to_datetime(diag["last_missing_day"], utc=True).date() == date(2025, 1, 3)


def test_can_carry_forward_gate() -> None:
    """
    Verify strict gate from contract:
    - last_snapshot_day_local == yesterday
    - snapshot_day_local == today
    - same_bar_identity and missing_days_tail_ok both True
    """
    today = date(2025, 1, 10)
    inp_ok = CarryForwardInputs(
        last_snapshot_day_local=today - timedelta(days=1),
        today_local=today,
        snapshot_day_local=today,
        same_bar_identity=True,
        missing_days_tail_ok=True,
    )
    assert can_carry_forward(inp_ok) is True

    inp_bad = CarryForwardInputs(
        last_snapshot_day_local=today - timedelta(days=2),
        today_local=today,
        snapshot_day_local=today,
        same_bar_identity=True,
        missing_days_tail_ok=True,
    )
    assert can_carry_forward(inp_bad) is False


def test_apply_carry_forward_mechanics_and_schema_normalization() -> None:
    """
    apply_carry_forward should:
    - copy prior snapshot
    - overwrite close/time_close/etc from new daily
    - call update_window_fields hook
    - normalize required schema (at least adds contract defaults if missing)
    """
    prior = {
        "id": 1,
        "tf": "7D",
        "bar_seq": 10,
        "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
        "time_close": pd.Timestamp("2025-01-09T00:00:00Z"),
        "time_high": pd.Timestamp("2025-01-05T00:00:00Z"),
        "time_low": pd.Timestamp("2025-01-02T00:00:00Z"),
        "open": 100.0,
        "high": 140.0,
        "low": 90.0,
        "close": 120.0,
        "volume": 1000.0,
        "market_cap": 1_000_000.0,
        "timestamp": pd.Timestamp("2025-01-09T00:00:00Z"),
        "last_ts_half_open": pd.Timestamp("2025-01-08T00:00:00Z"),
        "pos_in_bar": 6,
        "is_partial_start": False,
        "is_partial_end": True,
        "count_days_remaining": 1,
        "is_missing_days": False,
        "count_days": 6,
        "count_missing_days": 0,
    }
    new_daily = {
        "time_close": pd.Timestamp("2025-01-10T00:00:00Z"),
        "close": 130.0,
        "volume": 1200.0,
        "market_cap": 1_050_000.0,
        "timestamp": pd.Timestamp("2025-01-10T00:00:00Z"),
        "last_ts_half_open": pd.Timestamp("2025-01-09T12:00:00Z"),
        "pos_in_bar": 7,
        "is_partial_end": False,
        "count_days_remaining": 0,
        # pretend today's daily high pushes the window high up
        "high": 150.0,
        "low": 95.0,
        "timehigh": pd.Timestamp("2025-01-10T00:00:00Z"),
        "timelow": pd.Timestamp("2025-01-10T00:00:00Z"),
    }

    def update_window_fields(out: Dict[str, Any], daily: Dict[str, Any]) -> None:
        # Example semantics-neutral hook: expand high/low if today's daily extends it
        if "high" in daily and daily["high"] is not None:
            out["high"] = max(float(out["high"]), float(daily["high"]))
            out["time_high"] = daily.get("timehigh", out.get("time_high"))
        if "low" in daily and daily["low"] is not None:
            out["low"] = min(float(out["low"]), float(daily["low"]))
            out["time_low"] = daily.get("timelow", out.get("time_low"))

    out = apply_carry_forward(
        prior, new_daily_row=new_daily, update_window_fields=update_window_fields
    )

    assert out["close"] == 130.0
    assert pd.to_datetime(out["time_close"], utc=True) == pd.Timestamp(
        "2025-01-10T00:00:00Z"
    )
    assert out["high"] == 150.0
    assert out["low"] == 90.0  # unchanged (since 95 > 90)
    # Normalization: these must exist even if absent on prior/new
    for must in (
        "is_missing_days",
        "count_missing_days",
        "first_missing_day",
        "last_missing_day",
    ):
        assert must in out


def test_enforce_ohlc_sanity_fixes_bad_timelow_and_clamps_bounds() -> None:
    """
    Direct unit test of enforce_ohlc_sanity:
    - if time_low > time_close, fix time_low and low
    - clamp high/low relative to open/close
    """
    df = pd.DataFrame(
        [
            {
                "open": 100.0,
                "close": 110.0,
                "high": 105.0,  # violates (should be >= 110)
                "low": 120.0,  # violates (should be <= 100)
                "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
                "time_close": pd.Timestamp("2025-01-02T00:00:00Z"),
                "time_low": pd.Timestamp(
                    "2025-01-03T00:00:00Z"
                ),  # bad: after time_close
            }
        ]
    )
    out = enforce_ohlc_sanity(df)
    r = out.iloc[0].to_dict()

    assert r["high"] == 110.0
    assert r["low"] == 100.0
    # With open<=close, time_low should be time_open after the bad-timelow fix + clamp
    assert pd.to_datetime(r["time_low"], utc=True) == pd.Timestamp(
        "2025-01-01T00:00:00Z"
    )


def test_normalize_output_schema_adds_missing_required_columns() -> None:
    df = pd.DataFrame([{"id": 1, "tf": "7D", "bar_seq": 1, "open": 1.0, "close": 1.0}])
    out = normalize_output_schema(df)
    # A few representative required columns
    for col in (
        "time_open",
        "time_close",
        "is_partial_end",
        "is_missing_days",
        "count_missing_days",
        "timestamp",
    ):
        assert col in out.columns
