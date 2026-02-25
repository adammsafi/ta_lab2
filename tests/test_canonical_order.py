"""
Unit tests for CanonicalOrder dataclass.

All tests are pure unit tests - no network calls, no database.
Tests cover: to_exchange for coinbase/kraken formats (market/limit/stop),
validate() error cases, from_signal with aliases, unknown exchange,
client_order_id uniqueness, ETH pair handling.
"""

import pytest

from ta_lab2.paper_trading.canonical_order import CanonicalOrder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_market_order(**kwargs):
    defaults = dict(pair="BTC/USD", side="buy", order_type="market", quantity=0.01)
    defaults.update(kwargs)
    return CanonicalOrder(**defaults)


def make_limit_order(**kwargs):
    defaults = dict(
        pair="BTC/USD",
        side="buy",
        order_type="limit",
        quantity=0.01,
        limit_price=50000.0,
    )
    defaults.update(kwargs)
    return CanonicalOrder(**defaults)


def make_stop_order(**kwargs):
    defaults = dict(
        pair="BTC/USD",
        side="sell",
        order_type="stop",
        quantity=0.01,
        stop_price=45000.0,
    )
    defaults.update(kwargs)
    return CanonicalOrder(**defaults)


# ---------------------------------------------------------------------------
# validate() error cases
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_market_order_passes(self):
        order = make_market_order()
        order.validate()  # should not raise

    def test_valid_limit_order_passes(self):
        order = make_limit_order()
        order.validate()

    def test_valid_stop_order_passes(self):
        order = make_stop_order()
        order.validate()

    def test_invalid_side_raises(self):
        order = CanonicalOrder(
            pair="BTC/USD", side="hold", order_type="market", quantity=0.01
        )
        with pytest.raises(ValueError, match="Invalid side"):
            order.validate()

    def test_invalid_order_type_raises(self):
        order = CanonicalOrder(
            pair="BTC/USD", side="buy", order_type="twap", quantity=0.01
        )
        with pytest.raises(ValueError, match="Invalid order_type"):
            order.validate()

    def test_zero_quantity_raises(self):
        order = CanonicalOrder(
            pair="BTC/USD", side="buy", order_type="market", quantity=0.0
        )
        with pytest.raises(ValueError, match="quantity must be positive"):
            order.validate()

    def test_negative_quantity_raises(self):
        order = CanonicalOrder(
            pair="BTC/USD", side="buy", order_type="market", quantity=-1.0
        )
        with pytest.raises(ValueError, match="quantity must be positive"):
            order.validate()

    def test_limit_order_without_limit_price_raises(self):
        order = CanonicalOrder(
            pair="BTC/USD", side="buy", order_type="limit", quantity=0.01
        )
        with pytest.raises(ValueError, match="limit_price is required"):
            order.validate()

    def test_stop_order_without_stop_price_raises(self):
        order = CanonicalOrder(
            pair="BTC/USD", side="sell", order_type="stop", quantity=0.01
        )
        with pytest.raises(ValueError, match="stop_price is required"):
            order.validate()

    def test_limit_order_with_limit_price_passes(self):
        order = CanonicalOrder(
            pair="BTC/USD",
            side="buy",
            order_type="limit",
            quantity=0.01,
            limit_price=50000.0,
        )
        order.validate()  # should not raise

    def test_stop_order_with_stop_price_passes(self):
        order = CanonicalOrder(
            pair="BTC/USD",
            side="sell",
            order_type="stop",
            quantity=0.01,
            stop_price=45000.0,
        )
        order.validate()  # should not raise


# ---------------------------------------------------------------------------
# to_exchange - Coinbase format
# ---------------------------------------------------------------------------


class TestToExchangeCoinbase:
    def test_market_order_structure(self):
        order = make_market_order(quantity=0.5)
        payload = order.to_exchange("coinbase")
        assert payload["product_id"] == "BTC-USD"
        assert payload["side"] == "BUY"
        assert "market_market_ioc" in payload["order_configuration"]
        assert payload["order_configuration"]["market_market_ioc"]["base_size"] == "0.5"

    def test_market_sell_order(self):
        order = make_market_order(side="sell", quantity=0.1)
        payload = order.to_exchange("coinbase")
        assert payload["side"] == "SELL"
        assert "market_market_ioc" in payload["order_configuration"]

    def test_limit_order_structure(self):
        order = make_limit_order(quantity=0.01, limit_price=50000.0)
        payload = order.to_exchange("coinbase")
        assert payload["product_id"] == "BTC-USD"
        assert payload["side"] == "BUY"
        cfg = payload["order_configuration"]
        assert "limit_limit_gtc" in cfg
        assert cfg["limit_limit_gtc"]["base_size"] == "0.01"
        assert cfg["limit_limit_gtc"]["limit_price"] == "50000.0"

    def test_stop_order_structure(self):
        order = make_stop_order(stop_price=45000.0, limit_price=44500.0)
        payload = order.to_exchange("coinbase")
        cfg = payload["order_configuration"]
        assert "stop_limit_stop_limit_gtc" in cfg
        stop_cfg = cfg["stop_limit_stop_limit_gtc"]
        assert stop_cfg["stop_price"] == "45000.0"
        assert stop_cfg["limit_price"] == "44500.0"

    def test_stop_order_limit_price_falls_back_to_stop_price(self):
        """When stop order has no limit_price, limit_price falls back to stop_price."""
        order = make_stop_order(stop_price=45000.0, limit_price=None)
        payload = order.to_exchange("coinbase")
        cfg = payload["order_configuration"]["stop_limit_stop_limit_gtc"]
        assert cfg["limit_price"] == "45000.0"

    def test_client_order_id_present(self):
        order = make_market_order()
        payload = order.to_exchange("coinbase")
        assert "client_order_id" in payload
        assert payload["client_order_id"] == order.client_order_id

    def test_pair_slash_converted_to_dash(self):
        order = make_market_order(pair="ETH/USD")
        payload = order.to_exchange("coinbase")
        assert payload["product_id"] == "ETH-USD"

    def test_pair_uppercased(self):
        order = make_market_order(pair="btc/usd")
        payload = order.to_exchange("coinbase")
        assert payload["product_id"] == "BTC-USD"

    def test_coinbase_case_insensitive(self):
        order = make_market_order()
        assert order.to_exchange("COINBASE") == order.to_exchange("coinbase")

    def test_eth_pair_coinbase(self):
        order = CanonicalOrder(
            pair="ETH/USD", side="buy", order_type="market", quantity=1.0
        )
        payload = order.to_exchange("coinbase")
        assert payload["product_id"] == "ETH-USD"
        assert "market_market_ioc" in payload["order_configuration"]


# ---------------------------------------------------------------------------
# to_exchange - Kraken format
# ---------------------------------------------------------------------------


class TestToExchangeKraken:
    def test_market_order_structure(self):
        order = make_market_order(quantity=0.5)
        payload = order.to_exchange("kraken")
        assert payload["pair"] == "XBTUSD"  # BTC -> XBT, no slash
        assert payload["type"] == "buy"
        assert payload["ordertype"] == "market"
        assert payload["volume"] == "0.5"

    def test_limit_order_structure(self):
        order = make_limit_order(quantity=0.01, limit_price=50000.0)
        payload = order.to_exchange("kraken")
        assert payload["ordertype"] == "limit"
        assert payload["price"] == "50000.0"
        assert payload["volume"] == "0.01"

    def test_stop_order_structure(self):
        order = make_stop_order(stop_price=45000.0, limit_price=44500.0)
        payload = order.to_exchange("kraken")
        assert payload["ordertype"] == "stop-loss-limit"
        assert payload["price"] == "45000.0"  # stop trigger
        assert payload["price2"] == "44500.0"  # limit execution price

    def test_stop_order_price2_falls_back_to_stop(self):
        order = make_stop_order(stop_price=45000.0, limit_price=None)
        payload = order.to_exchange("kraken")
        assert payload["price2"] == "45000.0"

    def test_btc_converted_to_xbt(self):
        order = make_market_order(pair="BTC/USD")
        payload = order.to_exchange("kraken")
        assert payload["pair"] == "XBTUSD"

    def test_eth_pair_no_substitution(self):
        order = CanonicalOrder(
            pair="ETH/USD", side="buy", order_type="market", quantity=1.0
        )
        payload = order.to_exchange("kraken")
        assert payload["pair"] == "ETHUSD"

    def test_slash_removed(self):
        order = make_market_order(pair="ETH/USD")
        payload = order.to_exchange("kraken")
        assert "/" not in payload["pair"]

    def test_sell_side(self):
        order = make_market_order(side="sell")
        payload = order.to_exchange("kraken")
        assert payload["type"] == "sell"

    def test_kraken_case_insensitive(self):
        order = make_market_order()
        assert order.to_exchange("KRAKEN") == order.to_exchange("kraken")


# ---------------------------------------------------------------------------
# to_exchange - unknown exchange
# ---------------------------------------------------------------------------


class TestToExchangeUnknown:
    def test_unknown_exchange_raises_value_error(self):
        order = make_market_order()
        with pytest.raises(ValueError, match="Unknown exchange"):
            order.to_exchange("binance")

    def test_error_message_contains_exchange_name(self):
        order = make_market_order()
        with pytest.raises(ValueError, match="ftx"):
            order.to_exchange("ftx")


# ---------------------------------------------------------------------------
# client_order_id uniqueness
# ---------------------------------------------------------------------------


class TestClientOrderId:
    def test_client_order_id_is_unique_across_instances(self):
        orders = [make_market_order() for _ in range(10)]
        ids = [o.client_order_id for o in orders]
        assert len(set(ids)) == 10, "All client_order_ids should be unique"

    def test_client_order_id_is_string(self):
        order = make_market_order()
        assert isinstance(order.client_order_id, str)

    def test_custom_client_order_id_respected(self):
        order = CanonicalOrder(
            pair="BTC/USD",
            side="buy",
            order_type="market",
            quantity=0.01,
            client_order_id="custom-id-123",
        )
        payload = order.to_exchange("coinbase")
        assert payload["client_order_id"] == "custom-id-123"


# ---------------------------------------------------------------------------
# from_signal factory
# ---------------------------------------------------------------------------


class TestFromSignal:
    def test_basic_signal_dict(self):
        signal = {"pair": "BTC/USD", "side": "buy", "quantity": 0.01}
        order = CanonicalOrder.from_signal(signal)
        assert order.pair == "BTC/USD"
        assert order.side == "buy"
        assert order.quantity == 0.01

    def test_uses_direction_alias(self):
        signal = {"pair": "BTC/USD", "direction": "Long", "quantity": 0.01}
        order = CanonicalOrder.from_signal(signal)
        assert order.side == "buy"

    def test_long_maps_to_buy(self):
        signal = {"pair": "BTC/USD", "direction": "Long", "quantity": 0.01}
        order = CanonicalOrder.from_signal(signal)
        assert order.side == "buy"

    def test_short_maps_to_sell(self):
        signal = {"pair": "ETH/USD", "direction": "SHORT", "quantity": 1.0}
        order = CanonicalOrder.from_signal(signal)
        assert order.side == "sell"

    def test_buy_uppercase_maps_to_buy(self):
        signal = {"pair": "BTC/USD", "side": "BUY", "quantity": 0.01}
        order = CanonicalOrder.from_signal(signal)
        assert order.side == "buy"

    def test_sell_uppercase_maps_to_sell(self):
        signal = {"pair": "BTC/USD", "side": "SELL", "quantity": 0.01}
        order = CanonicalOrder.from_signal(signal)
        assert order.side == "sell"

    def test_uses_size_alias_for_quantity(self):
        signal = {"pair": "BTC/USD", "side": "buy", "size": 2.5}
        order = CanonicalOrder.from_signal(signal)
        assert order.quantity == 2.5

    def test_default_order_type_is_market(self):
        signal = {"pair": "BTC/USD", "side": "buy", "quantity": 0.01}
        order = CanonicalOrder.from_signal(signal)
        assert order.order_type == "market"

    def test_order_type_from_signal(self):
        signal = {
            "pair": "BTC/USD",
            "side": "buy",
            "quantity": 0.01,
            "order_type": "limit",
            "limit_price": 50000.0,
        }
        order = CanonicalOrder.from_signal(signal)
        assert order.order_type == "limit"

    def test_limit_price_from_signal(self):
        signal = {
            "pair": "BTC/USD",
            "side": "buy",
            "quantity": 0.01,
            "order_type": "limit",
            "limit_price": 50000.0,
        }
        order = CanonicalOrder.from_signal(signal)
        assert order.limit_price == 50000.0

    def test_stop_price_from_signal(self):
        signal = {
            "pair": "BTC/USD",
            "side": "sell",
            "quantity": 0.01,
            "order_type": "stop",
            "stop_price": 45000.0,
        }
        order = CanonicalOrder.from_signal(signal)
        assert order.stop_price == 45000.0

    def test_signal_id_stored(self):
        signal = {"pair": "BTC/USD", "side": "buy", "quantity": 0.01, "signal_id": 42}
        order = CanonicalOrder.from_signal(signal)
        assert order.signal_id == 42

    def test_asset_id_stored(self):
        signal = {"pair": "BTC/USD", "side": "buy", "quantity": 0.01, "asset_id": 7}
        order = CanonicalOrder.from_signal(signal)
        assert order.asset_id == 7

    def test_missing_pair_raises(self):
        signal = {"side": "buy", "quantity": 0.01}
        with pytest.raises(ValueError, match="pair"):
            CanonicalOrder.from_signal(signal)

    def test_missing_side_and_direction_raises(self):
        signal = {"pair": "BTC/USD", "quantity": 0.01}
        with pytest.raises(ValueError, match="side.*direction|direction.*side"):
            CanonicalOrder.from_signal(signal)

    def test_missing_quantity_and_size_raises(self):
        signal = {"pair": "BTC/USD", "side": "buy"}
        with pytest.raises(ValueError, match="quantity.*size|size.*quantity"):
            CanonicalOrder.from_signal(signal)

    def test_invalid_direction_raises(self):
        signal = {"pair": "BTC/USD", "direction": "hold", "quantity": 0.01}
        with pytest.raises(ValueError, match="Cannot normalize"):
            CanonicalOrder.from_signal(signal)

    def test_eth_pair_via_from_signal(self):
        signal = {"pair": "ETH/USD", "side": "buy", "quantity": 1.5}
        order = CanonicalOrder.from_signal(signal)
        kraken_payload = order.to_exchange("kraken")
        assert kraken_payload["pair"] == "ETHUSD"
        coinbase_payload = order.to_exchange("coinbase")
        assert coinbase_payload["product_id"] == "ETH-USD"

    def test_quantity_coerced_to_float(self):
        signal = {"pair": "BTC/USD", "side": "buy", "quantity": "0.01"}
        order = CanonicalOrder.from_signal(signal)
        assert isinstance(order.quantity, float)
        assert order.quantity == 0.01

    def test_size_coerced_to_float(self):
        signal = {"pair": "BTC/USD", "side": "buy", "size": "2"}
        order = CanonicalOrder.from_signal(signal)
        assert isinstance(order.quantity, float)
        assert order.quantity == 2.0


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_contains_pair_side_type_quantity(self):
        order = make_market_order(pair="BTC/USD", side="buy", quantity=0.5)
        r = repr(order)
        assert "BTC/USD" in r
        assert "buy" in r
        assert "market" in r
