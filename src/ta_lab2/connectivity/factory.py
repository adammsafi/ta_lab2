# src/ta_lab2/connectivity/factory.py

from __future__ import annotations

from typing import Optional

from .base import ExchangeInterface
from .binance import BinanceExchange
from .coinbase import CoinbaseExchange
from .bitfinex import BitfinexExchange
from .bitstamp import BitstampExchange
from .kraken import KrakenExchange
from .hyperliquid import HyperliquidExchange  # Import the new HyperliquidExchange class
from .exchange_config import ExchangeConfig


def get_exchange(
    name: str,
    config: Optional[ExchangeConfig] = None,
    **credentials,
) -> ExchangeInterface:
    """
    Factory function to get an exchange interface instance.

    Parameters
    ----------
    name : str
        The name of the exchange (case-insensitive).
    config : ExchangeConfig, optional
        If provided, credentials and environment are loaded from the config object.
        Direct ``credentials`` keyword arguments are passed alongside and will
        override config values in adapters that accept both.
    **credentials
        Additional keyword arguments forwarded to the adapter constructor.

    Returns
    -------
    ExchangeInterface
        An instance of the exchange adapter for the specified exchange.

    Raises
    ------
    ValueError
        If the exchange name is not supported.
    """
    kwargs = dict(credentials)
    if config is not None:
        kwargs["config"] = config

    if name.lower() == "binance":
        return BinanceExchange(**kwargs)
    elif name.lower() == "coinbase":
        return CoinbaseExchange(**kwargs)
    elif name.lower() == "bitfinex":
        return BitfinexExchange(**kwargs)
    elif name.lower() == "bitstamp":
        return BitstampExchange(**kwargs)
    elif name.lower() == "kraken":
        return KrakenExchange(**kwargs)
    elif name.lower() == "hyperliquid":  # Add condition for Hyperliquid
        return HyperliquidExchange(**kwargs)
    else:
        raise ValueError(f"Exchange '{name}' not supported.")
