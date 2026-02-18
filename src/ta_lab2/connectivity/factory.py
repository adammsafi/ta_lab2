# src/ta_lab2/connectivity/factory.py

from .base import ExchangeInterface
from .binance import BinanceExchange
from .coinbase import CoinbaseExchange
from .bitfinex import BitfinexExchange
from .bitstamp import BitstampExchange
from .kraken import KrakenExchange
from .hyperliquid import HyperliquidExchange  # Import the new HyperliquidExchange class


def get_exchange(name: str, **credentials) -> ExchangeInterface:
    """
    Factory function to get an exchange interface instance.
    :param name: The name of the exchange.
    :param credentials: Keyword arguments for exchange-specific credentials.
    :return: An instance of the ExchangeInterface for the specified exchange.
    :raises ValueError: If the exchange name is not supported.
    """
    if name.lower() == "binance":
        return BinanceExchange(**credentials)
    elif name.lower() == "coinbase":
        return CoinbaseExchange(**credentials)
    elif name.lower() == "bitfinex":
        return BitfinexExchange(**credentials)
    elif name.lower() == "bitstamp":
        return BitstampExchange(**credentials)
    elif name.lower() == "kraken":
        return KrakenExchange(**credentials)
    elif name.lower() == "hyperliquid":  # Add condition for Hyperliquid
        return HyperliquidExchange(**credentials)
    else:
        raise ValueError(f"Exchange '{name}' not supported.")
