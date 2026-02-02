---
title: "Update_DB"
author: "Adam Safi"
created: 2025-11-17T15:17:00+00:00
modified: 2025-11-25T22:29:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\ProcessDocuments\Update_DB.docx"
original_size_bytes: 18865
---
Update Database:

1. To get the max(date) of the current data in the database,
   run:

The focus is on timeclose as that is going to be the last timestamp
that the data will have in the database and will be important for step
3.

2. Download historical data from: [https://coinmarketcap.com/currencies/[ASSET\_NAME]/historical-data/](https://coinmarketcap.com/currencies/%5bASSET_NAME%5d/historical-data/)

   1. Update [ASSET\_NAME] with one of the following:

      1. Bitcoin
      2. Ethereum
      3. XRP
      4. BNB
      5. Chainlink
      6. Hyperliquid
      7. Solana
3. For each asset set the date range minimum to the last
   max(timeclose)-1 and the maximum to today()-1 as today’s daily date
   won’t be completed until “tomorrow” if it’s before the cutoff time 7PM
   EST during daylight savings and 8PM out of daylight savings
4. Download the data for each asset and move the data files from the
   downloads folder to new folder name with date = today()
   “update\_YYYY\_MM\_DD” in:

C:\Users\asafi\Downloads\cmc\_price\_histories\Updates

5. Once all the data files are there, we are ready to run the
   header\_check.py at:

C:\Users\asafi\Downloads\cmc\_price\_histories\

6. To run the header check open the script in Spyder or VSCode and
   edit the 10th line so it read DIR = r"
   C:\Users\asafi\Downloads\cmc\_price\_histories\Updates\update\_YYYY\_MM\_DD".
   Then run it to

   1. The correct output should read: “Wrote:
      C:\Users\asafi\Downloads\cmc\_price\_histories\Updates\update\_YYYY\_MM\_DD\header\_check.csv

> All headers match baseline:
> timeopen;timeclose;timehigh;timelow;name;open;high;low;close;volume;marketcap;circulatingsupply;timestamp”

2. If there is an issue investigate

7. If there correct output is given then head\_check.csv will be
   added in
   C:\Users\asafi\Downloads\cmc\_price\_histories\Updates\update\_YYYY\_MM\_DD.
   Then the next step is to run consolidate\_cmc\_histories.py at:

C:\Users\asafi\Downloads\cmc\_price\_histories\

8. To run the consolidate\_cmc\_histories.py open the script in Spyder
   or VSCode and edit the 9th line so it read DIR =
   r"C:\Users\asafi\Downloads\cmc\_price\_histories\Updates\update\_YYYY\_MM\_DD".
   Then run it to upload the new price data into cmc\_price\_histories7

   1. Confirm it ran correctly by running the following sql
      query:
9. Next update stats on price\_histories7 to confirm all tests pass
   by running run\_refresh\_price\_histories7\_stats.py in
   C:\Users\asafi\Downloads\ta\_lab2\src\ta\_lab2\scripts. Once this has been
   run confirm the tests have passed by running the following
   query:

SELECT \*

FROM price\_histories7\_stats

where "checked\_at"::date = DATE '2025-11-19' #fill in today’s
date

ORDER BY checked\_at DESC

LIMIT 100;

10. If all the tests passed continue on to running the daily and
    multi\_tf ema update script refresh\_cmc\_emas.py at
    C:\Users\asafi\Downloads\ta\_lab2\src\ta\_lab2\scripts