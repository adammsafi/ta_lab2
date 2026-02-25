"""
Tests for funding_adjuster.py

All tests are pure unit tests -- no database connection required.
DB-dependent functions (load_funding_rates_for_backtest, FundingAdjuster.adjust)
are tested via mocks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd

from ta_lab2.backtests.funding_adjuster import (
    FundingAdjustedResult,
    FundingAdjuster,
    compute_funding_payments,
    load_funding_rates_for_backtest,
    _strip_tz,
    _total_return,
    _sharpe_daily,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_daily_index(n: int, tz: str | None = None) -> pd.DatetimeIndex:
    """Return a DatetimeIndex of n daily bars starting 2024-01-01."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    if tz:
        return idx.tz_localize(tz)
    return idx


def _make_position(n: int, value: float = 10_000.0, tz: str | None = None) -> pd.Series:
    """Flat notional position of `value` for `n` bars."""
    return pd.Series([value] * n, index=_make_daily_index(n, tz=tz), name="position")


def _make_rates(n: int, rate: float, tz: str | None = None) -> pd.Series:
    """Constant funding rate series of length n."""
    return pd.Series([rate] * n, index=_make_daily_index(n, tz=tz), name="funding_rate")


# ---------------------------------------------------------------------------
# compute_funding_payments -- pure function tests
# ---------------------------------------------------------------------------


class TestComputeFundingPayments:
    """Tests for the core pure function."""

    def test_constant_position_constant_rate_long(self):
        """Long position + positive rate -> negative payments (outflow)."""
        position = _make_position(5, value=10_000.0)
        rates = _make_rates(5, rate=0.0001)  # 0.01% daily

        payments = compute_funding_payments(position, rates, is_short=False)

        assert len(payments) == 5
        # positive rate * positive position -> long PAYS -> negative cash flow
        assert all(payments < 0), "Long should have negative payments for positive rate"
        expected = -10_000.0 * 0.0001
        assert all(abs(payments - expected) < 1e-9), (
            f"Expected {expected}, got {payments.values}"
        )

    def test_constant_position_constant_rate_short(self):
        """Short position + positive rate -> positive payments (inflow)."""
        position = _make_position(5, value=10_000.0)
        rates = _make_rates(5, rate=0.0001)

        payments = compute_funding_payments(position, rates, is_short=True)

        assert len(payments) == 5
        # positive rate -> shorts RECEIVE -> positive cash flow
        assert all(payments > 0), (
            "Short should have positive payments for positive rate"
        )
        expected = 10_000.0 * 0.0001
        assert all(abs(payments - expected) < 1e-9), (
            f"Expected {expected}, got {payments.values}"
        )

    def test_negative_rate_long_receives(self):
        """Long position + negative rate -> long receives (positive payment)."""
        position = _make_position(3, value=5_000.0)
        rates = _make_rates(3, rate=-0.0002)  # negative rate

        payments = compute_funding_payments(position, rates, is_short=False)

        assert all(payments > 0), "Long should receive (positive) when rate is negative"

    def test_negative_rate_short_pays(self):
        """Short position + negative rate -> short pays (negative payment)."""
        position = _make_position(3, value=5_000.0)
        rates = _make_rates(3, rate=-0.0002)

        payments = compute_funding_payments(position, rates, is_short=True)

        assert all(payments < 0), "Short should pay (negative) when rate is negative"

    def test_zero_funding_rate(self):
        """Zero funding rate -> all payments are zero."""
        position = _make_position(10, value=20_000.0)
        rates = _make_rates(10, rate=0.0)

        payments = compute_funding_payments(position, rates, is_short=False)

        assert len(payments) == 10
        assert all(payments == 0.0), "Zero rate -> zero payments"

    def test_alignment_different_frequency(self):
        """Funding rates at different (coarser) frequency are forward-filled."""
        # Position: daily bars 2024-01-01..2024-01-10
        pos_index = pd.date_range("2024-01-01", periods=10, freq="D")
        position = pd.Series([10_000.0] * 10, index=pos_index)

        # Rates: every 3 days only (coarser)
        rate_index = pd.DatetimeIndex(
            [
                pd.Timestamp("2024-01-01"),
                pd.Timestamp("2024-01-04"),
                pd.Timestamp("2024-01-07"),
                pd.Timestamp("2024-01-10"),
            ]
        )
        rates = pd.Series([0.0001, 0.0002, 0.0003, 0.0004], index=rate_index)

        payments = compute_funding_payments(position, rates, is_short=False)

        assert len(payments) == 10
        # First bar: rate=0.0001, days 1-3 -> payment=-1.0
        assert abs(payments.iloc[0] - (-10_000.0 * 0.0001)) < 1e-9
        # Bar on Jan 4 gets 0.0002 (ffilled from Jan 4)
        assert abs(payments.iloc[3] - (-10_000.0 * 0.0002)) < 1e-9

    def test_empty_position_returns_empty(self):
        """Empty position timeline -> empty payments series."""
        position = pd.Series([], dtype=float)
        rates = _make_rates(5, rate=0.0001)
        payments = compute_funding_payments(position, rates, is_short=False)
        assert payments.empty

    def test_empty_funding_rates_returns_zeros(self):
        """Empty funding rates -> zero payments for all bars."""
        position = _make_position(5, value=10_000.0)
        rates = pd.Series([], dtype=float)
        payments = compute_funding_payments(position, rates, is_short=False)
        assert len(payments) == 5
        assert all(payments == 0.0)

    def test_tz_aware_position_aligned_to_naive_rates(self):
        """tz-aware position timeline is stripped and aligned to tz-naive rates."""
        position = _make_position(5, value=10_000.0, tz="UTC")  # tz-aware
        rates = _make_rates(5, rate=0.0001)  # tz-naive

        payments = compute_funding_payments(position, rates, is_short=False)

        assert len(payments) == 5
        assert all(payments < 0)  # longs pay positive rate

    def test_payments_series_has_correct_name(self):
        """Returned series has name 'funding_payment'."""
        position = _make_position(3, value=1_000.0)
        rates = _make_rates(3, rate=0.0001)
        payments = compute_funding_payments(position, rates)
        assert payments.name == "funding_payment"

    def test_magnitude_is_correct(self):
        """Payment magnitude matches: abs(payment) = position_value * abs(rate)."""
        position = _make_position(1, value=50_000.0)
        rates = _make_rates(1, rate=0.00015)

        payments_long = compute_funding_payments(position, rates, is_short=False)
        payments_short = compute_funding_payments(position, rates, is_short=True)

        expected_magnitude = 50_000.0 * 0.00015
        assert abs(abs(payments_long.iloc[0]) - expected_magnitude) < 1e-9
        assert abs(abs(payments_short.iloc[0]) - expected_magnitude) < 1e-9
        # Long and short are mirror images
        assert abs(payments_long.iloc[0] + payments_short.iloc[0]) < 1e-9


# ---------------------------------------------------------------------------
# load_funding_rates_for_backtest -- mock DB tests
# ---------------------------------------------------------------------------


class TestLoadFundingRatesForBacktest:
    """Tests for DB-backed funding rate loading via mock engine."""

    def _make_mock_engine(self, rows):
        """Return a mock SQLAlchemy engine yielding the given rows."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        conn.execute.return_value = mock_result
        return mock_engine

    def test_returns_series_from_rows(self):
        """Rows from DB are parsed into a pd.Series with DatetimeIndex."""
        ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        engine = self._make_mock_engine([(ts, 0.0001)])

        result = load_funding_rates_for_backtest(
            engine,
            "binance",
            "BTC",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 31, tzinfo=timezone.utc),
            mode="daily",
        )

        assert isinstance(result, pd.Series)
        assert len(result) == 1
        assert abs(result.iloc[0] - 0.0001) < 1e-9
        # Index must be tz-naive (MEMORY.md pitfall)
        assert result.index.tz is None

    def test_empty_rows_returns_empty_series_with_warning(self, caplog):
        """No DB rows -> empty Series + WARNING logged."""
        engine = self._make_mock_engine([])

        import logging

        with caplog.at_level(
            logging.WARNING, logger="ta_lab2.backtests.funding_adjuster"
        ):
            result = load_funding_rates_for_backtest(
                engine,
                "binance",
                "BTC",
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 31, tzinfo=timezone.utc),
            )

        assert result.empty
        assert any("No funding rates found" in r.message for r in caplog.records)

    def test_mode_daily_uses_1d_tf(self):
        """mode='daily' must pass tf='1d' filter in SQL (smoke test via mock)."""
        engine = self._make_mock_engine([])
        load_funding_rates_for_backtest(
            engine,
            "binance",
            "BTC",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 31, tzinfo=timezone.utc),
            mode="daily",
        )
        # Verify execute was called (SQL was constructed and sent)
        conn = engine.connect.return_value.__enter__.return_value
        assert conn.execute.called

    def test_db_exception_returns_empty_series_with_warning(self, caplog):
        """DB exception -> empty Series + WARNING logged (no crash)."""
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("connection refused")

        import logging

        with caplog.at_level(
            logging.WARNING, logger="ta_lab2.backtests.funding_adjuster"
        ):
            result = load_funding_rates_for_backtest(
                mock_engine,
                "binance",
                "BTC",
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 31, tzinfo=timezone.utc),
            )

        assert result.empty
        assert any("Failed to load" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# FundingAdjustedResult -- dataclass tests
# ---------------------------------------------------------------------------


class TestFundingAdjustedResult:
    """Verify FundingAdjustedResult dataclass fields are correctly populated."""

    def test_fields_accessible(self):
        """All required fields exist and are accessible."""
        equity = pd.Series([100.0, 99.0, 101.0], index=_make_daily_index(3))
        payments = pd.Series([-1.0, -1.0, -1.0], index=_make_daily_index(3))
        adj_equity = equity + payments.cumsum()

        result = FundingAdjustedResult(
            equity_adjusted=adj_equity,
            total_funding_paid=-3.0,
            total_return_adjusted=-0.03,
            sharpe_adjusted=-1.5,
            funding_payments_series=payments,
        )

        assert isinstance(result.equity_adjusted, pd.Series)
        assert isinstance(result.funding_payments_series, pd.Series)
        assert result.total_funding_paid == -3.0
        assert result.total_return_adjusted == -0.03
        assert result.sharpe_adjusted == -1.5

    def test_cumulative_funding_reduces_equity_for_long(self):
        """Long with positive funding: adjusted equity < raw equity."""
        equity = pd.Series([10_000.0] * 5, index=_make_daily_index(5))
        # Payments: -10 per bar (long pays 0.001% on 10K)
        payments = pd.Series([-10.0] * 5, index=_make_daily_index(5))
        adj_equity = equity + payments.cumsum()

        result = FundingAdjustedResult(
            equity_adjusted=adj_equity,
            total_funding_paid=float(payments.sum()),
            total_return_adjusted=_total_return(adj_equity),
            sharpe_adjusted=0.0,
            funding_payments_series=payments,
        )

        assert result.total_funding_paid == -50.0
        assert result.equity_adjusted.iloc[-1] < equity.iloc[-1]


# ---------------------------------------------------------------------------
# FundingAdjuster.adjust -- integration (mocked DB + mock vbt Portfolio)
# ---------------------------------------------------------------------------


class TestFundingAdjusterAdjust:
    """Tests for FundingAdjuster.adjust() using mock portfolio and DB."""

    def _make_mock_engine_with_rates(self, rate_rows):
        """Engine that returns specified rate rows from cmc_funding_rates."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rate_rows
        conn.execute.return_value = mock_result
        return mock_engine

    def _make_mock_portfolio(self, equity_values, tz=None):
        """Mock vbt Portfolio with a value() returning the given equity series."""
        n = len(equity_values)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        if tz:
            idx = idx.tz_localize(tz)
        equity = pd.Series(equity_values, index=idx, name="equity")
        pf = MagicMock()
        pf.value.return_value = equity
        return pf

    def test_adjust_flat_equity_zero_funding(self):
        """Zero funding rates -> adjusted equity equals raw equity."""
        engine = self._make_mock_engine_with_rates([])
        pf = self._make_mock_portfolio([10_000.0] * 10)

        adjuster = FundingAdjuster(engine, "binance", "BTC", mode="daily")
        result = adjuster.adjust(pf, is_short=False)

        assert isinstance(result, FundingAdjustedResult)
        assert len(result.equity_adjusted) == 10
        # No funding -> cumsum of 0 -> equity unchanged
        assert all(result.funding_payments_series == 0.0)

    def test_adjust_returns_correct_types(self):
        """FundingAdjustedResult fields have correct types."""
        ts = datetime(2024, 1, 1, 0, 0, 0)
        engine = self._make_mock_engine_with_rates([(ts, 0.0001)])
        pf = self._make_mock_portfolio([10_000.0] * 5)

        adjuster = FundingAdjuster(engine, "binance", "BTC")
        result = adjuster.adjust(pf, is_short=False)

        assert isinstance(result.equity_adjusted, pd.Series)
        assert isinstance(result.funding_payments_series, pd.Series)
        assert isinstance(result.total_funding_paid, float)
        assert isinstance(result.total_return_adjusted, float)
        assert isinstance(result.sharpe_adjusted, float)

    def test_adjust_empty_portfolio(self):
        """Empty portfolio equity -> FundingAdjustedResult with zeros."""
        engine = self._make_mock_engine_with_rates([])
        pf = MagicMock()
        pf.value.return_value = pd.Series([], dtype=float)

        adjuster = FundingAdjuster(engine, "binance", "BTC")
        result = adjuster.adjust(pf)

        assert result.equity_adjusted.empty
        assert result.total_funding_paid == 0.0
        assert result.total_return_adjusted == 0.0

    def test_adjust_long_with_positive_rate_reduces_equity(self):
        """Long + positive funding -> cumulative funding is negative -> equity reduced."""
        ts_list = [
            datetime(2024, 1, 1),
            datetime(2024, 1, 2),
            datetime(2024, 1, 3),
        ]
        rows = [(ts, 0.001) for ts in ts_list]  # 0.1% daily
        engine = self._make_mock_engine_with_rates(rows)
        pf = self._make_mock_portfolio([10_000.0, 10_000.0, 10_000.0])

        adjuster = FundingAdjuster(engine, "binance", "BTC")
        result = adjuster.adjust(pf, is_short=False)

        # Long pays positive rate -> total_funding_paid < 0
        assert result.total_funding_paid < 0
        # Adjusted equity should be less than raw at end
        raw_end = 10_000.0
        assert result.equity_adjusted.iloc[-1] < raw_end


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class TestPrivateHelpers:
    """Tests for _strip_tz, _total_return, _sharpe_daily."""

    def test_strip_tz_removes_utc(self):
        """tz-aware DatetimeIndex -> tz-naive."""
        idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
        stripped = _strip_tz(idx)
        assert stripped.tz is None

    def test_strip_tz_naive_unchanged(self):
        """tz-naive index is returned as-is."""
        idx = pd.date_range("2024-01-01", periods=3, freq="D")
        stripped = _strip_tz(idx)
        assert stripped.tz is None
        assert len(stripped) == 3

    def test_total_return_flat(self):
        """Flat equity -> 0% return."""
        equity = pd.Series([100.0, 100.0, 100.0])
        assert _total_return(equity) == 0.0

    def test_total_return_positive(self):
        """Rising equity -> positive return."""
        equity = pd.Series([100.0, 110.0])
        assert abs(_total_return(equity) - 0.10) < 1e-9

    def test_total_return_empty(self):
        """Empty equity -> 0.0."""
        assert _total_return(pd.Series([], dtype=float)) == 0.0

    def test_sharpe_daily_constant_returns_zero(self):
        """Constant equity (zero std) -> Sharpe = 0."""
        equity = pd.Series([100.0] * 5)
        assert _sharpe_daily(equity) == 0.0

    def test_sharpe_daily_single_bar(self):
        """Single bar -> Sharpe = 0 (not enough data)."""
        assert _sharpe_daily(pd.Series([100.0])) == 0.0

    def test_sharpe_daily_positive_for_trending_up(self):
        """Steadily rising equity -> positive Sharpe."""
        equity = pd.Series([100.0 + i * 0.5 for i in range(50)])
        sharpe = _sharpe_daily(equity)
        assert sharpe > 0.0
