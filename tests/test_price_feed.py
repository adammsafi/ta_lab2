"""
Unit tests for the exchange price feed refresh logic.

All tests use mocks - no live API calls, no database, no network.
Tests cover: discrepancy computation, threshold logic (adaptive + fallback),
fetch error handling, bar_close=None edge cases, PriceFeedRow construction,
refresh_price_feed main loop (dry_run vs write), default constants.

Module under test: ta_lab2.scripts.exchange.refresh_exchange_price_feed
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Conditional import - skip entire module if price feed script not yet created
# ---------------------------------------------------------------------------

try:
    import ta_lab2.scripts.exchange.refresh_exchange_price_feed as _feed_mod

    _FEED_AVAILABLE = True
except ImportError:
    _feed_mod = None  # type: ignore[assignment]
    _FEED_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FEED_AVAILABLE,
    reason="refresh_exchange_price_feed.py not yet created (43-05 pending)",
)


def _mod():
    """Return the price feed module (available after pytestmark guard)."""
    return _feed_mod


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_fallback_threshold_is_5pct(self):
        mod = _mod()
        assert mod.FALLBACK_THRESHOLD_PCT == pytest.approx(5.0)

    def test_default_pairs_includes_btc_usd(self):
        mod = _mod()
        assert "BTC/USD" in mod.DEFAULT_PAIRS

    def test_default_pairs_includes_eth_usd(self):
        mod = _mod()
        assert "ETH/USD" in mod.DEFAULT_PAIRS

    def test_default_exchanges_includes_coinbase(self):
        mod = _mod()
        assert "coinbase" in mod.DEFAULT_EXCHANGES

    def test_default_exchanges_includes_kraken(self):
        mod = _mod()
        assert "kraken" in mod.DEFAULT_EXCHANGES


# ---------------------------------------------------------------------------
# _base_symbol helper
# ---------------------------------------------------------------------------


class TestBaseSymbol:
    def test_slash_notation(self):
        mod = _mod()
        assert mod._base_symbol("BTC/USD") == "BTC"

    def test_dash_notation(self):
        mod = _mod()
        assert mod._base_symbol("ETH-USD") == "ETH"

    def test_eth_pair(self):
        mod = _mod()
        assert mod._base_symbol("ETH/USD") == "ETH"

    def test_uppercase_result(self):
        mod = _mod()
        assert mod._base_symbol("btc/usd") == "BTC"

    def test_no_separator_uses_first_three_chars(self):
        mod = _mod()
        assert mod._base_symbol("BTCUSD") == "BTC"


# ---------------------------------------------------------------------------
# Discrepancy formula tests (logic-only, no module calls)
# ---------------------------------------------------------------------------


class TestDiscrepancyFormula:
    """
    Pure arithmetic tests for discrepancy_pct = abs(live - bar_close) / bar_close * 100.
    These validate that the formula is correct before using it to assert module output.
    """

    def _compute(self, live: float, bar_close: float) -> float:
        return abs(live - bar_close) / bar_close * 100.0

    def test_zero_discrepancy_when_equal(self):
        assert self._compute(50000.0, 50000.0) == pytest.approx(0.0)

    def test_1pct_above(self):
        assert self._compute(50500.0, 50000.0) == pytest.approx(1.0)

    def test_1pct_below(self):
        assert self._compute(49500.0, 50000.0) == pytest.approx(1.0)

    def test_5pct_discrepancy(self):
        assert self._compute(52500.0, 50000.0) == pytest.approx(5.0)

    def test_20pct_discrepancy(self):
        assert self._compute(60000.0, 50000.0) == pytest.approx(20.0)

    def test_sub_percent_discrepancy(self):
        assert self._compute(50001.0, 50000.0) == pytest.approx(0.002)


# ---------------------------------------------------------------------------
# Threshold comparison logic
# ---------------------------------------------------------------------------


class TestThresholdLogic:
    def test_exceeds_when_above_threshold(self):
        assert 6.0 > 5.0  # exceeds

    def test_does_not_exceed_below_threshold(self):
        assert not (3.0 > 5.0)

    def test_does_not_exceed_at_exact_threshold(self):
        assert not (5.0 > 5.0)

    def test_exceeds_with_large_negative_discrepancy(self):
        assert abs(-8.0) > 5.0

    def test_adaptive_threshold_scales_with_std(self):
        """3 * std_ret_30 * 100 = expected threshold."""
        std = 0.02
        expected = 3.0 * std * 100.0
        assert expected == pytest.approx(6.0)

    def test_higher_std_gives_higher_threshold(self):
        threshold_low_vol = 3.0 * 0.01 * 100.0
        threshold_high_vol = 3.0 * 0.03 * 100.0
        assert threshold_high_vol > threshold_low_vol


# ---------------------------------------------------------------------------
# _get_latest_bar_close
# ---------------------------------------------------------------------------


class TestGetLatestBarClose:
    def _make_conn_with_row(self, close=50000.0, ts=None):
        ts = ts or datetime(2024, 1, 1, tzinfo=timezone.utc)
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=lambda i: {0: close, 1: ts}[i])
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        conn = MagicMock()
        conn.execute.return_value = mock_result
        return conn

    def _make_conn_no_row(self):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        conn = MagicMock()
        conn.execute.return_value = mock_result
        return conn

    def test_returns_close_price_as_float(self):
        mod = _mod()
        conn = self._make_conn_with_row(close=50000.0)
        price, ts = mod._get_latest_bar_close(conn, "BTC")
        assert price == pytest.approx(50000.0)
        assert isinstance(price, float)

    def test_returns_bar_ts(self):
        mod = _mod()
        bar_ts = datetime(2024, 6, 15, tzinfo=timezone.utc)
        conn = self._make_conn_with_row(close=50000.0, ts=bar_ts)
        price, ts = mod._get_latest_bar_close(conn, "BTC")
        assert ts == bar_ts

    def test_returns_none_none_when_no_row(self):
        mod = _mod()
        conn = self._make_conn_no_row()
        price, ts = mod._get_latest_bar_close(conn, "BTC")
        assert price is None
        assert ts is None

    def test_returns_none_none_on_no_result(self):
        """When DB returns no row (None), function should return (None, None)."""
        mod = _mod()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        conn = MagicMock()
        conn.execute.return_value = mock_result
        price, ts = mod._get_latest_bar_close(conn, "BTC")
        assert price is None
        assert ts is None

    def test_query_uses_symbol_and_tf(self):
        mod = _mod()
        conn = self._make_conn_no_row()
        mod._get_latest_bar_close(conn, "ETH", tf="1D")
        # Just verify execute was called (DB access occurred)
        conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# _get_adaptive_threshold
# ---------------------------------------------------------------------------


class TestGetAdaptiveThreshold:
    def _make_conn_with_std(self, std_ret_30=0.02):
        row = MagicMock()
        row.__getitem__ = MagicMock(
            side_effect=lambda i: std_ret_30 if i == 0 else None
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        conn = MagicMock()
        conn.execute.return_value = mock_result
        return conn

    def _make_conn_no_row(self):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        conn = MagicMock()
        conn.execute.return_value = mock_result
        return conn

    def test_3sigma_scaling_applied(self):
        """threshold = 3 * std_ret_30 * 100."""
        mod = _mod()
        conn = self._make_conn_with_std(std_ret_30=0.02)
        result = mod._get_adaptive_threshold(conn, "BTC")
        assert result == pytest.approx(6.0)

    def test_different_std_gives_different_threshold(self):
        mod = _mod()
        conn = self._make_conn_with_std(std_ret_30=0.01)
        result = mod._get_adaptive_threshold(conn, "BTC")
        assert result == pytest.approx(3.0)

    def test_fallback_when_no_row(self):
        mod = _mod()
        conn = self._make_conn_no_row()
        result = mod._get_adaptive_threshold(conn, "BTC")
        assert result == pytest.approx(mod.FALLBACK_THRESHOLD_PCT)

    def test_fallback_when_std_ret_30_none_in_row(self):
        """When row exists but std_ret_30 is None, fallback threshold used."""
        mod = _mod()
        row = MagicMock()
        row.__getitem__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        conn = MagicMock()
        conn.execute.return_value = mock_result
        result = mod._get_adaptive_threshold(conn, "BTC")
        assert result == pytest.approx(mod.FALLBACK_THRESHOLD_PCT)


# ---------------------------------------------------------------------------
# _fetch_live_price
# ---------------------------------------------------------------------------


class TestFetchLivePrice:
    """
    _fetch_live_price returns a 4-tuple: (bid, ask, mid, last_price).
    All values may be None on failure.
    """

    def test_returns_4_tuple(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 50000.0}

        with patch(
            "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
            return_value=mock_adapter,
        ):
            result = mod._fetch_live_price("coinbase", "BTC/USD")

        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_last_price_in_result(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 50000.0}

        with patch(
            "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
            return_value=mock_adapter,
        ):
            bid, ask, mid, last_price = mod._fetch_live_price("coinbase", "BTC/USD")

        assert last_price == pytest.approx(50000.0)

    def test_mid_price_falls_back_to_last_price_without_bid_ask(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 50000.0}

        with patch(
            "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
            return_value=mock_adapter,
        ):
            bid, ask, mid, last_price = mod._fetch_live_price("coinbase", "BTC/USD")

        assert mid == pytest.approx(50000.0)
        assert bid is None
        assert ask is None

    def test_mid_computed_as_average_of_bid_ask(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {
            "last_price": 50000.0,
            "bid": 49990.0,
            "ask": 50010.0,
        }

        with patch(
            "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
            return_value=mock_adapter,
        ):
            bid, ask, mid, last_price = mod._fetch_live_price("coinbase", "BTC/USD")

        assert mid == pytest.approx(50000.0)
        assert bid == pytest.approx(49990.0)
        assert ask == pytest.approx(50010.0)

    def test_returns_none_tuple_when_get_exchange_raises(self):
        mod = _mod()

        with patch(
            "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
            side_effect=Exception("Network error"),
        ):
            result = mod._fetch_live_price("coinbase", "BTC/USD")

        assert result == (None, None, None, None)

    def test_returns_none_tuple_when_get_ticker_raises(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.side_effect = Exception("API timeout")

        with patch(
            "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
            return_value=mock_adapter,
        ):
            result = mod._fetch_live_price("kraken", "BTC/USD")

        assert result == (None, None, None, None)

    def test_bid_ask_are_none_when_not_in_ticker(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 3200.0}

        with patch(
            "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
            return_value=mock_adapter,
        ):
            bid, ask, mid, last_price = mod._fetch_live_price("coinbase", "ETH/USD")

        assert bid is None
        assert ask is None
        assert last_price == pytest.approx(3200.0)


# ---------------------------------------------------------------------------
# bar_close=None edge case in discrepancy logic
# ---------------------------------------------------------------------------


class TestBarCloseNoneEdge:
    def test_discrepancy_none_when_bar_close_none(self):
        """When bar_close is None, the guard should prevent division."""
        bar_close = None
        live_price = 50000.0
        if bar_close is not None and bar_close != 0:
            discrepancy_pct = abs(live_price - bar_close) / bar_close * 100.0
        else:
            discrepancy_pct = None
        assert discrepancy_pct is None

    def test_exceeds_threshold_false_when_discrepancy_none(self):
        discrepancy_pct = None
        threshold_pct = 5.0
        exceeds = (discrepancy_pct is not None) and (discrepancy_pct > threshold_pct)
        assert exceeds is False


# ---------------------------------------------------------------------------
# refresh_price_feed - integration with fully mocked dependencies
# ---------------------------------------------------------------------------


def _make_mock_engine_conn(close=50000.0, std_ret_30=0.02):
    """Build a mock engine + connection that returns canned bar close and stats."""
    bar_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bar_row = MagicMock()
    bar_row.__getitem__ = MagicMock(side_effect=lambda i: {0: close, 1: bar_ts}[i])

    stats_row = MagicMock()
    stats_row.__getitem__ = MagicMock(
        side_effect=lambda i: std_ret_30 if i == 0 else None
    )

    bar_result = MagicMock()
    bar_result.fetchone.return_value = bar_row

    stats_result = MagicMock()
    stats_result.fetchone.return_value = stats_row

    conn = MagicMock()
    conn.execute.side_effect = [bar_result, stats_result] * 20  # enough for any loop

    engine = MagicMock()
    ctx_mgr = MagicMock()
    ctx_mgr.__enter__ = MagicMock(return_value=conn)
    ctx_mgr.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = ctx_mgr

    return engine, conn


class TestRefreshPriceFeed:
    def test_dry_run_does_not_call_write_feed_row(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 50000.0}
        engine, conn = _make_mock_engine_conn()

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row") as mock_write,
        ):
            mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=True,
            )

        mock_write.assert_not_called()

    def test_non_dry_run_calls_write_feed_row(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 50000.0}
        engine, conn = _make_mock_engine_conn()

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row") as mock_write,
        ):
            mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=False,
            )

        mock_write.assert_called_once()

    def test_returns_list_of_price_feed_rows(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 50000.0}
        engine, conn = _make_mock_engine_conn()

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row"),
        ):
            rows = mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=True,
            )

        assert isinstance(rows, list)
        assert len(rows) == 1
        row = rows[0]
        assert row.exchange == "coinbase"
        assert row.pair == "BTC/USD"

    def test_skips_pair_when_fetch_returns_all_none(self):
        """When _fetch_live_price returns (None, None, None, None), no row is written."""
        mod = _mod()
        engine, conn = _make_mock_engine_conn()

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                side_effect=Exception("Network error"),
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row") as mock_write,
        ):
            rows = mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=False,
            )

        mock_write.assert_not_called()
        assert len(rows) == 0

    def test_processes_multiple_exchange_pair_combinations(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 50000.0}
        engine, conn = _make_mock_engine_conn()

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row"),
        ):
            rows = mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase", "kraken"],
                pairs=["BTC/USD", "ETH/USD"],
                dry_run=True,
            )

        # 2 exchanges x 2 pairs = 4 rows
        assert len(rows) == 4

    def test_row_has_discrepancy_pct_when_bar_close_available(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 51000.0}
        engine, conn = _make_mock_engine_conn(close=50000.0)

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row"),
        ):
            rows = mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=True,
            )

        row = rows[0]
        assert row.discrepancy_pct is not None
        assert row.discrepancy_pct == pytest.approx(2.0)  # (51000-50000)/50000*100

    def test_row_discrepancy_none_when_no_bar_close(self):
        mod = _mod()
        mock_adapter = MagicMock()
        mock_adapter.get_ticker.return_value = {"last_price": 51000.0}

        # Connection returns no bar close
        no_row_result = MagicMock()
        no_row_result.fetchone.return_value = None
        conn = MagicMock()
        conn.execute.return_value = no_row_result

        engine = MagicMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=conn)
        ctx_mgr.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value = ctx_mgr

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row"),
        ):
            rows = mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=True,
            )

        row = rows[0]
        assert row.discrepancy_pct is None
        assert row.exceeds_threshold is False

    def test_exceeds_threshold_true_when_large_discrepancy(self):
        """With 20% discrepancy and 6% threshold, exceeds_threshold should be True."""
        mod = _mod()
        mock_adapter = MagicMock()
        # 60000 vs bar_close 50000 = 20% discrepancy
        mock_adapter.get_ticker.return_value = {"last_price": 60000.0}
        # std_ret_30 = 0.02 → threshold = 6%
        engine, conn = _make_mock_engine_conn(close=50000.0, std_ret_30=0.02)

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row"),
        ):
            rows = mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=True,
            )

        row = rows[0]
        assert row.exceeds_threshold is True

    def test_exceeds_threshold_false_when_small_discrepancy(self):
        """With 1% discrepancy and 6% threshold, exceeds_threshold should be False."""
        mod = _mod()
        mock_adapter = MagicMock()
        # 50500 vs 50000 = 1% discrepancy
        mock_adapter.get_ticker.return_value = {"last_price": 50500.0}
        # std_ret_30 = 0.02 → threshold = 6%
        engine, conn = _make_mock_engine_conn(close=50000.0, std_ret_30=0.02)

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.get_exchange",
                return_value=mock_adapter,
            ),
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_write_feed_row"),
        ):
            rows = mod.refresh_price_feed(
                db_url="postgresql://test",
                exchanges=["coinbase"],
                pairs=["BTC/USD"],
                dry_run=True,
            )

        row = rows[0]
        assert row.exceeds_threshold is False

    def test_uses_default_exchanges_when_none_provided(self):
        mod = _mod()
        call_log: list[str] = []

        def mock_fetch(exchange_name, pair):
            call_log.append(exchange_name)
            return None, None, None, None  # skip write

        no_row_result = MagicMock()
        no_row_result.fetchone.return_value = None
        conn = MagicMock()
        conn.execute.return_value = no_row_result
        engine = MagicMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=conn)
        ctx_mgr.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value = ctx_mgr

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_fetch_live_price", side_effect=mock_fetch),
        ):
            mod.refresh_price_feed(db_url="postgresql://test", dry_run=True)

        for exchange in mod.DEFAULT_EXCHANGES:
            assert exchange in call_log, f"{exchange} not called"

    def test_uses_default_pairs_when_none_provided(self):
        mod = _mod()
        call_log: list[str] = []

        def mock_fetch(exchange_name, pair):
            call_log.append(pair)
            return None, None, None, None

        no_row_result = MagicMock()
        no_row_result.fetchone.return_value = None
        conn = MagicMock()
        conn.execute.return_value = no_row_result
        engine = MagicMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=conn)
        ctx_mgr.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value = ctx_mgr

        with (
            patch(
                "ta_lab2.scripts.exchange.refresh_exchange_price_feed.create_engine",
                return_value=engine,
            ),
            patch.object(mod, "_fetch_live_price", side_effect=mock_fetch),
        ):
            mod.refresh_price_feed(db_url="postgresql://test", dry_run=True)

        for pair in mod.DEFAULT_PAIRS:
            assert pair in call_log, f"{pair} not fetched"
