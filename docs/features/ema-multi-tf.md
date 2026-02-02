---
title: "ema_multi_tf"
author: "Adam Safi"
created: 2025-12-04T13:22:00+00:00
modified: 2025-12-15T12:46:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\EMAs\DesriptiveDocuments\ema_multi_tf.docx"
original_size_bytes: 34603
---
**Exponential Moving Average – Multi-Timeframe
Tables**

**cmc\_ema\_multi\_tf (v1 – Bar-Aligned EMA)**

**cmc\_ema\_multi\_tf\_v2 (v2 – Continuous Daily EMA)**

**1. Table Purpose**

The multi-timeframe EMA tables (cmc\_ema\_multi\_tf and
cmc\_ema\_multi\_tf\_v2) store **daily-sampled exponential moving
averages** computed across a set of logical timeframes (e.g., 2D,
1W, 1M, 6M). Each row corresponds to a single daily timestamp for a
specific (id, tf, period) series and includes:

* the calculated EMA value,
* timeframe metadata (tf, tf\_days),
* and indicators describing whether the observation is a
  **canonical** timeframe boundary or a
  **rolling** interior point.

ta\_lab2 currently maintains **two versions** of this
table:

**Version Overview**

| **Version** | **Table Name** | **EMA Space** | **Behavior** | **Primary Use Case** |
| --- | --- | --- | --- | --- |
| **v1** | cmc\_ema\_multi\_tf | **Bar-space** | EMA resets at canonical timeframe boundaries. Rolling rows use daily alpha; canonical rows use bar alpha. Behaves similarly to TradingView. | Visual sanity checks, TradingView alignment, bar-level interpretation. |
| **v2** | cmc\_ema\_multi\_tf\_v2 | **Time-space** | Pure continuous daily EMA. No bar resets. Alpha depends only on the smoothing horizon. | Modeling, research pipelines, regime classification, quant signals. |

Both versions store the same columns and metadata, but the
**EMA propagation rules differ**. This document applies to
**both** tables unless explicitly noted.

**2.** **Column Definitions (Applies to Both v1
and v2)**

**id**

**Type:** INTEGER  
**Definition:**  
Unique identifier for the asset (e.g., cryptocurrency or traded
instrument).  
This value matches the primary key used across all CMC-derived price and
indicator tables.

**ts**

**Type:** TIMESTAMP WITH TIME ZONE  
**Definition:**  
Timestamp representing the **daily close** used to compute
the EMA value.  
All EMAs in this table are sampled at daily resolution, regardless of
the timeframe length.

**tf**

**Type:** TEXT  
**Definition:**  
Logical timeframe over which the EMA is defined (e.g., 2D, 7D, 30D,
180D).  
This value describes the **intended smoothing horizon**,
not the data frequency (sampling is always daily).

**period**

**Type:** INTEGER  
**Definition:**  
EMA lookback period used to compute the exponential moving average, also
referred to as the smoothing length. Determines the smoothing factor
**α:**

> α = $\frac{2}{period + 1}$

This value determines the smoothing factor applied to the price
series for the given timeframe. Both v1 and v2 use this formula, but
they apply **α differently** (see Version Behavior
section).

**ema**

**Type:** DOUBLE PRECISION  
**Definition:**  
Calculated exponential moving average value at the timestamp (ts) for
the specified asset, timeframe, and period (id, tf, period). The EMA is
computed recursively using the standard exponential smoothing
formula.

**ingested\_at**

**Type:** TIMESTAMP WITH TIME ZONE  
**Definition:**  
Timestamp indicating when the row was written to the database. Primarily
used for data lineage, auditing, and pipeline diagnostics.

**tf\_days**

**Type:** INTEGER  
**Definition:**  
The logical timeframe expressed in days (e.g., 1W → 7, 1M → 30 by
definition of the framework). Used to determine canonical boundaries
(v1) and horizon mapping (v2).

**roll**

**Type:** BOOLEAN  
**Definition:**  
Indicates whether the row corresponds to a canonical timeframe
boundary.

* **FALSE (canonical)**

  + Timestamp aligns with a direct multiple of tf\_days from the
    series’ origin.
  + Represents a “true timeframe close.”
* **TRUE (rolling)**

  + Timestamp lies **between** canonical
    boundaries.
  + Represents an interior, daily update.

**Note:** v1 and v2 *both* compute roll the same
way. They differ in **how** EMAs behave at those
boundaries.

**d1**

**Type:** DOUBLE PRECISION

**Definition:**  
First discrete derivative of the exponential moving average (ema) with
respect to time, computed for each (id, tf, period) series.
Operationally, d1 represents the **day-over-day change in the EMA
value** evaluated at the current timestamp. Represents daily EMA
momentum.

*d*1*t* = *E**M**A**t* − *E**M**A**t* − 1

**d2**

**Type:** DOUBLE PRECISION

**Definition:**  
Second discrete derivative of the exponential moving average (ema) with
respect to time, computed for each (id, tf, period) series.
Operationally, d2 represents the **change in the first derivative
(d1)**, capturing acceleration or deceleration in the EMA
trend.

*d*2*t* = *d*1*t* − *d*1*t* − 1

**Key clarification (important for correctness)**

* d1 and d2 are computed **for all rows**,
  including:

  + rolling rows (roll = TRUE)
  + canonical rows (roll = FALSE)
* They are always evaluated **at the current row**,
  using prior EMA state(s) for the same (id, tf, period).

So, it is more accurate to say:

“d1 and d2 are EMA derivatives *computed using prior
observations*, but stored as properties of the current record.”

---

**d1\_roll**

**Type:** DOUBLE PRECISION

**Definition:**  
First derivative of the exponential moving average (ema) computed
**only across canonical timeframe endpoints** (roll =
FALSE) for each (id, tf, period) series. This derivative ignores all
rolling (interior) rows and measures absolute EMA change **between
successive canonical timeframe closes**.

**d2\_roll**

**Type:** DOUBLE PRECISION

**Definition:**  
Second derivative of the exponential moving average (ema) computed
**only across canonical timeframe endpoints** (roll =
FALSE). This value reflects acceleration or deceleration of the EMA
trend **between canonical closes**, independent of rolling
observations.

**One-sentence summary (very useful in docs)**

d1 and d2 measure *continuous, daily EMA momentum and
acceleration*, while d1\_roll and d2\_roll measure *discrete,
period-aligned momentum and acceleration* using only canonical
timeframe boundaries.

**3. Version Behavior Details**

**Below is the essential distinction between the two
versions.**

**v1 – Bar-Aligned EMA (TradingView-Style)**

Table: cmc\_ema\_multi\_tf

Behavior:

* EMA **resets** at each canonical boundary (roll =
  FALSE).
* At canonical timestamps, EMA is recomputed using **bar
  alpha**, not daily alpha.
* Between boundaries (roll = TRUE), EMA is propagated using
  **daily alpha**.

Consequences:

* Line segments between canonical bars are continuous, but
  *global* EMA is discontinuous.
* Produces sharper turns and more sensitivity to timeframe
  alignment.
* More closely matches how TradingView behaves for higher-timeframe
  EMAs.

When to use v1:

* When you need TV-aligned visuals.
* When bar structure carries meaning (macro closes, weekly/monthly
  boundaries).
* When replicating bar-space indicators.

**v2 – Continuous Daily EMA (Time-Space, No
Resets)**

Table: cmc\_ema\_multi\_tf\_v2

Behavior:

* EMA evolves **continuously** from start to end;
  **no resets** at canonical boundaries.
* Only smoothing horizon changes via alpha; timeframe does
  **not** alter topology, so only a single daily smoothing
  constant is applied everywhere.
* Timeframe only determines horizon length, not resetting
  behavior.
* Consistent with textbook EMA definitions and most quant research
  literature.
* EMA is **daily-recursive everywhere** (topology =
  daily space)
* **Alpha changes only because the horizon
  changes**
* Timeframe affects **horizon length**, not
  *when* EMA updates or resets
* That is exactly the horizon-based interpretation:
* effective
  horizon = tf\_days × period  
  $$\alpha = \frac{2}{(\text{tf\\_days} \times
  \text{period}) + 1}
  $$

So:

* One alpha per (tf, period)
* Applied **uniformly every day**
* No bar resets
* No special casing at canonical boundaries

Consequences:

* Much smoother and more stable EMA curves.
* No discontinuities or bar-induced jumps.
* Easier to use in modeling pipelines, ML features, and statistical
  analysis.

When to use v2:

* For research, backtesting, quant models, regime detection, and ML
  features.
* When you want mathematically pure EMAs.
* When you want horizon-consistent smoothing.

**4. EMA Propagation Model (applies to both, but behavior
differs)**

**Regardless of version:**

* EMAs are propagated **daily**, because daily price
  bars are the most granular data available.
* Higher-level timeframes (e.g., 1W, 1M) **are not computed
  from resampled bars**.
* Instead, they are computed via daily EMA recursion using an alpha
  corresponding to the timeframe length.
* Both use the standard recursive exponential smoothing
  formula.
* Both derive timeframe length via tf\_days.

As a result:

* Every (id, tf, period) produces **one EMA value per
  day**
* Higher-level EMAs evolve **continuously** rather
  than updating only at bar closes

**Key difference:**

| **Version** | **How EMA evolves** | **Reset behavior** |
| --- | --- | --- |
| **v1** | Daily EMA between bars using daily α; at canonical bar closes, one-step EMA using bar α | **Resets at canonical boundaries** |
| **v2** | Daily EMA using horizon-based α, identical across all days, continuous daily EMA | **No resets** |

**5. Canonical vs Rolling Observations**

A row is canonical (roll = FALSE) if its timestamp lies on a direct
multiple of tf\_days from the price series origin. Otherwise, the row is
rolling (roll = TRUE).

Example (tf = 1M, tf\_days = 30):

| **Day** | **Type** |
| --- | --- |
| 1–29 | roll = TRUE |
| 30 | roll = FALSE (canonical) |
| 31–59 | roll = TRUE |
| 60 | roll = FALSE |
| … | … |

Both versions classify canonical vs. rolling identically; they differ
only in **how EMA is updated at canonical boundaries**.

**6. Summary**

* **v1 (cmc\_ema\_multi\_tf)** — is a bar-aligned EMA
  that resets at canonical boundaries. Best for **visuals**,
  **discretionary alignment**, and **bar
  semantics**.
* **v2 (cmc\_ema\_multi\_tf\_v2)** — is a
  **continuous daily-space** EMA without resets.  
  Best for **modeling, research, smooth signal generation, machine
  learning pipelines,** **regime detection**, and
  **quant pipelines**.

Both share the same schema, same metadata, and same derivative
calculations, but differ fundamentally in **EMA propagation
topology**.