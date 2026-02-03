---
title: "ta_lab2_GenesisFiles_Summary"
author: "Adam Safi"
created: 2025-10-27T16:10:00+00:00
modified: 2025-11-17T21:05:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Foundational\ta_lab2_GenesisFiles_Summary.docx"
original_size_bytes: 23306
---
Hello! I have reviewed the two Python files you provided: BTC Price
Analysis.py and Data\_Analysis\_Functions.py.

This is a comprehensive and well-structured quantitative analysis
pipeline for Bitcoin historical data. The main script, BTC Price
Analysis.py, serves as the "driver" that uses the custom library,
Data\_Analysis\_Functions.py, to perform a deep-dive analysis,
particularly focused on Exponential Moving Averages (EMAs).

Here is a detailed breakdown of what the code does.

**BTC Price Analysis.py (The Main Script)**

This script executes the analysis workflow from start to finish.

1. **Data Loading & Preparation:**

   * Loads a Bitcoin historical data CSV file.
   * Cleans column names (lowercase, strip whitespace).
   * Calculates simple price range columns (close-open and range
     (high-low)).
2. **Feature Engineering (Returns &
   Volatility):**

   * Calculates simple percent returns (b2t\_pct\_delta) and log returns
     (b2t\_log\_delta) for the OHLC data.
   * Calculates rolling standard deviation of log returns
     (add\_logret\_stdev\_vol) as a baseline volatility measure.
   * Calculates three more advanced volatility estimators over 30, 60,
     and 90-day windows:

     + **Parkinson Volatility** (uses High-Low
       prices).
     + **Garman-Klass Volatility** (uses
       Open-High-Low-Close).
     + **Rogers-Satchell Volatility** (also uses OHLC,
       robust to trends/drift).
   * Calculates the **Average True Range (ATR)** using a
     14-period Wilder's moving average.
3. **Core EMA Analysis System:**

   * This is the most significant part of the script. It sets up a
     full analysis of a 4-EMA system (21, 50, 100, 200 periods).
   * **EMAs:** Calculates the 16 EMAs (4 periods x 4
     price points: OHLC).
   * **1st Derivative (Slope):** Calculates the slope
     (\_d1) for all 16 EMAs to determine the direction and speed of the
     trend.
   * **2nd Derivative (Curvature):** Calculates the
     curvature (\_d2) for all 16 EMAs to determine if the trend is
     accelerating or decelerating.
   * **Helpers:** Prepares helper columns for analysis,
     such as slope in basis points (\_d1\_bps) and trend flip indicators
     (\_flip).
4. **Statistical Analysis & Visualization:**

   * **Plotting:**

     + Generates individual plots for each close EMA, showing the EMA
       line, its slope on a secondary axis, and markers for trend
       flips.
     + Generates a consolidated plot showing all four close EMAs (21,
       50, 100, 200) on a single chart.
   * **Flip Segment Analysis (build\_flip\_segments):**

     + This is an advanced technique. The code identifies every
       "segment" (the period between two trend flips) for each EMA.
     + It then calculates statistics for these segments, such as their
       duration (in bars), total return (close-to-close), max drawdown, and max
       run-up.
     + It produces summaries of this data (e.g., flip\_summary,
       flip\_summary\_by\_year).
   * **Comovement Regime Analysis
     (compute\_ema\_comovement\_stats):**

     + This is the most sophisticated analysis. It checks the
       *comovement* of the slopes of all four close EMAs at the same
       time.
     + It categorizes each trading day into one of three "regimes":
       **ALL\_UP** (all 4 EMA slopes are positive),
       **ALL\_DOWN** (all 4 are negative), or
       **MIXED**.
     + Crucially, it then calculates the *next day's return*
       based on the current day's regime. This is a foundational step for
       building a backtest.
   * **Final Visuals:**

     + Plots histograms of segment durations and returns.
     + Plots a bar chart of the "hit rate" (probability of a positive
       next-day return) for each regime (ALL\_UP, ALL\_DOWN, MIXED).

**Data\_Analysis\_Functions.py (The Custom Library)**

This file is a well-organized module (daf) that contains all the
complex calculation logic, keeping the main script clean.

* **Robust Time-Series Handling:** The functions
  correctly handle data sorted newest\_top (most recent date at the top).
  For rolling calculations (like EWM or rolling std), the code correctly
  reverses the DataFrame (.iloc[::-1]), performs the calculation
  chronologically, and then reverses it back. This is a critical and
  often-overlooked step.
* **Advanced Statistics:** Contains the specific
  formulas for Parkinson, Garman-Klass, and Rogers-Satchell
  volatility.
* **Advanced Trend Analysis:** The
  compute\_ema\_trend\_stats function is particularly advanced. It supports
  three different ways to define a "trend flip":

  1. **binary:** A simple +1/-1 system where a zero-slope
     carries forward the previous sign.
  2. **three\_state:** A +1/0/-1 system where a move to a
     zero-slope is not a flip.
  3. **flat\_zone:** Defines a "flat" trend based on a
     slope threshold (e.g., |slope| < 5 bps) and classifies if these flat
     periods lead to trend continuation or reversal.
* **Performance:** The code uses good pandas
  practices, such as batch-assigning new columns to avoid DataFrame
  fragmentation warnings.

**Key Observations & Potential Next Steps**

* **Strength:** This is not a simple technical
  analysis script; it's a quantitative research framework. The focus on
  derivatives (slope/curvature) and regime analysis (comovement) is
  robust.
* **Observation:** The analysis of "next-bar returns"
  based on EMA regimes is the first step toward building a full trading
  strategy.

**Logical Next Steps:**

1. **Backtesting:** You could use the regime signals
   (ALL\_UP, ALL\_DOWN) to build a simple backtester. For example: "Go long
   when regime is ALL\_UP, go short/flat when regime is ALL\_DOWN, stay flat
   when MIXED." You could then calculate a full equity curve, Sharpe ratio,
   and max drawdown for this strategy.
2. **Machine Learning:** The dozens of features you've
   engineered (all the volatility measures, EMA slopes, curvatures, and
   regime states) would be excellent inputs for a machine learning model
   (like XGBoost or a RandomForest) to predict the next day's price
   direction.
3. **Parameter Optimization:** The script hardcodes EMA
   periods (21, 50, 100, 200) and volatility windows. You could wrap this
   analysis in a loop to test different parameters.

Overall, this is a very strong and impressive piece of analysis
code.

**🧠 Data\_Analysis\_Functions.py — the engine**

This module defines a **comprehensive toolkit for quantitative
time-series and technical analysis**.  
It provides reusable, vectorized functions that operate on pandas
DataFrames of OHLCV data.  
Key areas of functionality include:

**1. Return and Volatility Calculations**

* **b2t\_pct\_delta()** and
  **b2t\_log\_delta()** compute **bar-to-bar simple and
  log returns** across open, high, low, close, and derived
  columns.
* **add\_logret\_stdev\_vol()**,
  **add\_parkinson\_vol()**,
  **add\_garman\_klass\_vol()**,
  **add\_rogers\_satchell\_vol()**, and
  **add\_atr()** implement **classic realized-volatility
  estimators** (Parkinson, Garman-Klass, Rogers-Satchell) and
  **Average True Range** metrics

Data\_Analysis\_Functions

.

**2. EMA Computation and Derivative Analysis**

* **add\_ema\_columns()**,
  **add\_ema\_d1()**, **add\_ema\_d2()**, and
  **prepare\_ema\_helpers()** calculate EMAs, their first and
  second derivatives, and scaled slope columns.
* Internal helpers like \_sign\_flips\_from\_d1() detect **EMA
  trend reversals (flips)**.
* **compute\_ema\_trend\_stats()** (and its predecessor
  old\_compute\_ema\_trend\_stats) summarize **flips, mean slopes,
  intervals, and magnitude distributions** across multiple
  periods

Data\_Analysis\_Functions

.

**3. Flip-Segment & Regime Analytics**

* **build\_flip\_segments()** reconstructs the segments
  between EMA sign flips, measuring duration, return, drawdown, and
  recovery per segment

Data\_Analysis\_Functions

.

* The design supports both “newest-first” and “oldest-first” data
  orientation (direction="newest\_top").

**4. Visualization Tools**

* **plot\_ema\_w\_slopes\_flips()** and
  **plot\_consolidated\_emas()** visualize EMA levels, slopes,
  and flip points on dual-axis plots

Data\_Analysis\_Functions

.

In short, this file is a **general-purpose technical analytics
library** built for reuse, not just Bitcoin.

**📈 BTC Price Analysis.py — the application**

This script is a **comprehensive workflow that drives the
analysis engine** above using actual Bitcoin data from
CoinMarketCap.

**1. Data Preparation**

* Loads historical BTC OHLC data
  (Bitcoin\_01\_1\_2016-10\_26\_2025\_historical\_data\_coinmarketcap.csv).
* Normalizes columns and computes deltas:  
  close−open, daily range, and both simple and log returns via
  daf.delta\_column() and daf.b2t\_log\_delta()

BTC Price Analysis

.

**2. Volatility & Risk Metrics**

* Computes 30-, 60-, and 90-day realized-volatility measures using
  **Parkinson**, **Garman-Klass**, and
  **Rogers-Satchell** estimators.
* Adds a **14-day ATR** using Wilder’s smoothing
  method

BTC Price Analysis

.

**3. EMA Trend Structure**

* Defines ema\_periods = [21, 50, 100, 200] and applies EMAs across
  all OHLC fields.
* Computes 1st and 2nd derivatives (slopes and curvature),
  preparing helper fields for slope scaling and flip detection.

**4. Statistical & Visual Analysis**

* Uses **compute\_ema\_trend\_stats()** and
  **build\_flip\_segments()** to measure:

  + Flip frequencies, durations, and slope magnitudes.
  + Regime co-movement statistics (ALL\_UP, ALL\_DOWN, MIXED) and
    hit-rates.
* Plots EMA overlays, histograms of segment durations and returns,
  and regime hit-rate bar charts

BTC Price Analysis

.

**5. Output / Export**

* Optionally saves processed DataFrames (e.g., flip summaries,
  regime stats) and exports a 201-row sample with a timestamped
  filename.

**🧩 How they fit together**

* BTC Price Analysis.py is the **driver script** — it
  orchestrates data ingestion, applies all analytical routines, and
  visualizes results.
* Data\_Analysis\_Functions.py is the **library** — it
  provides the heavy-lifting math and statistical logic.  
  Together, they form a modular Bitcoin-backtesting and regime-detection
  system centered on **EMA slope dynamics**,
  **volatility structure**, and **trend
  segmentation**.
