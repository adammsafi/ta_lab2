---
title: "ema_multi_tf_cal_anchor"
author: "Adam Safi"
created: 2025-12-04T13:22:00+00:00
modified: 2025-12-09T04:09:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\EMAs\DesriptiveDocuments\ema_multi_tf_cal_anchor.docx"
original_size_bytes: 29565
---
**Exponential Moving Average – Multi-Timeframe
(Calendar-Anchored)**

**cmc\_ema\_multi\_tf\_cal\_anchor**

**Table Purpose**

The cmc\_ema\_multi\_tf\_cal\_anchor table stores **daily**
EMAs whose canonical (non-rolling) observation points are tied to
**explicit anchored calendar endpoints** (e.g., actual
month-end, quarter-end, year-end), **including partial initial
calendar blocks.**

This differs from \_cal in one critical way:

\_cal

Requires **full calendar blocks** → skips partial
initial 1M/2M/3M/6M bars.

\_anchor

Accepts **partial initial blocks**, anchoring canonical
closes to real month-ends/year-ends even if the block started
mid-month.

Between anchored closes, the EMA still updates
**daily**, using **daily alpha**, preserving
continuity.

This makes \_anchor the closest internal model to a
**TradingView-style bar EMA**, while still supplying a
**full daily series** for modeling, signals, and
derivatives.

This table is designed to align EMA resets and derivative
calculations as closely as possible to **bar-based, anchored EMA
behavior** used by professional charting platforms, while
preserving daily continuity and observability.

**Column Definitions**

**id**

**Type:** INTEGER **Definition:**Unique identifier for the asset (e.g., cryptocurrency). This
identifier is consistent across all CMC-derived price and indicator
tables.

**ts**

**Type:** TIMESTAMP WITH TIME ZONE **Definition:**Timestamp corresponding to the **daily close**
used to propagate the EMA value. All EMA values in this table are
evaluated at daily resolution.

**tf**

**Type:** TEXT **Definition:**Calendar-anchored logical timeframe over which the EMA is
defined as:

* 1M, 2M, 3M, 6M, 12M
* 1W, 2W, … anchored to Saturday

Timeframes correspond to **explicit calendar periods with fixed
anchor points**, not synthetic day counts.

**period**

**Type:** INTEGER **Definition:**EMA lookback period used to compute the exponential moving
average. This value determines the smoothing factor applied during daily
EMA propagation. Number of **anchored bars** used to
compute the EMA. Example: tf = 6M, period = 10 → a 10-bar EMA where each
bar = a 6-month anchored block.

**ema**

**Type:** DOUBLE PRECISION **Definition:**Calculated exponential moving average value for the specified
asset, timestamp, timeframe, and period.

**Important behavior:**

* Between anchored closes (roll = TRUE) EMA updates
  **daily** using **daily α**, not bar
  α.
* At anchored closes (roll = FALSE) EMA is **snapped**
  to the canonical bar EMA (ema\_bar\_close).

So:

* **ema ≠ ema\_bar.**
* ema is the **continuous daily EMA curve**, while
  ema\_bar is the **discrete bar-space EMA** (see
  below).

**ingested\_at**

**Type:** TIMESTAMP WITH TIME ZONE **Definition:**Timestamp indicating when the row was written to the database.
Used for operational auditing and pipeline diagnostics.

**tf\_days**

**Type:** INTEGER **Definition:  
Metadata-only** nominal horizon for the timeframe. **Not
used in smoothing or roll detection**.

**roll**

**Type:** BOOLEAN **Definition:**Indicates whether the observation represents an
**interior rolling day** or an **anchored canonical
boundary**.

* FALSE: Timestamp corresponds to an **anchored calendar bar
  close**
* TRUE: Timestamp lies between anchored endpoints, an interior day
  and represents daily propagation

Anchoring rules here allow for **partial initial bars**,
unlike \_cal.

**d1**

**Type:** DOUBLE PRECISION **Definition:**

First discrete derivative of the exponential moving average (ema)
computed **only across successive anchored canonical
observations** (roll = FALSE).

*d*1\_*r**o**l**l* = *e**m**a**t* − *e**m**a**p**r**e**v* *c**a**n**o**n**i**c**a**l*

Represents the **day-over-day change** in the EMA value,
evaluated at the current timestamp.

**d2**

**Type:** DOUBLE PRECISION **Definition:**Second discrete derivative of the exponential moving average
(ema) computed **only across successive calendar-aligned canonical
observations** (roll = FALSE).

*d*2*t* = *d*1*t* − *d*1*t* − 1

Measures trend acceleration strictly between calendar period
endpoints.

**d1\_roll**

**Type:** DOUBLE PRECISION **Definition:**First derivative of the continuous exponential moving average
(ema) with respect to time, computed for each (id, tf, period)
series.

*d*1*t* = *E**M**A**t* − *E**M**A**t* − 1

Represents the **day-over-day change in the EMA value**
evaluated at the current timestamp.

**d2\_roll**

**Type:** DOUBLE PRECISION **Definition:**

Second derivative of the continuous exponential moving average (ema)
with respect to time, computed for each (id, tf, period) series.

*d*2*t* = *d*1\_*r**o**l**l**t* − *d*1\_*r**o**l**l**t* − 1

Represents the **acceleration or deceleration** of the
EMA trend at the current timestamp.

**Interpretation Notes**

* EMA values are **propagated daily**, even though
  anchoring defines canonical resets.
* Anchored canonical observations (roll = FALSE) correspond to
  **explicit calendar endpoints**.
* d1 and d2 describe **discrete, anchor-to-anchor trend
  changes**, closely approximating true bar-based EMAs.
* d1\_roll and d2\_roll describe **continuous daily trend
  dynamics.**

**Recommended One-Line Summary (Optional)**

cmc\_ema\_multi\_tf\_cal\_anchor preserves daily EMA continuity while
enforcing strict calendar anchoring to approximate bar-level EMA
behavior at canonical period endpoints.

**APPENDIX — \_bar Columns and Semantics**

**Purpose of \_bar Fields**

In cmc\_ema\_multi\_tf\_cal\_anchor, \_bar columns provide a
**bar-space view** of the EMA series and its derivatives,
evaluated only at **explicitly anchored calendar
boundaries**; EMA is **reset at anchored closes**
and then propagated *only conceptually* as a bar-EMA
sequence.

Where the base fields (ema, roll, d1, d2, d1\_roll, d2\_roll) describe
EMA behavior in **daily time space**, the \_bar fields
describe the same quantities in **completed anchored-bar
space**, closely mirroring how bar-based EMAs behave on
professional charting platforms.

All \_bar columns share the **same data types** as their
non-\_bar counterparts.

**Canonical / Anchor Dependency**

For this table:

* Anchors define **fixed calendar endpoints** (e.g.,
  explicit month-end, quarter-end, or other anchored bars).
* Rows where roll = FALSE represent **completed anchored
  bars**.
* \_bar values are only meaningful at these anchored
  boundaries.

Rolling interior rows (where roll = TRUE) represent intra-bar
propagation and do **not** define new \_bar states.

**\_bar Field Definitions**

**ema\_bar**

**Type:** DOUBLE PRECISION  
**Definition:**  
Exponential moving average value sampled **at the close of a
completed anchored bar**.

This is the EMA level **as of the fully completed, anchored
calendar bar**, independent of intra-bar daily evolution. It is
the bar-space analog of the daily ema field.

The **anchored bar EMA**:

* At each anchored close → equals the canonical bar EMA.
* Between anchored closes → carried forward using
  **daily-equivalent alpha** on price (so the bar EMA evolves
  smoothly intra-bar for analytics).

Thus ema\_bar is the EMA **in bar space**, whereas ema is
the EMA **in time space**

**roll\_bar**

**Type:** BOOLEAN  
**Definition:**  
Indicator for whether the row represents a valid **bar-complete
anchored observation**.

In practice for cmc\_ema\_multi\_tf\_cal\_anchor:

* roll\_bar = FALSE identifies an **anchored bar**
  **close** (canonical endpoint).
* roll\_bar = TRUE (if present) would indicate non-bar interior rows
  and should not be treated as completed bars.

Valid \_bar values are intended to be interpreted only when roll\_bar =
FALSE.

**d1\_bar**

**Type:** DOUBLE PRECISION  
**Definition:**  
First discrete derivative of ema\_bar computed **between successive
completed anchored bars**.

This represents the **bar-to-bar EMA change**, i.e., the
slope of the EMA series measured from one completed anchored period to
the next. Only defined at anchor rows (roll\_bar = FALSE).

**d2\_bar**

**Type:** DOUBLE PRECISION  
**Definition:**  
Second discrete derivative of ema\_bar computed across completed anchored
bars.

This captures **changes in bar-level
momentum**—acceleration or deceleration of the EMA trend—from one
anchored bar to the next. Only defined at anchor rows (roll\_bar =
FALSE).

**d1\_roll\_bar**

**Type:** DOUBLE PRECISION  
**Definition:**  
First derivative of ema\_bar computed **only across consecutive
canonical anchored endpoints**, explicitly scoped to bar-complete
transitions.

Operationally, this is the bar-space analog of d1\_roll: it focuses
strictly on **anchor-to-anchor** changes, ignoring interior
daily propagation. After every anchored close, this series
**jumps**, because ema\_bar resets to the canonical bar
EMA.

**d2\_roll\_bar**

**Type:** DOUBLE PRECISION  
**Definition:**  
Second derivative of ema\_bar computed. Measures change in daily momentum
across all days.

This captures curvature of the bar-space EMA, including the expected
discontinuities at anchored closes.

**Interpretation Notes**

* \_bar columns operate entirely in the logic of **anchored
  bars**, not daily time.
* Anchoring allows **partial initial months** to count
  as valid bars—this is the defining difference from \_cal.
* ema\_bar, d1\_bar, d2\_bar provide the **closest internal
  representation to TradingView multi-timeframe EMAs**, which only
  update at bar closes.
* d1\_roll\_bar and d2\_roll\_bar provide a daily-resolution projection
  of bar-space behavior.
* EMA is still **propagated daily**; \_bar fields are a
  **projection onto completed anchored bars**.
* Anchoring enforces **structural regularity** in how
  bars are defined, making:

  + ema\_bar, d1\_bar, and d2\_bar more directly comparable across time,
    and
  + d1\_roll\_bar, d2\_roll\_bar suitable for TradingView-style slope /
    curvature interpretation.
* \_bar columns in this table are the **closest internal
  representation** to a true bar-based EMA as seen on charting
  platforms.

**One-Line Summary (Optional)**

cmc\_ema\_multi\_tf\_cal\_anchor provides daily EMA continuity while
enforcing **true anchored calendar boundaries**, producing
bar-space EMA values and derivatives that closely approximate
TradingView’s multi-timeframe EMA logic.