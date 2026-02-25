"""Unit tests for OverrideManager.

All tests run without a live database. SQLAlchemy Engine is mocked throughout.
The mock connection returns controlled SQL results for precise behavior testing.

Tests cover:
    1. TestCreateOverride       -- dual INSERT (override + event), return override_id
    2. TestCreateStickyOverride -- sticky=True propagated to INSERT params
    3. TestApplyOverride        -- UPDATE + event INSERT on success
    4. TestApplyAlreadyApplied  -- rowcount=0 -> no event INSERT (no-op)
    5. TestRevertOverride       -- UPDATE + event INSERT on success
    6. TestGetActiveOverrides   -- WHERE reverted_at IS NULL, returns OverrideInfo list
    7. TestGetPendingNonStickyOverrides -- WHERE sticky=FALSE AND applied_at IS NOT NULL ...
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


from ta_lab2.risk.override_manager import OverrideInfo, OverrideManager


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 2, 25, 12, 0, 0, tzinfo=timezone.utc)
_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _make_begin_engine(execute_side_effects: list) -> MagicMock:
    """Build a mock engine whose engine.begin() context manager sequences through execute side-effects.

    Each item in execute_side_effects is a MagicMock result returned for the
    corresponding conn.execute() call within the begin() block.
    """
    engine = MagicMock()
    conn = MagicMock()

    # Set up conn.execute to return each result in sequence
    conn.execute.side_effect = execute_side_effects

    # engine.begin() as conn
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    return engine, conn


def _make_connect_engine(rows: list) -> MagicMock:
    """Build a mock engine whose engine.connect() returns the given rows from fetchall()."""
    engine = MagicMock()
    conn = MagicMock()

    result = MagicMock()
    result.fetchall.return_value = rows
    conn.execute.return_value = result

    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    return engine, conn


def _make_override_row(
    override_id: str = _UUID,
    asset_id: int = 1,
    strategy_id: int = 2,
    operator: str = "asafi",
    reason: str = "test reason",
    system_signal: str = "long",
    override_action: str = "flat",
    sticky: bool = False,
    created_at: datetime = _NOW,
    applied_at=None,
    reverted_at=None,
    revert_reason=None,
) -> MagicMock:
    """Build a mock row with _mapping attribute for OverrideInfo construction."""
    row = MagicMock()
    row._mapping = {
        "override_id": override_id,
        "asset_id": asset_id,
        "strategy_id": strategy_id,
        "operator": operator,
        "reason": reason,
        "system_signal": system_signal,
        "override_action": override_action,
        "sticky": sticky,
        "created_at": created_at,
        "applied_at": applied_at,
        "reverted_at": reverted_at,
        "revert_reason": revert_reason,
    }
    return row


# ---------------------------------------------------------------------------
# Test 1: TestCreateOverride
# ---------------------------------------------------------------------------


class TestCreateOverride:
    """create_override inserts row into cmc_risk_overrides + audit event."""

    def test_returns_override_id(self) -> None:
        """create_override returns the UUID string from RETURNING clause."""
        insert_override_result = MagicMock()
        insert_override_result.scalar.return_value = _UUID

        insert_event_result = MagicMock()

        engine, conn = _make_begin_engine([insert_override_result, insert_event_result])
        mgr = OverrideManager(engine)

        result = mgr.create_override(
            asset_id=1,
            strategy_id=2,
            operator="asafi",
            reason="test",
            system_signal="long",
            override_action="flat",
        )

        assert result == _UUID

    def test_calls_execute_twice(self) -> None:
        """Two DB operations: INSERT into cmc_risk_overrides + INSERT into cmc_risk_events."""
        insert_override_result = MagicMock()
        insert_override_result.scalar.return_value = _UUID

        insert_event_result = MagicMock()

        engine, conn = _make_begin_engine([insert_override_result, insert_event_result])
        mgr = OverrideManager(engine)

        mgr.create_override(
            asset_id=1,
            strategy_id=2,
            operator="asafi",
            reason="test",
            system_signal="long",
            override_action="flat",
        )

        assert conn.execute.call_count == 2

    def test_first_insert_targets_cmc_risk_overrides(self) -> None:
        """First INSERT targets cmc_risk_overrides table."""
        insert_override_result = MagicMock()
        insert_override_result.scalar.return_value = _UUID

        engine, conn = _make_begin_engine([insert_override_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.create_override(
            asset_id=1,
            strategy_id=2,
            operator="asafi",
            reason="test",
            system_signal="long",
            override_action="flat",
        )

        first_call_sql = str(conn.execute.call_args_list[0][0][0])
        assert "cmc_risk_overrides" in first_call_sql

    def test_second_insert_targets_cmc_risk_events_with_correct_type(self) -> None:
        """Second INSERT targets cmc_risk_events with event_type='override_created'."""
        insert_override_result = MagicMock()
        insert_override_result.scalar.return_value = _UUID

        engine, conn = _make_begin_engine([insert_override_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.create_override(
            asset_id=1,
            strategy_id=2,
            operator="asafi",
            reason="test",
            system_signal="long",
            override_action="flat",
        )

        second_call_sql = str(conn.execute.call_args_list[1][0][0])
        assert "cmc_risk_events" in second_call_sql
        # Params passed as second positional arg
        second_call_params = conn.execute.call_args_list[1][0][1]
        assert second_call_params.get("reason") == "test"
        assert second_call_params.get("operator") == "asafi"

    def test_non_sticky_by_default(self) -> None:
        """Default sticky=False is passed to the INSERT."""
        insert_override_result = MagicMock()
        insert_override_result.scalar.return_value = _UUID

        engine, conn = _make_begin_engine([insert_override_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.create_override(
            asset_id=1,
            strategy_id=2,
            operator="asafi",
            reason="test",
            system_signal="long",
            override_action="flat",
        )

        first_call_params = conn.execute.call_args_list[0][0][1]
        assert first_call_params["sticky"] is False


# ---------------------------------------------------------------------------
# Test 2: TestCreateStickyOverride
# ---------------------------------------------------------------------------


class TestCreateStickyOverride:
    """sticky=True is propagated to the INSERT params."""

    def test_sticky_flag_in_params(self) -> None:
        """When sticky=True is passed, the INSERT params contain sticky=True."""
        insert_override_result = MagicMock()
        insert_override_result.scalar.return_value = _UUID

        engine, conn = _make_begin_engine([insert_override_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.create_override(
            asset_id=1,
            strategy_id=2,
            operator="asafi",
            reason="Manual risk reduction",
            system_signal="long",
            override_action="flat",
            sticky=True,
        )

        first_call_params = conn.execute.call_args_list[0][0][1]
        assert first_call_params["sticky"] is True


# ---------------------------------------------------------------------------
# Test 3: TestApplyOverride
# ---------------------------------------------------------------------------


class TestApplyOverride:
    """apply_override sets applied_at and logs override_applied event."""

    def test_update_and_event_on_success(self) -> None:
        """When UPDATE affects 1 row, event INSERT is also called."""
        update_result = MagicMock()
        update_result.rowcount = 1

        event_result = MagicMock()

        engine, conn = _make_begin_engine([update_result, event_result])
        mgr = OverrideManager(engine)

        mgr.apply_override(override_id=_UUID)

        assert conn.execute.call_count == 2

    def test_update_sql_sets_applied_at(self) -> None:
        """UPDATE SQL targets cmc_risk_overrides and sets applied_at."""
        update_result = MagicMock()
        update_result.rowcount = 1

        engine, conn = _make_begin_engine([update_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.apply_override(override_id=_UUID)

        update_sql = str(conn.execute.call_args_list[0][0][0])
        assert "cmc_risk_overrides" in update_sql
        assert "applied_at" in update_sql

    def test_event_type_is_override_applied(self) -> None:
        """Event INSERT targets cmc_risk_events with event_type='override_applied'."""
        update_result = MagicMock()
        update_result.rowcount = 1

        engine, conn = _make_begin_engine([update_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.apply_override(override_id=_UUID)

        event_sql = str(conn.execute.call_args_list[1][0][0])
        assert "cmc_risk_events" in event_sql
        assert "override_applied" in event_sql


# ---------------------------------------------------------------------------
# Test 4: TestApplyAlreadyApplied
# ---------------------------------------------------------------------------


class TestApplyAlreadyApplied:
    """When UPDATE returns rowcount=0, apply_override is a no-op (no event INSERT)."""

    def test_no_event_insert_when_already_applied(self) -> None:
        """rowcount=0 means already applied -- no event INSERT, just early return."""
        update_result = MagicMock()
        update_result.rowcount = 0

        engine, conn = _make_begin_engine([update_result])
        mgr = OverrideManager(engine)

        mgr.apply_override(override_id=_UUID)

        # Only the UPDATE was called, no event INSERT
        assert conn.execute.call_count == 1


# ---------------------------------------------------------------------------
# Test 5: TestRevertOverride
# ---------------------------------------------------------------------------


class TestRevertOverride:
    """revert_override sets reverted_at + revert_reason and logs override_reverted event."""

    def test_update_and_event_on_success(self) -> None:
        """When UPDATE affects 1 row, event INSERT is also called."""
        update_result = MagicMock()
        update_result.rowcount = 1

        event_result = MagicMock()

        engine, conn = _make_begin_engine([update_result, event_result])
        mgr = OverrideManager(engine)

        mgr.revert_override(override_id=_UUID, reason="resolved", operator="asafi")

        assert conn.execute.call_count == 2

    def test_update_sql_sets_reverted_at_and_reason(self) -> None:
        """UPDATE SQL sets reverted_at and revert_reason."""
        update_result = MagicMock()
        update_result.rowcount = 1

        engine, conn = _make_begin_engine([update_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.revert_override(override_id=_UUID, reason="resolved", operator="asafi")

        update_sql = str(conn.execute.call_args_list[0][0][0])
        update_params = conn.execute.call_args_list[0][0][1]
        assert "reverted_at" in update_sql
        assert "revert_reason" in update_sql
        assert update_params["reason"] == "resolved"

    def test_event_type_is_override_reverted(self) -> None:
        """Event INSERT includes event_type='override_reverted'."""
        update_result = MagicMock()
        update_result.rowcount = 1

        engine, conn = _make_begin_engine([update_result, MagicMock()])
        mgr = OverrideManager(engine)

        mgr.revert_override(override_id=_UUID, reason="resolved", operator="asafi")

        event_sql = str(conn.execute.call_args_list[1][0][0])
        assert "cmc_risk_events" in event_sql
        assert "override_reverted" in event_sql

    def test_no_event_when_already_reverted(self) -> None:
        """rowcount=0 means already reverted -- no event INSERT."""
        update_result = MagicMock()
        update_result.rowcount = 0

        engine, conn = _make_begin_engine([update_result])
        mgr = OverrideManager(engine)

        mgr.revert_override(override_id=_UUID, reason="resolved", operator="asafi")

        assert conn.execute.call_count == 1


# ---------------------------------------------------------------------------
# Test 6: TestGetActiveOverrides
# ---------------------------------------------------------------------------


class TestGetActiveOverrides:
    """get_active_overrides returns OverrideInfo list from WHERE reverted_at IS NULL."""

    def test_returns_two_override_info_objects(self) -> None:
        """Two DB rows produce two OverrideInfo objects."""
        row1 = _make_override_row(override_id="aaa1", asset_id=1, strategy_id=2)
        row2 = _make_override_row(override_id="bbb2", asset_id=3, strategy_id=4)

        engine, conn = _make_connect_engine([row1, row2])
        mgr = OverrideManager(engine)

        result = mgr.get_active_overrides()

        assert len(result) == 2
        assert isinstance(result[0], OverrideInfo)
        assert isinstance(result[1], OverrideInfo)
        assert result[0].override_id == "aaa1"
        assert result[1].override_id == "bbb2"

    def test_sql_filters_reverted_at_is_null(self) -> None:
        """SELECT SQL includes WHERE reverted_at IS NULL."""
        engine, conn = _make_connect_engine([])
        mgr = OverrideManager(engine)

        mgr.get_active_overrides()

        executed_sql = str(conn.execute.call_args_list[0][0][0])
        assert "reverted_at IS NULL" in executed_sql

    def test_asset_id_filter_applied(self) -> None:
        """When asset_id is provided, SQL includes asset_id filter."""
        engine, conn = _make_connect_engine([])
        mgr = OverrideManager(engine)

        mgr.get_active_overrides(asset_id=42)

        executed_sql = str(conn.execute.call_args_list[0][0][0])
        executed_params = conn.execute.call_args_list[0][0][1]
        assert "asset_id" in executed_sql
        assert executed_params.get("asset_id") == 42

    def test_empty_result_returns_empty_list(self) -> None:
        """No active overrides returns empty list."""
        engine, conn = _make_connect_engine([])
        mgr = OverrideManager(engine)

        result = mgr.get_active_overrides()

        assert result == []


# ---------------------------------------------------------------------------
# Test 7: TestGetPendingNonStickyOverrides
# ---------------------------------------------------------------------------


class TestGetPendingNonStickyOverrides:
    """get_pending_non_sticky_overrides identifies applied non-sticky overrides for auto-revert."""

    def test_returns_one_override_info(self) -> None:
        """One DB row produces one OverrideInfo object."""
        row = _make_override_row(
            override_id=_UUID,
            sticky=False,
            applied_at=_NOW,
            reverted_at=None,
        )

        engine, conn = _make_connect_engine([row])
        mgr = OverrideManager(engine)

        result = mgr.get_pending_non_sticky_overrides()

        assert len(result) == 1
        assert isinstance(result[0], OverrideInfo)
        assert result[0].override_id == _UUID

    def test_sql_includes_sticky_false_and_applied_at_not_null(self) -> None:
        """WHERE clause includes sticky = FALSE AND applied_at IS NOT NULL AND reverted_at IS NULL."""
        engine, conn = _make_connect_engine([])
        mgr = OverrideManager(engine)

        mgr.get_pending_non_sticky_overrides()

        executed_sql = str(conn.execute.call_args_list[0][0][0])
        assert "sticky = FALSE" in executed_sql
        assert "applied_at IS NOT NULL" in executed_sql
        assert "reverted_at IS NULL" in executed_sql

    def test_empty_result_returns_empty_list(self) -> None:
        """No pending non-sticky overrides returns empty list."""
        engine, conn = _make_connect_engine([])
        mgr = OverrideManager(engine)

        result = mgr.get_pending_non_sticky_overrides()

        assert result == []
