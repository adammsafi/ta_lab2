---
title: "soFarInMyOwnWords"
author: "Adam Safi"
created: 2025-11-08T18:27:00+00:00
modified: 2025-11-08T21:22:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Plans&Status\soFarInMyOwnWords.docx"
original_size_bytes: 25836
---
1. Pulled historical data from
   https://coinmarketcap.com/currencies/bitcoin/historical-data/ for
   BTC\_USD at a daily granularity in .csv – currently the file is
   from:2016\_01\_01 to:2025\_10\_26

   1. Located @
      C:\Users\asafi\Downloads\ta\_lab2\data\Bitcoin\_01\_1\_2016-10\_26\_2025\_historical\_data\_coinmarketcap.csv
   2. Fields:

      1. timeOpen
      2. timeClose
      3. timeHigh
      4. timeLow
      5. name
      6. open
      7. high
      8. low
      9. close
      10. volume
      11. marketCap
      12. timestamp
2. I then worked on developing two python files BTC Price
   Analysis.py and Data\_Analysis\_Functions.py

   1. Located @C:\Users\asafi\Downloads\ta\_lab\Old\BTC Price
      Analysis.py and
      C:\Users\asafi\Downloads\ta\_lab\Old\Data\_Analysis\_Functions.py
   2. BTC Price Analysis.py is an end-to-end analysis script that:

      1. Loads your BTC OHLCV CSV, cleans column names, and duplicates it
         to a working df2.
      2. Expands timestamp columns (timeopen, timeclose, timehigh,
         timelow) into rich date/time features.
      3. Computes simple % returns and log returns (bar-to-bar +
         intraday).
      4. Builds multiple volatility measures (rolling stdev of log
         returns; Parkinson, Garman-Klass, Rogers–Satchell; ATR).
      5. Adds EMAs for open/high/low/close at 21/50/100/200, plus first
         (slope) and second (curvature) derivatives, and helper flags like slope
         sign “flips.”
      6. Produces plots (per-EMA panels and consolidated views), and
         computes/plots EMA comovement regimes and flip-segment stats (durations,
         returns, histos).
   3. Data\_Analysis\_Functions.py is a reusable library your script
      imports that provides:

      1. Cleaning & time features: drop duplicate timestamp column;
         expand timestamps to year/month/day, weekday, quarters, optional season
         and moon phase.
      2. Return math: bar-to-bar simple and log deltas (incl. intraday),
         with rounding and orientation control (newest-on-top vs
         oldest-on-top).
      3. Volatility toolset: rolling log-ret stdev (annualized),
         Parkinson, Garman-Klass, Rogers–Satchell, and ATR (Wilder/SMA/EMA), all
         orientation-safe.
      4. EMA utilities: add EMAs in batch; compute d1 (slope) and d2
         (curvature); scale slopes (bps/percent); detect trend flips with
         alignment options (“older/newer/actionable”).
      5. Regime & segment analytics: build flip segments (with
         duration, returns, max drawdown/run-up, slope stats), compute EMA
         comovement regimes (ALL\_UP / ALL\_DOWN / detailed MIXED strings) and
         summarize hit rates/returns, plus plotting helpers for regimes and EMA
         views.
3. After standing up and working on these two files for a few weeks,
   it became clear that continuing to work on just two files was
   unmanageable for the functionality and complexity of what I was trying
   to develop, so I developed ta\_lab as a package to better develop the
   project. ta\_lab was quickly replaced with tab\_lab2

   1. Located at C:\Users\asafi\Downloads\ta\_lab2

List of ta\_lib2 Commits

![](./media/image1.emf)

4. Once ta\_lib2 was in an okay spot, I wanted to shift focus to
   complete a POC for:

   1. Pulling data from an API on my local machine and saving it to a
      database table, this became known as fedtools2

      1. Located at C:\Users\asafi\Downloads\fedtools2
   2. This also led to the creation of the following directories:

      1. C:\Users\asafi\Downloads\Data\_Tools
      2. C:\Users\asafi\Downloads\ETL
      3. C:\Users\asafi\Downloads\FinancialData
      4. C:\Users\asafi\Downloads\FinancialData\FedData
   3. Using the cloud

      1. Creating a VM
      2. Creating a database in the VM
      3. Writing a script to pull data from an API and then saving it into
         a database
      4. Writing a set of timers to automate hitting the API and updating
         the database
      5. Connecting to the database from my local machine
5. There are still open items, but this project be