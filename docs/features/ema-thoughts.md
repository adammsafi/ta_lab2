---
title: "EMA_thoughts"
author: "Adam Safi"
created: 2025-12-29T12:26:00+00:00
modified: 2026-01-07T11:51:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\EMAs\EMA_thoughts.docx"
original_size_bytes: 20465
---
**EMA**

I am trying to determine which EMA methodologies are most appropriate
to persist within ta\_lab2. There are many valid ways to compute an EMA
series, and there is surprisingly little formal literature that clearly
defines a single “correct” approach.

The word appropriate is used deliberately for its ambiguity. An EMA’s
suitability depends on a number of design choices and downstream use
cases that are not always explicitly defined. In this context, the
primary purpose of an EMA series is to measure trend, identify potential
support and resistance levels in time series data, and provide a smooth
representation of price dynamics across different time horizons. Changes
in the slope and acceleration of an EMA can also be used as inputs to
probabilistic studies aimed at forecasting future movements in the
underlying series.

**Seeding**

There are two main schools of thought when it comes to seeding an
EMA.

The first approach seeds the EMA using a simple moving average
calculated over the canonical prices for the chosen period. For example,
when calculating a 180-day, 10-period EMA, one would take the canonical
closes at days, 180,360,540,720,900,1080,1260,1440,1620,1800  
compute the SMA at day 1800, and use that value as the initial EMA input
to the recursive formula. This method has the advantage of reducing
early-series bias and produces a smoother, more stable initial EMA
value.

The alternative approach seeds the EMA directly from the first
available close price, typically setting the EMA equal to the close on
day 1 (or day 2, depending on indexing) and applying the recursive EMA
formula from that point forward. This method converges more quickly to a
“live” EMA but can introduce greater sensitivity and distortion in the
early portion of the series.

Both approaches are mathematically defensible. The choice between
them affects early EMA behavior, convergence characteristics, and
comparability with external tools and platforms, and therefore must be
considered carefully in the context of ta\_lab2’s broader design
goals.

**Smoothing Factor**

The smoothing factor, commonly referred to as alpha, determines the
relative weighting of new observations versus historical EMA values. It
controls how quickly the EMA responds to changes in the underlying price
series and therefore directly influences lag, smoothness, and
sensitivity. A larger alpha increases responsiveness but amplifies
noise, while a smaller alpha produces a smoother series at the cost of
increased lag. Because alpha governs the fundamental dynamics of the
EMA, its definition must be tightly coupled to how time, bars, and
periods are modeled within the system.

Daily Alpha – Daily alpha assumes that each EMA update corresponds to
a single calendar day and that the smoothing factor is derived solely
from the nominal period length. In this formulation, alpha is typically
defined as

𝛼 = 2/N+1, where

N represents the EMA period expressed in days. This approach
implicitly assumes uniform daily spacing and is most appropriate when
operating directly on daily bars without aggregation or multi-timeframe
alignment. While simple and widely used, daily alpha can become
inconsistent when applied to EMA series constructed from non-daily bars
or from canonical timestamps that represent aggregated time
intervals.

Bar-Based Alpha

Bar-based alpha generalizes the smoothing factor by defining alpha in
terms of bar count rather than calendar time. In this model, each bar,
regardless of its real-world duration, is treated as a single
observation in the EMA recursion. Alpha is therefore computed using the
same canonical formula, but with the understanding that N represents a
number of bars rather than days. This approach provides consistency
across timeframes and aligns naturally with how many charting platforms
compute EMAs on resampled or aggregated data. However, it abstracts away
the actual elapsed time between observations, which can introduce
distortions when bar durations vary or when gaps exist in the underlying
data.

Period × Bar-Based Alpha

Period × bar-based alpha extends the bar-based approach by explicitly
incorporating both the EMA period and the number of bars contained
within each higher-level timeframe. In this formulation, alpha is
adjusted to reflect the effective number of lower-level bars
contributing to each EMA update, allowing the smoothing factor to scale
with both period length and bar compression. This approach is
particularly useful for multi-timeframe EMA systems, where a single EMA
update may represent multiple underlying daily or intraday observations.
While more complex, period × bar-based alpha offers improved conceptual
consistency when aligning EMAs across timeframes and provides a clearer
mapping between mathematical smoothing behavior and the underlying bar
structure.

**Partial Start Period**

A key design choice for bar-based EMAs arises at the beginning of a
series when the first bar represents only a partial period. This
situation occurs when bars are calendar-aligned or calendar-anchored and
the time series begins in the middle of a higher-level interval. For
example, if a series starts in mid-August, both the monthly bar for
August and a six-month bar anchored to a fixed calendar boundary will be
incomplete at the start of the series.

In this scenario, the EMA methodology must explicitly define whether
a partial bar is eligible to participate in EMA seeding and early
updates. Treating the initial partial bar as a valid observation allows
the EMA to begin responding immediately, but it introduces an
observation whose duration and informational content differ from that of
a fully formed bar. This can increase early-series sensitivity and may
distort comparability with EMAs computed on fully completed bars.

Alternatively, the EMA can be defined to ignore partial start
periods, delaying initialization until the first fully completed bar is
available. This approach improves consistency across observations and
preserves a uniform interpretation of each bar’s contribution, but it
also postpones EMA availability and reduces early data coverage. The
resulting EMA may be smoother and more stable initially, but at the cost
of responsiveness during the early portion of the series.

The choice between including or excluding partial start periods has
downstream implications for convergence behavior, cross-timeframe
alignment, and comparability with external charting platforms. As such,
this decision should be made explicitly and encoded as part of the EMA
specification within ta\_lab2, rather than treated as an implicit side
effect of bar construction or data availability.

**Preview Days**

Preview days refer to the intermediate observations that occur
between successive canonical bar closes in higher-timeframe EMA
constructions. When an EMA is defined on aggregated or calendar-based
bars, such as weekly, monthly, or multi-month intervals, the canonical
EMA update occurs only at the completion of each full bar. Preview days
capture the evolving EMA value on the intervening lower-timeframe
observations, typically daily closes, by applying the EMA recursion
using the most recent available price while holding the higher-timeframe
bar context fixed. These preview values are not final and will be
superseded by the canonical EMA once the bar closes, but they provide a
forward-looking view of how the EMA is likely to evolve if current
prices persist. Preview days improve responsiveness and analytical
continuity, while introducing a clear distinction between provisional
and canonical EMA states that must be explicitly modeled and
persisted.

When incorporating preview days into a higher-timeframe EMA, a
critical design decision is whether preview updates should use the same
smoothing factor as canonical bar closes. Applying the canonical alpha
to preview days treats each preview observation as an equivalent EMA
update, increasing responsiveness but effectively compressing multiple
EMA steps into a single bar period. This can cause the EMA to converge
more quickly than intended and may over-weight short-term price
movements within an incomplete bar. Alternatively, using a reduced or
scaled alpha for preview days preserves the intended smoothing behavior
across the full bar interval, ensuring that the cumulative influence of
all preview updates does not exceed that of a single canonical update.
The choice directly affects convergence, volatility sensitivity, and
alignment with external platforms, and therefore must be explicitly
specified rather than left as an implicit consequence of
implementation.

**Definitions:**  
Calendar Aligned

Calendar aligned bars are time intervals whose boundaries are
determined solely by standard calendar conventions, independent of when
a time series begins. Each bar starts and ends at predefined calendar
boundaries such as the start and end of a day, week, month, quarter, or
year. For example, a calendar-aligned monthly bar always spans from the
first day of the month at 00:00 to the last day of the month at
23:59:59, regardless of when data collection for a particular asset
begins.

In a calendar-aligned system, all assets and time series share
identical bar boundaries for a given timeframe, which facilitates
cross-asset comparability and consistent aggregation. However, when a
series begins mid-period, the first bar will be incomplete by
definition, representing only a partial interval of the full calendar
span.

Calendar Anchored

Calendar anchored bars are defined relative to fixed, globally
consistent calendar anchors, and their boundaries do not vary based on
when a series begins. These anchors correspond to standard, widely
recognized calendar partitions that repeat predictably over time.
Calendar anchoring is only meaningful for timeframes whose boundaries
are universally agreed upon and naturally segmented by the calendar.

Calendar anchored behavior is therefore relevant for the following
timeframes:

* Yearly (1Y): January 1 to December 31
* Every 6 Months (6M): January 1 to June 30, and July 1 to December
  31
* Quarterly (3M): Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec
* Every 2 Months (2M): Jan–Feb, Mar-Apr, May–Jun, Jul–Aug, Sep-Oct,
  Nov–Dec
* Monthly (1M): First day of the month to the last day of the
  month
* Weekly (1W), when ISO-anchored: Monday 00:00 through Sunday
  23:59:59

For these timeframes, all assets and time series share identical bar
boundaries, regardless of when their data begins. If a series starts
mid-period, the first anchored bar will be partial, but it will still be
associated with one of these fixed anchor intervals. This approach
maximizes cross-asset comparability, aligns with standard financial
reporting conventions, and provides a stable foundation for
multi-timeframe analysis.