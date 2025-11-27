# Updating CMC Price Histories and EMA Tables

This guide walks through how to update the CoinMarketCap (CMC) price history data and the EMA (Exponential Moving Average) tables used by `ta_lab2`.  
You do **not** need to write code; you will:

- Download CSV files from CoinMarketCap
- Run a few Python scripts
- Run a few saved SQL queries
- Do some light checks to make sure everything looks good

---

## 0. Before you start

You will need:

- Access to the target PostgreSQL database (via pgAdmin or another SQL tool)
- Python environment with the existing scripts already working
- Basic familiarity with:
  - Opening a Python script in Spyder or VSCode and pressing “Run”
  - Opening and running a saved `.sql` file in pgAdmin or another SQL client

You will work mostly with:

- **CMC raw price CSV files** on disk
- **`cmc_price_histories7`** table (raw daily prices in the database)
- **EMA tables**:
  - `cmc_ema_daily`
  - `cmc_ema_multi_tf`
  - `cmc_ema_multi_tf_cal`

---

## 1. Check the current latest date in the database

We first find the latest date currently loaded in `cmc_price_histories7`. This tells us **where to start** the new download window from CoinMarketCap.

1. Open your SQL tool (pgAdmin or similar) and connect to the target database.
2. Run the saved SQL file that returns the latest date in `cmc_price_histories7`:

   ```text
   sql/metrics/max_ts_rowcount_by_table.sql
   ```

3. In the output, look at the row for `cmc_price_histories7` and note:

   - `max_ts` (specifically based on `timeclose`)
   - `row_count`

4. Write down the latest **`timeclose` date** for `cmc_price_histories7`.  
   This will be used as:

   ```text
   last_max_timeclose_date
   ```

We focus on `timeclose` because it is the final timestamp for each daily bar and is the anchor for later steps.

---

## 2. Download new price data from CoinMarketCap

You will download new daily price data **from the day after your last trusted date (minus one day for overlap)** up to **yesterday**.

1. Go to CoinMarketCap:

   ```text
   https://coinmarketcap.com/currencies/[ASSET_NAME]/historical-data/
   ```

2. Replace `[ASSET_NAME]` with each of the following:

   - `bitcoin`
   - `ethereum`
   - `xrp`
   - `bnb`
   - `chainlink`
   - `hyperliquid`
   - `solana`

3. For each asset:
   - Set the **start date** to:  
     `last_max_timeclose_date - 1 day`  
     (we intentionally include one overlapping day to be safe).
   - Set the **end date** to:  
     `yesterday` (`today - 1 day`)  
     because today’s daily bar is not yet complete until later in the evening.

   > **Note:** The daily bar is considered “complete” after:
   > - ~7pm EST during daylight savings time  
   > - ~8pm EST outside daylight savings time

4. Click **Download Data** for each asset.  
   This will save a `.csv` file (usually into your `Downloads` folder).

---

## 3. Organize the downloaded CSV files

1. Create a new folder named with today’s date in the `Updates` directory:

   ```text
   C:\Users\asafi\Downloads\cmc_price_histories\Updates\update_YYYY_MM_DD
   ```

   Replace `YYYY_MM_DD` with today’s date (for example, `update_2025_11_26`).

2. Move all the newly downloaded asset CSV files (Bitcoin, Ethereum, etc.) into this folder.

At this point, **all new CSV files for the update should be in**:

```text
C:\Users\asafi\Downloads\cmc_price_histories\Updates\update_YYYY_MM_DD
```

---

## 4. Run the header check

We now confirm that all CSV files have the expected columns.

1. Open the `header_check.py` script located at:

   ```text
   C:\Users\asafi\Downloads\cmc_price_histories\header_check.py
   ```

2. Edit the line that sets `DIR` (around line 10) so it points to the new update folder, for example:

   ```python
   DIR = r"C:\Users\asafi\Downloads\cmc_price_histories\Updates\update_YYYY_MM_DD"
   ```

3. Run `header_check.py` in Spyder or VSCode.

4. **Expected output in the console:**

   - A line like:

     ```text
     Wrote: C:\Users\asafi\Downloads\cmc_price_histories\Updates\update_YYYY_MM_DD\header_check.csv
     ```

   - A line indicating that all headers match the baseline:

     ```text
     All headers match baseline: timeopen;timeclose;timehigh;timelow;name;open;high;low;close;volume;marketcap;circulatingsupply;timestamp
     ```

5. If the script reports any mismatched headers:
   - Open the problematic CSV(s)
   - Compare the column names to the expected baseline
   - Fix the CSV or re-download as needed  
   - Re-run `header_check.py` until everything passes.

When this step is successful, you should see a `header_check.csv` file in the update folder.

---

## 5. Load new price data into `cmc_price_histories7`

Now we load the cleaned CSVs into the main database price table.

1. Open the `consolidate_cmc_histories.py` script located at:

   ```text
   C:\Users\asafi\Downloads\cmc_price_histories\consolidate_cmc_histories.py
   ```

2. Edit the line that sets `DIR` (around line 9) so it points to the same update folder:

   ```python
   DIR = r"C:\Users\asafi\Downloads\cmc_price_histories\Updates\update_YYYY_MM_DD"
   ```

3. Run `consolidate_cmc_histories.py` in Spyder or VSCode.

   - This script will:
     - Read each CSV file in the folder
     - Upsert the data into `cmc_price_histories7` in the database

4. After it finishes, confirm it ran correctly using a saved SQL check. For example, run:

   ```text
   sql/metrics/current_vs_snapshot_rowcount_comparisson.sql
   ```

   or another dedicated check that compares row counts before/after the load.

   > **If you haven’t finalized a specific “post-load sanity check” query yet, leave a note here like:**  
   > `[TODO: fill in canonical post-load row-count check SQL here]`.

If anything looks off (for example, the row counts change in an unexpected way), investigate before continuing.

---

## 6. Check the latest load window by asset

Before updating stats, run the **latest-load window sanity check** to make sure the most recent ingest is clean.

1. In your SQL tool, run:

   ```text
   sql/metrics/cmc_price_histories7_latest_load_window_check.sql
   ```

2. This query filters rows to the most recent `load_ts` per `id` and returns:

   - `id`
   - `min_date`
   - `max_date`
   - `n_rows`

3. For each asset `id`, confirm:

   - The date range from `min_date` to `max_date` is continuous (no gaps)
   - `n_rows` equals the number of calendar days between `min_date` and `max_date` (inclusive)

   For example, if the latest batch covers `2025-11-19` through `2025-11-24`, then:

   ```text
   n_rows = 6
   ```

4. If any asset shows gaps or an unexpected `n_rows`, inspect:

   - The source CSVs in the update folder
   - The `consolidate_cmc_histories.py` log output

   Fix findings and re-run the load and this check before continuing.

---

## 7. Run stats for `cmc_price_histories7`

Now we run the stats script for the raw price table to confirm everything looks healthy.

1. In Python (Spyder or VSCode), run:

   ```text
   C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\run_refresh_price_histories7_stats.py
   ```

   (If the actual filename is slightly different, update it here later.)

2. After the script finishes, check the latest stats with:

   ```sql
   SELECT *
   FROM price_histories7_stats
   WHERE "checked_at"::date = DATE 'YYYY-MM-DD'  -- replace with today's date
   ORDER BY checked_at DESC
   LIMIT 100;
   ```

3. Review the results:

   - All tests should ideally show `PASS`
   - Some `WARN` statuses may be acceptable if you understand and expect them
   - Any `FAIL` should be investigated before moving on

If everything looks good, you can move on to updating EMAs.

---

## 8. Refresh EMA tables and run stats

There are three EMA layers to update, and for each one you should **run its stats immediately after the refresh finishes**, before moving on to the next layer:

1. **Daily EMAs:** `cmc_ema_daily`
2. **Multi-timeframe EMAs (price-based):** `cmc_ema_multi_tf`
3. **Multi-timeframe EMAs (calendar-aligned):** `cmc_ema_multi_tf_cal`

The recommended order is:

1. Refresh **daily EMAs**, then run **daily EMA stats**.  
2. Refresh **multi-timeframe EMAs (price-based)**, then run **multi-timeframe EMA stats**.  
3. Refresh **multi-timeframe EMAs (calendar-aligned)**, then run **calendar multi-timeframe EMA stats**.

### 8.1 Daily EMAs (`cmc_ema_daily`)

#### 8.1.1 Run the daily EMA refresh script

1. In Spyder or VSCode, open the daily EMA refresh script. For example:

   ```text
   C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\refresh_cmc_ema_daily_only.py
   ```

2. Make sure the script is configured to:

   - Point to the correct database (via `TARGET_DB_URL` or your `.env` file).
   - Use `--ids all` (or whatever subset of assets you want to refresh).
   - Use incremental/insert-only mode unless you **deliberately** want a full recompute from a given start date.

3. Run the script. You should see log lines indicating that:

   - It is extending `cmc_ema_daily` from the previous last date.
   - It is inserting rows only for the new dates just loaded into `cmc_price_histories7`.

4. If the script fails, stop here, investigate the error, and only continue once it completes successfully.

#### 8.1.2 Run the daily EMA stats

Immediately after the daily EMA refresh completes:

1. Run the daily EMA stats script. For example:

   ```text
   [TODO: insert path/filename, e.g. refresh_cmc_ema_daily_stats.py]
   ```

2. In your SQL tool, run a query like:

   ```sql
   SELECT *
   FROM ema_daily_stats
   WHERE checked_at::date = DATE 'YYYY-MM-DD'   -- replace with today’s date
   ORDER BY checked_at DESC
   LIMIT 100;
   ```

3. Confirm that:

   - The most recent `checked_at` is today’s date.
   - There are no unexpected `FAIL` results.
   - Any `WARN` results are understood and acceptable.

Only after the daily EMA stats look good should you move on to the multi-timeframe EMAs.

---

### 8.2 Multi-timeframe EMAs (price-based) (`cmc_ema_multi_tf`)

#### 8.2.1 Run the multi-timeframe EMA refresh script

1. Open the multi-timeframe EMA refresh script. For example:

   ```text
   C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\refresh_cmc_ema_multi_tf_only.py
   ```

2. Make sure the script is configured to:

   - Point to the correct database.
   - Use `--ids all` (or your desired subset).
   - Run in incremental “dirty-window” mode so that it:

     - Recomputes from a small window (for example, the last week or so).
     - Upserts rows into `cmc_ema_multi_tf` for the new date range.
     - Does **not** touch old history beyond that window.

3. Run the script and watch the logs for each asset:

   - You should see each asset listed with messages like *“extending cmc_ema_multi_tf from [last_multi_ts] through end=None”*.
   - You should see per-asset row counts summarizing how many rows were inserted/updated.

4. If anything looks off (for example, extremely large row counts or errors), stop and investigate.

#### 8.2.2 Run the multi-timeframe EMA stats

Immediately after the multi-timeframe EMA refresh completes:

1. Run the multi-timeframe EMA stats script:

   ```text
   [TODO: insert path/filename, e.g. refresh_cmc_ema_multi_tf_stats.py]
   ```

2. Query the stats table (for example, `ema_multi_tf_stats`) for today’s date and review:

   ```sql
   SELECT *
   FROM ema_multi_tf_stats
   WHERE checked_at::date = DATE 'YYYY-MM-DD'   -- replace with today’s date
   ORDER BY checked_at DESC
   LIMIT 100;
   ```

3. Review key tests:

   - **Gap tests** – Confirm there are no unexpected gaps in each timeframe.
   - **Row-count vs span tests** – Confirm the number of rows matches expectations for each timeframe window.
   - **Roll flag consistency tests** – Confirm that `roll`, `d1_roll`, and `d2_roll` behave as expected (for example, `roll = true` only on canonical endpoints).

4. If tests show unexpected `FAIL` results, pause and investigate before moving on to calendar-aligned EMAs.

---

### 8.3 Multi-timeframe EMAs (calendar-aligned) (`cmc_ema_multi_tf_cal`)

This table uses calendar-aligned timeframes (for example, month-end, quarter-end, etc.).

#### 8.3.1 Run the calendar multi-timeframe EMA refresh script

1. Open the calendar multi-timeframe EMA refresh script:

   ```text
   C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\refresh_cmc_ema_multi_tf_cal_only.py
   ```

2. Make sure it is configured for:

   - The correct database.
   - `--ids all` (or the subset you want).

3. Run the script and confirm logs show:

   - The incremental dirty-window start date.
   - Per-asset row counts upserted into `cmc_ema_multi_tf_cal`.

#### 8.3.2 Run the calendar multi-timeframe EMA stats

Immediately after the calendar multi-timeframe EMA refresh completes:

1. Run the calendar multi-timeframe EMA stats script:

   ```text
   [TODO: insert path/filename, e.g. refresh_cmc_ema_multi_tf_cal_stats.py]
   ```

2. Query the calendar EMA stats table for today’s date. For example:

   ```sql
   SELECT *
   FROM ema_multi_tf_cal_stats
   WHERE checked_at::date = DATE 'YYYY-MM-DD'   -- replace with today’s date
   ORDER BY checked_at DESC
   LIMIT 100;
   ```

3. Review:

   - Gap tests for each calendar timeframe (for example, 1M, 3M, 6M).
   - Row-count vs span tests.
   - Roll flag consistency tests for calendar-aligned endpoints.

4. If all tests look good, your EMA layers are now fully updated and validated.
## 10. Update the “trusted through” documentation

Once all checks look good, update your operational record of how “fresh” the database is.

1. Open the existing “trusted through” markdown file, for example:

   ```text
   docs/ops/db_trusted_through_YYYY-MM-DD.md
   ```

2. Make a new copy for the current update, for example:

   ```text
   db_trusted_through_2025-11-26.md
   ```

3. Update the table inside that file with the new:

   - Latest `timeclose` date for `cmc_price_histories7`
   - Latest timestamps and row counts for:
     - `cmc_ema_daily`
     - `cmc_ema_multi_tf`
     - `cmc_ema_multi_tf_cal`

4. Save the file and commit it to Git along with any updated SQL and script files.

This gives “future you” a clear record of exactly how far each table is trusted through, tied to a specific date.

---

## 11. Summary of the full process

At a high level, updating prices and EMAs involves:

1. **Check current latest database date** in `cmc_price_histories7`.
2. **Download new daily CSVs** from CoinMarketCap for each asset (overlapping by one day).
3. **Organize CSVs** into a dated `update_YYYY_MM_DD` folder.
4. **Run header_check.py** to confirm CSV structure.
5. **Run consolidate_cmc_histories.py** to load data into `cmc_price_histories7`.
6. **Run the latest-load window check SQL** to confirm a clean contiguous date window.
7. **Run price_histories7 stats** and confirm all tests are passing or acceptable.
8. **Refresh daily and multi-timeframe EMAs** (including calendar-aligned EMAs).
9. **Run EMA stats** for all EMA tables and confirm they look healthy.
10. **Update the “trusted through” documentation** with the new dates and row counts.

Once you’ve gone through this once or twice, the process becomes a repeatable checklist that can be followed even by someone with a non-technical background.
