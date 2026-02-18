# tests/test_connectivity.py

from ta_lab2.connectivity.factory import get_exchange


# Test for Binance (currently expected to fail due to 451 error if no VPN, or pass with ETH/USDT)
def test_binance_get_ticker():
    """
    Tests fetching ticker data from Binance.
    """
    binance = get_exchange("binance")
    # Using ETH/USDT as BTC/USD might be restricted
    ticker = binance.get_ticker("ETH/USDT")
    assert "last_price" in ticker
    assert isinstance(ticker["last_price"], float)
    print(f"Binance ETH/USDT Ticker: {ticker}")


def test_binance_get_order_book():
    """
    Tests fetching order book data from Binance.
    """
    binance = get_exchange("binance")
    # Using ETH/USDT as BTC/USD might be restricted
    order_book = binance.get_order_book("ETH/USDT", depth=10)
    assert "bids" in order_book
    assert "asks" in order_book
    assert isinstance(order_book["bids"], list)
    assert isinstance(order_book["asks"], list)
    assert all(
        isinstance(level, list) and len(level) == 2 for level in order_book["bids"]
    )
    print(f"Binance ETH/USDT Order Book (top 10 bids): {order_book['bids'][:10]}")


def test_binance_get_historical_klines():
    """
    Tests fetching historical kline data from Binance.
    """
    import time

    binance = get_exchange("binance")
    end_time = int(time.time())
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago

    klines = binance.get_historical_klines("ETH/USDT", "1h", start_time, end_time)
    assert isinstance(klines, list)
    assert len(klines) > 0
    assert all(isinstance(kline, list) and len(kline) == 6 for kline in klines)
    print(f"Binance ETH/USDT 1h klines (first 5): {klines[:5]}")


# New tests for Coinbase Exchange
def test_coinbase_get_ticker():
    """
    Tests fetching ticker data from Coinbase Exchange.
    """
    coinbase = get_exchange("coinbase")
    ticker = coinbase.get_ticker("BTC/USD")
    assert "last_price" in ticker
    assert isinstance(ticker["last_price"], float)
    print(f"Coinbase BTC/USD Ticker: {ticker}")


def test_coinbase_get_order_book():
    """
    Tests fetching order book data from Coinbase Exchange.
    """
    coinbase = get_exchange("coinbase")
    order_book = coinbase.get_order_book(
        "BTC/USD", depth=10
    )  # Depth will be mapped to Coinbase's level
    assert "bids" in order_book
    assert "asks" in order_book
    assert isinstance(order_book["bids"], list)
    assert isinstance(order_book["asks"], list)
    assert all(
        isinstance(level, list) and len(level) == 2 for level in order_book["bids"]
    )
    print(f"Coinbase BTC/USD Order Book (top 10 bids): {order_book['bids'][:10]}")


def test_coinbase_get_historical_klines():
    """
    Tests fetching historical kline data from Coinbase Exchange.
    """
    import time

    coinbase = get_exchange("coinbase")
    end_time = int(time.time())
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago

    klines = coinbase.get_historical_klines("BTC/USD", "1h", start_time, end_time)
    assert isinstance(klines, list)
    assert len(klines) > 0
    assert all(isinstance(kline, list) and len(kline) == 6 for kline in klines)
    print(f"Coinbase BTC/USD 1h klines (first 5): {klines[:5]}")


# New tests for Bitfinex
def test_bitfinex_get_ticker():
    """
    Tests fetching ticker data from Bitfinex.
    """
    bitfinex = get_exchange("bitfinex")
    ticker = bitfinex.get_ticker("BTC/USD")
    assert "last_price" in ticker
    assert isinstance(ticker["last_price"], float)
    print(f"Bitfinex BTC/USD Ticker: {ticker}")


def test_bitfinex_get_order_book():
    """
    Tests fetching order book data from Bitfinex.
    """
    bitfinex = get_exchange("bitfinex")
    order_book = bitfinex.get_order_book("BTC/USD", depth=10)
    assert "bids" in order_book
    assert "asks" in order_book
    assert isinstance(order_book["bids"], list)
    assert isinstance(order_book["asks"], list)
    assert all(
        isinstance(level, list) and len(level) == 2 for level in order_book["bids"]
    )
    print(f"Bitfinex BTC/USD Order Book (top 10 bids): {order_book['bids'][:10]}")


def test_bitfinex_get_historical_klines():
    """
    Tests fetching historical kline data from Bitfinex.
    """
    import time

    bitfinex = get_exchange("bitfinex")
    end_time = int(time.time())
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago

    klines = bitfinex.get_historical_klines("BTC/USD", "1h", start_time, end_time)
    assert isinstance(klines, list)
    assert len(klines) > 0
    assert all(isinstance(kline, list) and len(kline) == 6 for kline in klines)
    print(f"Bitfinex BTC/USD 1h klines (first 5): {klines[:5]}")


# New tests for Bitstamp
def test_bitstamp_get_ticker():
    """
    Tests fetching ticker data from Bitstamp.
    """
    bitstamp = get_exchange("bitstamp")
    ticker = bitstamp.get_ticker("BTC/USD")
    assert "last_price" in ticker
    assert isinstance(ticker["last_price"], float)
    print(f"Bitstamp BTC/USD Ticker: {ticker}")


def test_bitstamp_get_order_book():
    """
    Tests fetching order book data from Bitstamp.
    """
    bitstamp = get_exchange("bitstamp")
    order_book = bitstamp.get_order_book("BTC/USD", depth=10)
    assert "bids" in order_book
    assert "asks" in order_book
    assert isinstance(order_book["bids"], list)
    assert isinstance(order_book["asks"], list)
    assert all(
        isinstance(level, list) and len(level) == 2 for level in order_book["bids"]
    )
    print(f"Bitstamp BTC/USD Order Book (top 10 bids): {order_book['bids'][:10]}")


def test_bitstamp_get_historical_klines():
    """
    Tests fetching historical kline data from Bitstamp.
    """
    import time

    bitstamp = get_exchange("bitstamp")
    end_time = int(time.time())
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago

    klines = bitstamp.get_historical_klines("BTC/USD", "1h", start_time, end_time)
    assert isinstance(klines, list)
    assert len(klines) > 0
    assert all(isinstance(kline, list) and len(kline) == 6 for kline in klines)
    print(f"Bitstamp BTC/USD 1h klines (first 5): {klines[:5]}")


# New tests for Kraken
def test_kraken_get_ticker():
    """
    Tests fetching ticker data from Kraken.
    """
    kraken = get_exchange("kraken")
    ticker = kraken.get_ticker("BTC/USD")
    assert "last_price" in ticker
    assert isinstance(ticker["last_price"], float)
    print(f"Kraken BTC/USD Ticker: {ticker}")


def test_kraken_get_order_book():
    """
    Tests fetching order book data from Kraken.
    """
    kraken = get_exchange("kraken")
    order_book = kraken.get_order_book("BTC/USD", depth=10)
    assert "bids" in order_book
    assert "asks" in order_book
    assert isinstance(order_book["bids"], list)
    assert isinstance(order_book["asks"], list)
    assert all(
        isinstance(level, list) and len(level) == 2 for level in order_book["bids"]
    )
    print(f"Kraken BTC/USD Order Book (top 10 bids): {order_book['bids'][:10]}")


def test_kraken_get_historical_klines():
    """
    Tests fetching historical kline data from Kraken.
    """
    import time

    kraken = get_exchange("kraken")
    end_time = int(time.time())
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago

    klines = kraken.get_historical_klines("BTC/USD", "1h", start_time, end_time)
    assert isinstance(klines, list)
    assert len(klines) > 0
    assert all(isinstance(kline, list) and len(kline) == 6 for kline in klines)
    print(f"Kraken BTC/USD 1h klines (first 5): {klines[:5]}")


# New test for Hyperliquid
def test_hyperliquid_get_historical_klines():
    """
    Tests fetching historical kline data from Hyperliquid.
    """
    import time

    hyperliquid = get_exchange("hyperliquid")
    end_time = int(time.time())
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago

    klines = hyperliquid.get_historical_klines("BTC/USD", "1h", start_time, end_time)
    assert isinstance(klines, list)
    assert len(klines) > 0
    assert all(isinstance(kline, list) and len(kline) == 6 for kline in klines)
    print(f"Hyperliquid BTC/USD 1h klines (first 5): {klines[:5]}")


# You can run these tests using pytest:
# pytest tests/test_connectivity.py
