---
title: "ema_multi_tf_cal"
author: "Adam Safi"
created: 2025-12-04T13:22:00+00:00
modified: 2025-12-17T22:31:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\EMAs\DesriptiveDocuments\ema_multi_tf_cal.docx"
original_size_bytes: 31894
---
**Exponential Moving Average – Multi-Timeframe
(Calendar-Aligned)**

**cmc\_ema\_multi\_tf\_cal**

**Table Purpose**

The cmc\_ema\_multi\_tf\_cal table stores **daily sampled
exponential moving averages (EMAs)** calculated over
**calendar-aligned timeframes**.

Key features:

* The EMA is updated **every day**, using *daily
  alpha*, independent of timeframe length.
* **Canonical rows (roll = FALSE) occur only at true calendar
  boundaries**, such as month-end, quarter-end, or
  year-end.
* Timeframes reflect **exact real-world calendar
  periods** (1M = the actual month; 6M = the actual six-month
  block), *not fixed day counts*.
* The \_bar fields describe EMA behavior **in
  bar-space**, representing completed calendar periods.

This table is the correct foundation for:

* TradingView-style calendar bars
* Calendar-aligned macro / regime models
* Monthly / quarterly / annual indicator computation
* Period-consistent derivatives and momentum signals
* institutional reporting periods

**Column Definitions**

**id**

**Type:** INTEGER  
**Definition:**  
Unique identifier for the asset (e.g., cryptocurrency). This identifier
is consistent across all CMC-derived price and indicator tables.

**ts**

**Type:** TIMESTAMP WITH TIME ZONE  
**Definition:**  
Timestamp corresponding to the **daily close** used to
compute the EMA value. All EMA values in this table are evaluated at
daily resolution, regardless of timeframe length.



**tf**

**Type:** TEXT  
**Definition:**  
**Calendar-aligned** logical timeframe over which the EMA
is defined, e.g.:

* 1M – calendar month
* 3M – calendar quarter
* 6M – six calendar months
* 1Y – calendar year

These are **true calendar periods**, not synthetic
day-count approximations, and not fixed numbers of days.

**period**

**Type:** INTEGER  
**Definition:**  
EMA lookback period used to compute the exponential moving average. This
value determines the smoothing factor applied to the daily price series.
If tf = 6M and period = 10, the EMA uses **10 six-month
bars** as its smoothing horizon.

**ema**

**Type:** DOUBLE PRECISION  
**Definition:**  
Calculated exponential moving average value for the specified asset,
timestamp, timeframe, and period. The EMA is propagated daily using
standard exponential smoothing, even for multi-month or multi-year
timeframes.

This is the **daily EMA**, computed as:

* At canonical closes (roll = FALSE) → uses the **canonical
  bar EMA value**
* At all interior days (roll = TRUE) → the EMA **continues
  updating daily** using **daily alpha**, not bar
  alpha

Key point:

* **ema never resets at bar boundaries.**
* It is a **continuous daily series** whose only
  difference on canonical rows is that it is “snapped” to the canonical
  bar-EMA value on those days.

**ingested\_at**

**Type:** TIMESTAMP WITH TIME ZONE  
**Definition:**  
Timestamp indicating when the row was written to the database. Used for
data lineage, auditing, and pipeline monitoring.

**tf\_days**

**Type:** INTEGER  
**Definition:**  
A metadata-only field describing the nominal horizon associated with the
timeframe. It is NOT used:

* to compute smoothing
* to compute α
* to compute ema
* to determine roll boundaries

Included for schema consistency and cross-table alignment with
\_multi\_tf and \_anchor\_derived

**roll**

**Type:** BOOLEAN  
**Definition:**  
Indicates whether the observation represents a **rolling interior
timestamp** or a **calendar-aligned canonical
boundary**.

* FALSE: Timestamp corresponds to the final trading day of a
  calendar period
* TRUE: Timestamp lies within the interior of the current calendar
  period

This is the primary difference versus \_multi\_tf, where roll is based
on fixed bar sizes rather than calendar boundaries.

**d1**

**Type:** DOUBLE PRECISION  
**Definition:**  
First discrete derivative of the exponential moving average (ema)
computed **only across successive calendar-aligned canonical
observations** (roll = FALSE).

*d*1\_*r**o**l**l* = *e**m**a**t* − *e**m**a**p**r**e**v* *c**a**n**o**n**i**c**a**l*

Rolling (interior) rows are excluded from this derivative
computation.

**d2**

**Type:** DOUBLE PRECISION  
**Definition:**  
Second discrete derivative of the exponential moving average (ema)
computed **only across successive calendar-aligned canonical
observations** (roll = FALSE).

*d*2*t* = *d*1*t* − *d*1*t* − 1

Measures trend acceleration strictly between calendar period
endpoints.

**d1\_roll**

**Type:** DOUBLE PRECISION  
**Definition:**  
First derivative of the continuous exponential moving average (ema) with
respect to time, computed for each (id, tf, period) series.

*d*1*t* = *E**M**A**t* − *E**M**A**t* − 1

Represents the **day-over-day change in the EMA value**
evaluated at the current timestamp.

**d2\_roll**

**Type:** DOUBLE PRECISION  
**Definition:**  
Second derivative of the continuous exponential moving average (ema)
with respect to time, computed for each (id, tf, period) series.

*d*2*t* = *d*1\_*r**o**l**l**t* − *d*1\_*r**o**l**l**t* − 1

Represents the **acceleration or deceleration** of the
EMA trend at the current timestamp.

**Interpretation Notes**

* EMA values are propagated **daily**, even when
  timeframes span months or years, always using daily α (not bar
  α).
* Canonical observations (roll = FALSE) occur only at **true
  calendar end points**, not fixed day intervals.
* d1 and d2 capture continuous daily trend dynamics.
* d1\_roll and d2\_roll capture
  **calendar-period-to-calendar-period** EMA momentum and
  acceleration.

**Recommended One-Line Summary (Optional)**

cmc\_ema\_multi\_tf\_cal provides daily EMA continuity while enforcing
strict calendar alignment at non-rolling observation points.

**APPENDIX — \_bar Columns and Semantics**

**Purpose of \_bar Fields**

In cmc\_ema\_multi\_tf\_cal, \_bar columns provide a bar-space
representation of EMA values and derivatives derived from a
daily-propagated EMA series.

Where the base columns describe EMA behavior in daily time space,
\_bar columns describe the same quantities collapsed to completed
calendar periods (e.g., month, quarter, year).

In daily time, EMA is **continuous**; in bar space, EMA
is **reset** to the canonical bar EMA at each bar
close.

**Canonical Dependency**

All \_bar values are defined **only at canonical calendar
boundaries**, where:

* roll = FALSE
* the current row represents the **final trading day of a
  calendar period**

Rolling interior rows do **not** materially participate
in \_bar computations.

**\_bar Field Definitions**

**ema\_bar**

**Type:** DOUBLE PRECISION

**Definition:**The **canonical bar EMA** (computed only on true
calendar-bar closes). Interior rows have this value carried forward
exactly as the bar-space EMA behaves.

The key distinction:

* ema = daily EMA curve (continuous)
* ema\_bar = bar EMA curve (piecewise, resets at each bar
  close)
* independent of intra-period daily propagation.

**roll\_bar**

**Type:** BOOLEAN

**Definition:**Boolean indicator identifying whether a row represents a valid
bar-complete observation.

In cmc\_ema\_multi\_tf\_cal:

* roll\_bar = FALSE indicates a canonical calendar boundary
* roll\_bar = TRUE (if present) indicates non-bar rows and should
  not be interpreted as completed bars

In practice, meaningful \_bar values exist only when roll\_bar =
FALSE.

**d1\_bar**

**Type:** DOUBLE PRECISION

**Definition:**First discrete derivative of ema\_bar computed **between
successive completed calendar bars**.

This value represents **net EMA change over a full calendar
period**, regardless of the number of trading days contained
within that period. Defined only when roll\_bar = false.

**d2\_bar**

**Type:** DOUBLE PRECISION

**Definition:**Second discrete derivative of ema\_bar computed across completed
calendar bars.

This value captures **acceleration or deceleration** of
EMA momentum from one calendar period to the next. Defined only when
roll\_bar = false.

**d1\_roll\_bar**

**Type:** DOUBLE PRECISION

**Definition:**First derivative of ema\_bar computed **across all
days**.

This will jump right after canonical rows, because bar-space ema
**resets** the canonical ema.

**d2\_roll\_bar**

**Type:** DOUBLE PRECISION

**Definition:**Second derivative of daily ema\_bar. Measures change in daily
momentum across all days.

**Interpretation Notes**

* \_bar columns operate **completed calendar bars**,
  not days.
* Periods may differ in length (Feb vs Dec, etc.); \_bar values
  normalize EMA behavior to period completion, not calendar
  duration.
* \_bar fields are particularly useful for:

  + calendar-based regime detection and trend analysis
  + reporting and aggregation
  + reducing intra-period noise
  + monthly/quarterly momentum

**One-Line Summary (Optional)**

cmc\_ema\_multi\_tf\_cal provides a **daily EMA curve**
aligned to **true calendar periods**, with \_bar fields
expressing the same indicator in **calendar-bar space** for
regime and boundary-aware analysis.

**Seeding**

* EMA seeding does not leverage partial periods, on timeframes that
  leverage a Week(s), Month(s), or Year(s)

  + Example, if the first daily close price of an asset was on
    07/13/2011, then the first 1-Week close would be on 07/24/2011, the
    first 1-Month close would be on 08/30/2011, and the first 1-Year close
    would be on 12/31/2012

    - Therefore, the first 10-Period 1-Year EMA would have its first
      EMA generated on 12/31/2022, with roll = false and there would then be a
      1-Year 10-Period EMA where roll=true everyday forward until 12/31/2023,
      and this pattern would continue indefinitely.
