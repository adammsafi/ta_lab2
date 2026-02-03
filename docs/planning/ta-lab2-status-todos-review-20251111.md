---
title: "ta_lab2_Status&ToDos_Review_20251111"
author: "Adam Safi"
created: 2025-11-08T18:58:00+00:00
modified: 2025-11-11T11:47:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Plans&Status\ta_lab2_Status&ToDos_Review_20251111.docx"
original_size_bytes: 18220
---
**1) Historical BTC Data (CSV)**

* **Source:** coinmarketcap.com
* **Pair / Frequency:** BTC\_USD, daily
* **Date range:** **2016-01-01 →
  2025-10-26**
* **Location:**  
  C:\Users\asafi\Downloads\ta\_lab2\data\Bitcoin\_01\_1\_2016-10\_26\_2025\_historical\_data\_coinmarketcap.csv
* **Fields (columns):**

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

**2) Initial Analysis Scripts**

* **Files:** BTC Price Analysis.py and
  Data\_Analysis\_Functions.py
* **Location:**  
  C:\Users\asafi\Downloads\ta\_lab\Old\BTC Price Analysis.py  
  C:\Users\asafi\Downloads\ta\_lab\Old\Data\_Analysis\_Functions.py

**2a) BTC Price Analysis.py (end-to-end analysis)**

* Loads the BTC OHLCV CSV, normalizes column names, and creates a
  working df2.
* Expands timestamp columns (timeOpen, timeClose, timeHigh,
  timeLow) into rich date/time features.
* Computes simple % returns and log returns (bar-to-bar and
  intraday).
* Builds multiple volatility measures (rolling stdev of log
  returns; Parkinson, Garman–Klass, Rogers–Satchell; ATR).
* Adds EMAs for open/high/low/close at 21/50/100/200; computes
  first (slope, d1) and second (curvature, d2) derivatives; flags slope
  “flip” events.
* Produces plots (per-EMA panels and consolidated views),
  computes/plots EMA co-movement regimes, and flip-segment stats
  (durations, returns, histograms).

**2b) Data\_Analysis\_Functions.py (reusable
library)**

* **Cleaning & time features:** drop duplicate
  timestamp; expand to year/month/day, weekday, quarter; optional season
  and moon phase.
* **Return math:** bar-to-bar simple/log deltas (incl.
  intraday) with rounding and orientation control (newest-on-top vs.
  oldest-on-top).
* **Volatility toolkit:** rolling log-return stdev
  (annualized), Parkinson, Garman–Klass, Rogers–Satchell, and ATR
  (Wilder/SMA/EMA), orientation-safe.
* **EMA utilities:** batch EMA add; d1/d2; slope
  scaling (bps/percent); trend-flip detection with alignment options
  (“older / newer / actionable”).
* **Regimes & segments:** build flip segments
  (duration, returns, MDD/MRU, slope stats); compute EMA co-movement
  regimes (ALL\_UP / ALL\_DOWN / detailed MIXED); summarize hit
  rates/returns; plotting helpers.

**3) Packaging the Project**

As the scope grew, maintaining two monolithic files became unwieldy.
The work was reorganized into a Python package:

* **Package:** ta\_lab → quickly superseded by
  **ta\_lab2**
* **Location:**
  C:\Users\asafi\Downloads\ta\_lab2

*Commit history for ta\_lab2 is maintained separately (see commit
table).*

**4) Proof-of-Concept: Data → DB Pipeline
(fedtools2)**

Goal: pull data from an API on the local machine and persist it to a
database table.

* **Repo/Folder:** fedtools2  
  **Location:** C:\Users\asafi\Downloads\fedtools2
* **Related directories created:**

  + C:\Users\asafi\Downloads\Data\_Tools
  + C:\Users\asafi\Downloads\ETL
  + C:\Users\asafi\Downloads\FinancialData
  + C:\Users\asafi\Downloads\FinancialData\FedData

**Cloud workflow (VM + DB)**

1. Create a VM.
2. Provision a database on the VM.
3. Write a script to pull from the API and insert into the
   DB.
4. Add timers/schedulers to automate API pulls and DB
   updates.
5. Connect to the remote DB from the local machine.

**5) Status & Next Steps**

The project is ongoing. Immediate next actions:

* Finalize ta\_lab2 module boundaries and docstrings; harden public
  APIs.
* Lock a canonical DB schema for ingested data (versions &
  migrations).
* Productionize the API → DB job (idempotency, retries,
  logging/alerts).
* Add CI for tests, lint, and release automation; pin environments
  (conda/uv).
* Write a short runbook (local, VM, and troubleshooting).

Top of Form
