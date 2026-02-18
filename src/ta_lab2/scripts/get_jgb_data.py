from tvdatafeed import TvDatafeed, Interval

# Initialize TvDatafeed without credentials for now
# If you encounter issues with data retrieval, you might need to provide your TradingView username and password:
# tv = TvDatafeed(username='your_tradingview_username', password='your_tradingview_password')
tv = TvDatafeed()

# Define the symbol for Japanese 10-Year Government Bond Yield
# Common symbols for JGBs might vary, trying a few common ones.
# We'll start with what seems most likely.
# For bond yields, the exchange might be 'JPX' or 'FX_IDC' or simply not required if it's a global index.
# Let's try to get data for 'JP10Y' (Japan 10 Year Yield)

# Example 1: Trying a common symbol for 10-year JGB, often found on global indices or specific exchanges
symbol = "JP10Y"
exchange = "FX_IDC"  # FX_IDC often hosts global indices and bond yields

print(f"Attempting to fetch data for {symbol} from {exchange}...")

try:
    df = tv.get_hist(
        symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=5000
    )

    if df is not None:
        print(f"Successfully fetched {len(df)} bars for {symbol} from {exchange}:")
        print(df.head())
        print("Tail:")
        print(df.tail())

        # Save to CSV for easy viewing
        df.to_csv(f"{symbol}_{exchange}_daily.csv")
        print(f"Data saved to {symbol}_{exchange}_daily.csv")
    else:
        print(f"No data returned for {symbol} from {exchange}.")
        print(
            "This could mean the symbol/exchange combination is incorrect, or credentials might be needed."
        )

except Exception as e:
    print(f"An error occurred: {e}")

print(
    "\nTrying another common symbol if the first attempt fails or is not comprehensive."
)

# Example 2: Another common symbol might be from a different exchange or symbol convention
symbol_alt = "JGB10Y"
exchange_alt = "JPX"  # Japan Exchange Group, though bond yields might not be directly on a stock exchange

print(f"\nAttempting to fetch data for {symbol_alt} from {exchange_alt}...")

try:
    df_alt = tv.get_hist(
        symbol=symbol_alt,
        exchange=exchange_alt,
        interval=Interval.in_daily,
        n_bars=5000,
    )

    if df_alt is not None:
        print(
            f"Successfully fetched {len(df_alt)} bars for {symbol_alt} from {exchange_alt}:"
        )
        print(df_alt.head())
        print("Tail:")
        print(df_alt.tail())

        # Save to CSV for easy viewing
        df_alt.to_csv(f"{symbol_alt}_{exchange_alt}_daily.csv")
        print(f"Data saved to {symbol_alt}_{exchange_alt}_daily.csv")
    else:
        print(f"No data returned for {symbol_alt} from {exchange_alt}.")
        print(
            "This could mean the symbol/exchange combination is incorrect, or credentials might be needed."
        )

except Exception as e:
    print(f"An error occurred: {e}")

print("\nIf no data was retrieved, you might need to:")
print(
    "1. Find the exact symbol on TradingView for the Japanese bond yield you're interested in."
)
print("2. Provide your TradingView username and password when initializing TvDatafeed.")
print("   Example: tv = TvDatafeed(username='your_username', password='your_password')")
