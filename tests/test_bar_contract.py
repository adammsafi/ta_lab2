from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest
import pandas as pd

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


from ta_lab2.scripts.bars.common_snapshot_contract import (
    REQUIRED_COL_DEFAULTS,
    assert_one_row_per_local_day,
    compute_missing_days_diagnostics,
    normalize_output_schema,
    enforce_ohlc_sanity,
    can_carry_forward,
    CarryForwardInputs,
    ensure_state_table,
    load_state,
    upsert_state,
)


def _normalize_db_url(url: str) -> str:
    if not url:
        return url
    prefixes = (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+psycopg3://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
        "postgres+psycopg3://",
    )
    for p in prefixes:
        if url.startswith(p):
            return "postgresql://" + url[len(p) :]
    return url


DB_URL = os.environ.get("TARGET_DB_URL") or os.environ.get("TA_LAB2_DB_URL") or ""
if not DB_URL:
    pytest.skip(
        "DB tests skipped: set TARGET_DB_URL (or TA_LAB2_DB_URL).",
        allow_module_level=True,
    )
DB_URL = _normalize_db_url(DB_URL)

DEFAULT_TZ = os.environ.get("TA_LAB2_BAR_TEST_TZ", "America/New_York")

BAR_TABLES = [
    "public.cmc_price_bars_1d",
    "public.cmc_price_bars_multi_tf",
    "public.cmc_price_bars_multi_tf_cal_us",
    "public.cmc_price_bars_multi_tf_cal_iso",
    "public.cmc_price_bars_multi_tf_cal_anchor_us",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso",
]

STATE_TABLES = [
    "public.cmc_price_bars_1d_state",
    "public.cmc_price_bars_multi_tf_state",
    "public.cmc_price_bars_multi_tf_cal_us_state",
    "public.cmc_price_bars_multi_tf_cal_iso_state",
    "public.cmc_price_bars_multi_tf_cal_anchor_us_state",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso_state",
]


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


def _exec(conn, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    """Execute SQL without fetching results (for DDL/DML)."""
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        return
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()


def _has_table(conn, table: str) -> bool:
    schema, name = table.split(".", 1)
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
    schema, name = table.split(".", 1)
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


def _get_unique_constraints_cols(conn, schema: str, table: str) -> List[List[str]]:
    rows = _fetchall(
        conn,
        """
        SELECT tc.constraint_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = %s
          AND tc.table_name = %s
          AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
        ORDER BY tc.constraint_name, kcu.ordinal_position
        """,
        [schema, table],
    )
    by_name: Dict[str, List[str]] = {}
    for cname, col in rows:
        by_name.setdefault(str(cname), []).append(str(col).lower())
    return list(by_name.values())


def _get_unique_indexes_cols(conn, schema: str, table: str) -> List[List[str]]:
    rows = _fetchall(
        conn,
        """
        SELECT i.relname, a.attname, x.n
        FROM pg_class t
        JOIN pg_namespace ns ON ns.oid = t.relnamespace
        JOIN pg_index ix ON ix.indrelid = t.oid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS x(attnum, n) ON true
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.attnum
        WHERE ns.nspname = %s
          AND t.relname = %s
          AND ix.indisunique = true
        ORDER BY i.relname, x.n
        """,
        [schema, table],
    )
    by_idx: Dict[str, List[str]] = {}
    for idx, col, _pos in rows:
        by_idx.setdefault(str(idx), []).append(str(col).lower())
    return list(by_idx.values())


# -------------------- expectations --------------------

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

REQUIRED_SNAPSHOT_COLS = {
    "timestamp",
    "last_ts_half_open",
    "pos_in_bar",
    "count_days_remaining",
    "count_days",
    "count_missing_days",
    "first_missing_day",
    "last_missing_day",
}

REQUIRED_CONTRACT_STATE_COLS_BASE = {
    "id",
    "tf",
    "daily_min_seen",
    "daily_max_seen",
    "last_bar_seq",
    "last_time_close",
    "updated_at",
}

REQUIRED_CONTRACT_STATE_HAS_TZ = {
    # all contract state tables in your DB have tz (including multi_tf_state)
    "tz"
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


@pytest.mark.parametrize("bar_table", BAR_TABLES)
def test_bar_tables_exist_and_have_required_columns(bar_table: str) -> None:
    with _connect() as conn:
        assert _has_table(conn, bar_table), f"Missing bar table: {bar_table}"
        cols = set(_list_columns(conn, bar_table))

        missing = sorted(REQUIRED_BAR_CORE_COLS - cols)
        assert not missing, (
            f"{bar_table} is missing required columns: {missing}\n"
            f"Fix: migrate the table schema or update bar upsert logic to include these columns."
        )

        if bar_table != "public.cmc_price_bars_1d":
            missing2 = sorted(REQUIRED_SNAPSHOT_COLS - cols)
            assert not missing2, (
                f"{bar_table} is missing snapshot bookkeeping columns: {missing2}\n"
                f"Fix: align schema with snapshot contract (REQUIRED_COL_DEFAULTS / normalize_output_schema)."
            )


@pytest.mark.parametrize("state_table", STATE_TABLES)
def test_state_tables_exist_and_have_expected_columns(state_table: str) -> None:
    with _connect() as conn:
        assert _has_table(conn, state_table), f"Missing state table: {state_table}"
        cols = set(_list_columns(conn, state_table))

        if state_table.endswith("_1d_state"):
            missing = sorted(REQUIRED_1D_STATE_COLS - cols)
            assert not missing, (
                f"{state_table} missing expected 1d state columns: {missing}\n"
                f"Fix: update schema or adjust expectations to match your 1d state design."
            )
        else:
            missing = sorted(
                (REQUIRED_CONTRACT_STATE_COLS_BASE | REQUIRED_CONTRACT_STATE_HAS_TZ)
                - cols
            )
            assert not missing, (
                f"{state_table} missing expected contract state columns: {missing}\n"
                f"Fix: migrate schema to match ensure_state_table(with_tz=True)."
            )


@pytest.mark.parametrize(
    "state_table", [t for t in STATE_TABLES if not t.endswith("_1d_state")]
)
def test_state_unique_key_supports_upsert_conflict_target(state_table: str) -> None:
    """
    upsert_state() uses ON CONFLICT (id, tf). That requires a UNIQUE/PK on (id, tf).
    """
    schema, name = state_table.split(".", 1)
    with _connect() as conn:
        uniq_all = _get_unique_constraints_cols(
            conn, schema, name
        ) + _get_unique_indexes_cols(conn, schema, name)

        ok = any(u == ["id", "tf"] for u in uniq_all)

        assert ok, (
            f"{state_table} does not have a UNIQUE/PK exactly on (id, tf).\n"
            f"Unique keys/indexes found: {uniq_all}\n"
            f"Fix A: add UNIQUE(id, tf) (recommended; matches current upsert_state()).\n"
            f"Fix B: if you want tz-scoped uniqueness, change upsert_state() to ON CONFLICT (id, tf, tz)\n"
            f"and add UNIQUE(id, tf, tz)."
        )


# -------------------- contract unit tests --------------------


def test_contract_assert_one_row_per_local_day_rejects_duplicate_local_day() -> None:
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


def test_missing_days_diagnostics_edge_and_interior_cases() -> None:
    # no missing
    d0, d4 = date(2025, 1, 1), date(2025, 1, 5)
    diag = compute_missing_days_diagnostics(
        d0,
        d4,
        [
            date(2025, 1, 1),
            date(2025, 1, 2),
            date(2025, 1, 3),
            date(2025, 1, 4),
            date(2025, 1, 5),
        ],
    )
    assert diag["is_missing_days"] is False

    # interior missing (missing Jan 3)
    diag = compute_missing_days_diagnostics(
        d0, d4, [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 4), date(2025, 1, 5)]
    )
    assert diag["is_missing_days"] is True
    assert int(diag["count_missing_days"]) == 1

    # edge missing at start (missing Jan 1)
    diag = compute_missing_days_diagnostics(
        d0, d4, [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5)]
    )
    assert diag["is_missing_days"] is True
    assert int(diag["count_missing_days"]) == 1

    # edge missing at end (missing Jan 5)
    diag = compute_missing_days_diagnostics(
        d0, d4, [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4)]
    )
    assert diag["is_missing_days"] is True
    assert int(diag["count_missing_days"]) == 1


def test_normalize_output_schema_adds_required_defaults() -> None:
    df = pd.DataFrame([{"id": 1, "tf": "7D", "bar_seq": 1, "open": 1.0, "close": 1.0}])
    out = normalize_output_schema(df)

    # representative required columns
    must = [
        "time_open",
        "time_close",
        "is_partial_start",
        "is_partial_end",
        "is_missing_days",
        "count_missing_days",
    ]
    missing = [c for c in must if c not in out.columns]
    assert (
        not missing
    ), f"normalize_output_schema did not add required columns: {missing}"

    # verify defaults for newly created cols
    for col, default in REQUIRED_COL_DEFAULTS.items():
        if col in out.columns and col not in df.columns:
            v = out.iloc[0][col]
            if default is None:
                assert v is None or pd.isna(v)
            else:
                assert v == default


def test_enforce_ohlc_sanity_clamps_and_fixes_bad_timelow() -> None:
    df = pd.DataFrame(
        [
            {
                "open": 100.0,
                "close": 110.0,
                "high": 105.0,
                "low": 120.0,
                "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
                "time_close": pd.Timestamp("2025-01-02T00:00:00Z"),
                "time_low": pd.Timestamp("2025-01-03T00:00:00Z"),
            }
        ]
    )
    out = enforce_ohlc_sanity(df).iloc[0]
    assert out["high"] == 110.0
    assert out["low"] == 100.0
    assert pd.to_datetime(out["time_low"], utc=True) == pd.Timestamp(
        "2025-01-01T00:00:00Z"
    )


def test_can_carry_forward_gate_rules() -> None:
    today = date(2025, 1, 10)
    ok = CarryForwardInputs(
        last_snapshot_day_local=date(2025, 1, 9),
        today_local=today,
        snapshot_day_local=today,
        same_bar_identity=True,
        missing_days_tail_ok=True,
    )
    assert can_carry_forward(ok) is True

    bad = CarryForwardInputs(
        last_snapshot_day_local=date(2025, 1, 8),
        today_local=today,
        snapshot_day_local=today,
        same_bar_identity=True,
        missing_days_tail_ok=True,
    )
    assert can_carry_forward(bad) is False


def test_state_upsert_and_load_with_tz_parameter() -> None:
    """
    Test actual state upsert/load operations with tz parameter.
    Verifies that:
    - ensure_state_table creates table with tz column when with_tz=True
    - upsert_state correctly inserts/updates state rows with tz
    - load_state returns tz column and preserves values
    - Conflict on (id, tf) works correctly (not on tz)
    """
    test_state_table = "public.test_state_upsert_tz"

    # Cleanup first (in case of prior test failures)
    with _connect() as conn:
        _fetchall(conn, f"DROP TABLE IF EXISTS {test_state_table}")

    try:
        # Create state table with tz column
        ensure_state_table(DB_URL, test_state_table, with_tz=True)

        # Verify tz column exists
        with _connect() as conn:
            cols = set(_list_columns(conn, test_state_table))
            assert "tz" in cols, "State table should have tz column when with_tz=True"

        # Insert initial state for id=1, tf=7D, tz=America/New_York
        initial_state = pd.DataFrame(
            [
                {
                    "id": 1,
                    "tf": "7D",
                    "tz": "America/New_York",
                    "daily_min_seen": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "daily_max_seen": pd.Timestamp("2025-01-05T00:00:00Z"),
                    "last_bar_seq": 10,
                    "last_time_close": pd.Timestamp("2025-01-05T23:59:59Z"),
                }
            ]
        )

        upsert_state(DB_URL, test_state_table, initial_state, with_tz=True)

        # Load state back and verify tz preserved
        loaded = load_state(DB_URL, test_state_table, ids=[1], with_tz=True)
        assert not loaded.empty, "Should load the upserted state"
        assert len(loaded) == 1, "Should have exactly one row"

        row = loaded.iloc[0]
        assert row["id"] == 1
        assert row["tf"] == "7D"
        assert row["tz"] == "America/New_York", "tz should be preserved"
        assert row["last_bar_seq"] == 10
        assert pd.to_datetime(row["daily_min_seen"], utc=True) == pd.Timestamp(
            "2025-01-01T00:00:00Z"
        )

        # Update state (upsert with same id, tf, different tz value)
        # This tests that conflict target is (id, tf) only, not (id, tf, tz)
        updated_state = pd.DataFrame(
            [
                {
                    "id": 1,
                    "tf": "7D",
                    "tz": "UTC",  # Changed tz
                    "daily_min_seen": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "daily_max_seen": pd.Timestamp("2025-01-10T00:00:00Z"),  # Updated
                    "last_bar_seq": 15,  # Updated
                    "last_time_close": pd.Timestamp("2025-01-10T23:59:59Z"),
                }
            ]
        )

        upsert_state(DB_URL, test_state_table, updated_state, with_tz=True)

        # Load and verify update occurred (should be 1 row, not 2)
        loaded2 = load_state(DB_URL, test_state_table, ids=[1], with_tz=True)
        assert (
            len(loaded2) == 1
        ), "Should still have exactly one row (upsert, not insert)"

        row2 = loaded2.iloc[0]
        assert row2["tz"] == "UTC", "tz should be updated"
        assert row2["last_bar_seq"] == 15, "last_bar_seq should be updated"
        assert pd.to_datetime(row2["daily_max_seen"], utc=True) == pd.Timestamp(
            "2025-01-10T00:00:00Z"
        )

    finally:
        # Cleanup
        with _connect() as conn:
            _fetchall(conn, f"DROP TABLE IF EXISTS {test_state_table}")


def test_state_tracking_across_refreshes() -> None:
    """
    Test state incremental behavior across multiple bar refreshes.
    Simulates:
    1. First refresh: new state created
    2. Second refresh: state updated with new bar_seq and time_close
    3. Third refresh: daily_max_seen extended

    Verifies state advances correctly as new bars are processed.
    """
    test_state_table = "public.test_state_incremental"

    # Cleanup first
    with _connect() as conn:
        _fetchall(conn, f"DROP TABLE IF EXISTS {test_state_table}")

    try:
        # Create state table
        ensure_state_table(DB_URL, test_state_table, with_tz=True)

        # === Refresh 1: Initial state ===
        refresh1_state = pd.DataFrame(
            [
                {
                    "id": 52,
                    "tf": "14D",
                    "tz": "America/New_York",
                    "daily_min_seen": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "daily_max_seen": pd.Timestamp("2025-01-14T00:00:00Z"),
                    "last_bar_seq": 1,
                    "last_time_close": pd.Timestamp("2025-01-14T23:59:59Z"),
                }
            ]
        )

        upsert_state(DB_URL, test_state_table, refresh1_state, with_tz=True)

        # Verify initial state
        state_r1 = load_state(DB_URL, test_state_table, ids=[52], with_tz=True)
        assert len(state_r1) == 1
        assert state_r1.iloc[0]["last_bar_seq"] == 1
        assert pd.to_datetime(
            state_r1.iloc[0]["daily_max_seen"], utc=True
        ) == pd.Timestamp("2025-01-14T00:00:00Z")

        # === Refresh 2: New bar completed ===
        refresh2_state = pd.DataFrame(
            [
                {
                    "id": 52,
                    "tf": "14D",
                    "tz": "America/New_York",
                    "daily_min_seen": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "daily_max_seen": pd.Timestamp("2025-01-28T00:00:00Z"),  # Extended
                    "last_bar_seq": 2,  # Advanced
                    "last_time_close": pd.Timestamp("2025-01-28T23:59:59Z"),  # Advanced
                }
            ]
        )

        upsert_state(DB_URL, test_state_table, refresh2_state, with_tz=True)

        # Verify state advanced
        state_r2 = load_state(DB_URL, test_state_table, ids=[52], with_tz=True)
        assert len(state_r2) == 1, "Should still be one row (upsert)"
        assert state_r2.iloc[0]["last_bar_seq"] == 2, "bar_seq should advance"
        assert pd.to_datetime(
            state_r2.iloc[0]["last_time_close"], utc=True
        ) == pd.Timestamp("2025-01-28T23:59:59Z")
        assert pd.to_datetime(
            state_r2.iloc[0]["daily_max_seen"], utc=True
        ) == pd.Timestamp("2025-01-28T00:00:00Z")

        # === Refresh 3: In-progress bar (daily_max extends but bar not closed) ===
        refresh3_state = pd.DataFrame(
            [
                {
                    "id": 52,
                    "tf": "14D",
                    "tz": "America/New_York",
                    "daily_min_seen": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "daily_max_seen": pd.Timestamp(
                        "2025-02-05T00:00:00Z"
                    ),  # Extended further
                    "last_bar_seq": 2,  # Same (bar in progress)
                    "last_time_close": pd.Timestamp(
                        "2025-01-28T23:59:59Z"
                    ),  # Unchanged
                }
            ]
        )

        upsert_state(DB_URL, test_state_table, refresh3_state, with_tz=True)

        # Verify daily_max_seen updated but bar_seq/time_close stable
        state_r3 = load_state(DB_URL, test_state_table, ids=[52], with_tz=True)
        assert len(state_r3) == 1
        assert (
            state_r3.iloc[0]["last_bar_seq"] == 2
        ), "bar_seq unchanged (in-progress bar)"
        assert pd.to_datetime(
            state_r3.iloc[0]["last_time_close"], utc=True
        ) == pd.Timestamp("2025-01-28T23:59:59Z")
        assert pd.to_datetime(
            state_r3.iloc[0]["daily_max_seen"], utc=True
        ) == pd.Timestamp("2025-02-05T00:00:00Z"), "daily_max_seen extended"

    finally:
        # Cleanup
        with _connect() as conn:
            _fetchall(conn, f"DROP TABLE IF EXISTS {test_state_table}")


# ==============================================================================
# Backfill Detection Tests (GAP-C03)
# ==============================================================================


def test_check_for_backfill_detects_historical_data() -> None:
    """
    Test that check_for_backfill returns True when source has data
    earlier than daily_min_seen in state.
    """
    from ta_lab2.scripts.bars.refresh_cmc_price_bars_1d import _check_for_backfill

    test_source_table = "public.test_backfill_source"
    conn = _connect()

    try:
        # Create test source table with sample data
        _exec(conn, f"DROP TABLE IF EXISTS {test_source_table}")
        _exec(
            conn,
            f"""
            CREATE TABLE {test_source_table} (
                id integer,
                timestamp timestamptz
            )
        """,
        )

        # Insert data from 2025-01-15 onwards
        _exec(
            conn,
            f"""
            INSERT INTO {test_source_table} (id, timestamp) VALUES
            (100, '2025-01-15T00:00:00Z'),
            (100, '2025-01-16T00:00:00Z'),
            (100, '2025-01-17T00:00:00Z')
        """,
        )

        # Get the actual MIN from database to use as baseline
        min_row = _fetchall(
            conn, f"SELECT MIN(timestamp) FROM {test_source_table} WHERE id = 100"
        )
        actual_min = str(min_row[0][0])

        # State reflects current MIN
        state_no_backfill = {"daily_min_seen": actual_min}

        # No backfill: MIN in source matches state
        result = _check_for_backfill(conn, test_source_table, 100, state_no_backfill)
        assert result is False, "Should not detect backfill when MIN matches state"

        # Now insert historical data before 2025-01-15
        _exec(
            conn,
            f"""
            INSERT INTO {test_source_table} (id, timestamp) VALUES
            (100, '2025-01-05T00:00:00Z'),
            (100, '2025-01-06T00:00:00Z')
        """,
        )

        # Backfill detected: MIN in source is now earlier than state (still has old MIN)
        result_backfill = _check_for_backfill(
            conn, test_source_table, 100, state_no_backfill
        )
        assert (
            result_backfill is True
        ), "Should detect backfill when MIN < daily_min_seen"

    finally:
        _exec(conn, f"DROP TABLE IF EXISTS {test_source_table}")
        conn.close()


def test_check_for_backfill_no_state() -> None:
    """
    Test that check_for_backfill returns False when state is None (first run).
    """
    from ta_lab2.scripts.bars.refresh_cmc_price_bars_1d import _check_for_backfill

    test_source_table = "public.test_backfill_no_state"
    conn = _connect()

    try:
        # Create test source table
        _exec(conn, f"DROP TABLE IF EXISTS {test_source_table}")
        _exec(
            conn,
            f"""
            CREATE TABLE {test_source_table} (
                id integer,
                timestamp timestamptz
            )
        """,
        )

        _exec(
            conn,
            f"""
            INSERT INTO {test_source_table} (id, timestamp) VALUES
            (200, '2025-01-01T00:00:00Z')
        """,
        )

        # No state = first run, should not trigger backfill
        result = _check_for_backfill(conn, test_source_table, 200, None)
        assert result is False, "Should not detect backfill when state is None"

        # State with no daily_min_seen
        state_no_min = {"daily_min_seen": None}
        result2 = _check_for_backfill(conn, test_source_table, 200, state_no_min)
        assert (
            result2 is False
        ), "Should not detect backfill when daily_min_seen is None"

    finally:
        _exec(conn, f"DROP TABLE IF EXISTS {test_source_table}")
        conn.close()


def test_handle_backfill_deletes_bars_and_state() -> None:
    """
    Test that handle_backfill properly clears bars and state for rebuild.
    """
    from ta_lab2.scripts.bars.refresh_cmc_price_bars_1d import _handle_backfill

    test_bars_table = "public.test_backfill_bars"
    test_state_table = "public.test_backfill_state"
    conn = _connect()

    try:
        # Create test tables
        _exec(conn, f"DROP TABLE IF EXISTS {test_bars_table}")
        _exec(conn, f"DROP TABLE IF EXISTS {test_state_table}")

        _exec(
            conn,
            f"""
            CREATE TABLE {test_bars_table} (
                id integer,
                timestamp timestamptz,
                tf text,
                bar_seq bigint
            )
        """,
        )

        _exec(
            conn,
            f"""
            CREATE TABLE {test_state_table} (
                id integer PRIMARY KEY,
                last_src_ts timestamptz,
                daily_min_seen timestamptz
            )
        """,
        )

        # Insert test data
        _exec(
            conn,
            f"""
            INSERT INTO {test_bars_table} (id, timestamp, tf, bar_seq) VALUES
            (300, '2025-01-10T00:00:00Z', '1D', 1),
            (300, '2025-01-11T00:00:00Z', '1D', 2),
            (400, '2025-01-10T00:00:00Z', '1D', 1)
        """,
        )

        _exec(
            conn,
            f"""
            INSERT INTO {test_state_table} (id, last_src_ts, daily_min_seen) VALUES
            (300, '2025-01-11T00:00:00Z', '2025-01-10T00:00:00Z'),
            (400, '2025-01-10T00:00:00Z', '2025-01-10T00:00:00Z')
        """,
        )

        # Verify data exists
        bars_before = _fetchall(
            conn, f"SELECT COUNT(*) FROM {test_bars_table} WHERE id = 300"
        )
        state_before = _fetchall(
            conn, f"SELECT COUNT(*) FROM {test_state_table} WHERE id = 300"
        )
        assert bars_before[0][0] == 2, "Should have 2 bars before backfill"
        assert state_before[0][0] == 1, "Should have 1 state before backfill"

        # Handle backfill for id=300
        _handle_backfill(conn, test_bars_table, test_state_table, 300)

        # Verify data deleted for id=300
        bars_after = _fetchall(
            conn, f"SELECT COUNT(*) FROM {test_bars_table} WHERE id = 300"
        )
        state_after = _fetchall(
            conn, f"SELECT COUNT(*) FROM {test_state_table} WHERE id = 300"
        )
        assert bars_after[0][0] == 0, "Should have 0 bars after backfill"
        assert state_after[0][0] == 0, "Should have 0 state after backfill"

        # Verify id=400 data unaffected
        bars_other = _fetchall(
            conn, f"SELECT COUNT(*) FROM {test_bars_table} WHERE id = 400"
        )
        state_other = _fetchall(
            conn, f"SELECT COUNT(*) FROM {test_state_table} WHERE id = 400"
        )
        assert bars_other[0][0] == 1, "Other ID bars should be unaffected"
        assert state_other[0][0] == 1, "Other ID state should be unaffected"

    finally:
        _exec(conn, f"DROP TABLE IF EXISTS {test_bars_table}")
        _exec(conn, f"DROP TABLE IF EXISTS {test_state_table}")
        conn.close()


def test_daily_min_seen_updated_after_processing() -> None:
    """
    Test that daily_min_seen is tracked in state after processing new data.
    """
    test_state_table = "public.test_daily_min_seen_tracking"

    # Cleanup first
    with _connect() as conn:
        _exec(conn, f"DROP TABLE IF EXISTS {test_state_table}")

    try:
        # Create state table with daily_min_seen column
        ensure_state_table(DB_URL, test_state_table, with_tz=False)

        # Add daily_min_seen column if not exists (multi-TF state table has it, 1D needs migration)
        with _connect() as conn:
            _exec(
                conn,
                f"""
                ALTER TABLE {test_state_table}
                ADD COLUMN IF NOT EXISTS daily_min_seen TIMESTAMPTZ
            """,
            )

        # Initial state: first time processing this ID
        initial_state = pd.DataFrame(
            [
                {
                    "id": 500,
                    "tf": "1D",
                    "daily_min_seen": pd.Timestamp("2025-01-05T00:00:00Z"),
                    "daily_max_seen": pd.Timestamp("2025-01-10T00:00:00Z"),
                    "last_bar_seq": 5,
                    "last_time_close": pd.Timestamp("2025-01-10T23:59:59Z"),
                }
            ]
        )

        upsert_state(DB_URL, test_state_table, initial_state, with_tz=False)

        # Verify initial state
        loaded = load_state(DB_URL, test_state_table, ids=[500], with_tz=False)
        assert len(loaded) == 1
        assert pd.to_datetime(
            loaded.iloc[0]["daily_min_seen"], utc=True
        ) == pd.Timestamp("2025-01-05T00:00:00Z")

        # Simulate new data processing (daily_min unchanged, max extended)
        updated_state = pd.DataFrame(
            [
                {
                    "id": 500,
                    "tf": "1D",
                    "daily_min_seen": pd.Timestamp("2025-01-05T00:00:00Z"),  # Unchanged
                    "daily_max_seen": pd.Timestamp("2025-01-15T00:00:00Z"),  # Extended
                    "last_bar_seq": 10,
                    "last_time_close": pd.Timestamp("2025-01-15T23:59:59Z"),
                }
            ]
        )

        upsert_state(DB_URL, test_state_table, updated_state, with_tz=False)

        # Verify daily_min_seen unchanged (no backfill)
        loaded2 = load_state(DB_URL, test_state_table, ids=[500], with_tz=False)
        assert len(loaded2) == 1
        assert pd.to_datetime(
            loaded2.iloc[0]["daily_min_seen"], utc=True
        ) == pd.Timestamp("2025-01-05T00:00:00Z")
        assert loaded2.iloc[0]["last_bar_seq"] == 10

    finally:
        # Cleanup
        with _connect() as conn:
            _exec(conn, f"DROP TABLE IF EXISTS {test_state_table}")
