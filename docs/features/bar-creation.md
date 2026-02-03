---
title: "bar_creation"
author: "Adam Safi"
created: 2025-12-29T14:01:00+00:00
modified: 2026-01-08T08:14:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\Bars\DesriptiveDocuments\bar_creation.docx"
original_size_bytes: 46446
---
**Bar Creation**

**Purpose and Scope**

This document defines how time series data is aggregated into bars
within **ta\_lab2**. Bar creation is a foundational concern
that directly impacts all downstream analytics, including EMA
construction, trend detection, probabilistic modeling, and
multi-timeframe alignment.

The objective of this document is to **explicitly define bar
semantics** so that all higher-level indicators operate on
well-specified, deterministic, and auditable time structures. Bar
creation is treated as an **independent system concern**,
strictly separated from indicator logic, smoothing, or signal
interpretation.

**Core Concepts**

A **bar** represents an aggregation of observations over
a defined time interval. Each bar has:

1. A start (open) timestamp
2. An end (close) timestamp
3. A high timestamp
4. A low timestamp
5. An open price
6. A high price
7. A low price
8. A close price
9. A volume
10. A market capitalization
11. A **canonical close**, representing the finalized
    and authoritative value for that interval

Bars may also have **preview observations**, which occur
before the bar is complete and represent provisional state.

Bar creation must define:

* How bar boundaries are determined
* Whether bars are calendar aligned or calendar anchored
* How partial periods are handled
* Whether preview observations are exposed and how they are
  labeled

**Timeframe Definition**

A **timeframe (tf)** is a named interval specification
that defines how bars are constructed. A timeframe consists of:

* A **unit** (day, week, month, quarter, year, or
  fixed-length duration)
* A **count** (integer ≥ 1)
* A **calendar dependence flag** (calendar-based or
  fixed-length)

Timeframes may be:

* **Fixed-length** (e.g., 180D, 365D), independent of
  calendar boundaries
* **Calendar-based**, derived from universally
  recognized calendar units
* **Observation-space rolling**, where bars are formed
  by grouping a fixed number of canonical base observations in order.
  Missing calendar days do not create synthetic observations and are
  tracked diagnostically.

Only explicitly defined and supported calendar timeframes may be
calendar anchored.

**Bar Boundary Construction (Normative Algorithm)**

Bar boundaries are constructed deterministically according to the
following algorithm.

Given:

* timeframe (tf)
* alignment type
* calendar convention
* boundary timezone authority
* input observation timestamps

The bar construction process is:

1. Normalize timestamps to the boundary timezone authority
2. Determine candidate calendar unit boundaries, if
   applicable
3. Apply alignment or anchoring rules
4. Compute bar start timestamp
5. Compute bar end timestamp
6. Assign canonical timestamp equal to bar end timestamp
7. Associate observations strictly within [start\_ts,
   end\_ts]

This process must be deterministic and re-executable using stored
metadata alone.

**Calendar Aligned Bars**

Calendar aligned bars are time intervals whose boundaries align to
calendar units, but whose grouping depends on the series start rather
than a fixed global anchor.

Each bar:

* Begins at the start of a calendar unit
* Ends at the end of a calendar unit
* May span multiple contiguous units

The specific grouping of calendar units into bars depends on when the
bar sequence begins.

Example:  
A calendar-aligned 6-month bar may span March–August, August–January, or
any other contiguous six-month window, provided each bar begins on the
first day of a month and ends on the last day of a month.

If a series begins mid-period, the first bar is partial by
definition.

**ta\_lab2 clarification:** Calendar-aligned bars align
to calendar unit boundaries, but grouping of multiple units into a bar
may depend on a deterministic alignment origin. Partial start bars are
excluded for aligned models; the first emitted bar begins at the first
full boundary after data availability.

**Calendar Anchored Bars**

Calendar anchored bars are defined relative to **fixed,
globally consistent calendar anchors**. Their boundaries are
predetermined and do not vary by series start.

Anchoring applies only to timeframes with universally agreed calendar
segmentation.

Supported anchored timeframes:

* **Yearly (1Y)**: Jan 1 – Dec 31
* **Semiannual (6M)**: Jan–Jun, Jul–Dec
* **Quarterly (3M)**: Jan–Mar, Apr–Jun, Jul–Sep,
  Oct–Dec
* **Bi-monthly (2M)**: Jan–Feb, Mar–Apr, May–Jun,
  Jul–Aug, Sep–Oct, Nov–Dec
* **Monthly (1M)**: Full calendar month
* **Weekly (1W)**, when explicitly anchored (e.g., ISO
  weeks)

All assets and time series share identical bar boundaries for these
timeframes.

If a series begins mid-period, the first bar is partial but
**must still be associated with its correct anchored
interval**.

**Rolling Bars (Observation-Space)**Rolling bars aggregate a fixed count of canonical base
observations (e.g., N daily closes).

• Bar identity is determined by ordered observation grouping.  
• Expected calendar days between the bar start and snapshot day are
computed for diagnostics.  
• Missing days advance expected position within the bar but do not
introduce synthetic data.  
• Snapshot emission is allowed even when missing days exist.

**Partial Start Periods**

A **partial start period** occurs when a time series
begins within the interior of a bar interval.

Bar creation must explicitly define whether partial start bars
are:

* **Included** (persisted immediately), or
* **Excluded** (suppressed until the first full bar
  completes)

This policy is a property of bar creation itself and is independent
of any indicator logic.

Partial bars, once created, must never be reclassified as full
bars.

**Canonical Bars and Preview Observations**

A **canonical bar** is finalized only at the end of its
defined interval and represents the authoritative bar close.

Canonical bars:

* Are stable and persistable
* Are suitable for cross-series comparison
* Emit exactly one canonical close event

**Preview observations** are intermediate data points
that occur before a canonical bar is complete, typically derived from
lower-timeframe canonical closes.

Preview observations:

* Are provisional
* Must be explicitly labeled as such
* Must never overwrite canonical values

**Preview Days**

**Preview days** are a specific type of preview
observation that occur on daily boundaries within an unfinished
higher-timeframe bar.

Preview days allow systems to observe interim bar behavior without
prematurely finalizing the bar.

Preview days are persisted as snapshot rows keyed by the daily close
timestamp. Canonical observations are represented by roll = false.

Preview days:

* Share the same bar identity as the canonical bar
* Are marked as provisional (e.g., roll = true)
* Exist strictly within the bar’s start and end timestamps

**Canonical Close Price Rule**

The **canonical close price** of a bar is derived
from:

The most recent lower-timeframe **canonical close**
occurring at or before the bar’s canonical timestamp.

If no such lower-timeframe close exists, the canonical close is
undefined and the bar must not be finalized.

**Preview Lifecycle and Transition**

Preview observations follow a strict lifecycle:

* Preview observations **share bar identity** with
  their canonical bar
* Preview observations are marked provisional
* Upon canonical close:

  + Preview observations are superseded
  + Exactly one canonical bar is emitted
  + Canonical data is authoritative and immutable

Preview observations must never persist beyond the existence of a
canonical bar unless explicitly configured for historical
inspection.

**Persistence Contract**

Persisted bars must include sufficient metadata to allow **full
reconstruction** of bar boundaries and semantics.

At minimum, persisted data must encode:

* Bar start timestamp
* Bar end timestamp
* Canonical timestamp
* Alignment type
* Calendar convention (if applicable)
* Preview vs canonical classification
* Partial-bar classification (if applicable)

Bar identity must be immutable once created.

Persisted systems **MAY** store multiple snapshot rows
per semantic bar when preview observations are enabled. Semantic bar
identity (start/end timestamps) remains immutable regardless of snapshot
count.

**Invariant Violation Handling**

Any violation of a formal invariant constitutes a system error.

Invariant violations must result in:

* Explicit error signaling
* Rejection of bar emission
* Audit logging sufficient for diagnosis

Invariant violations are not acceptable edge cases.

**Non-Goals**

Bar creation explicitly does **not**:

* Perform indicator calculations
* Apply smoothing or filtering
* Infer missing prices
* Apply asset- or venue-specific trading rules

These concerns belong to downstream systems.

An **invariant** is a condition or property that must
always hold true for a system, regardless of state, time, or execution
path.

In other words, an invariant defines what **cannot
change** without the system becoming invalid. It serves as a
contract that constrains behavior and ensures consistency, correctness,
and predictability across implementations and over time.

In the context of software and data systems, invariants are used
to:

* Define non-negotiable rules of structure or behavior
* Prevent ambiguous or inconsistent interpretations
* Enable validation, testing, and enforcement
* Provide a stable foundation on which more complex logic can
  safely depend

If an invariant is violated, it indicates a bug, a modeling error, or
an explicit breach of system assumptions rather than an acceptable edge
case.

**Formal Invariants**

The following invariants define non-negotiable properties of bar
creation within **ta\_lab2**. These rules are intended to be
enforceable through validation logic and to serve as a stable contract
for all downstream analytics.

**Global Invariants**

1. **Deterministic Construction**  
   Given identical inputs, timeframe definitions, and configuration, bar
   creation must be deterministic.
2. **Monotonic Time Ordering**  
   Bar start times, end times, and observations must be strictly ordered.
   Overlapping bars at the same timeframe are not permitted.
3. **Single Canonical Close per Bar**  
   Each bar may have at most one canonical close, occurring exactly at the
   bar’s end timestamp.

**Calendar Aligned Invariants**

4. **Calendar Boundary Alignment**  
   Bars must start at the beginning of a calendar unit and end at the end
   of a calendar unit.
5. **Series-Dependent Grouping**  
   The grouping of calendar units into bars may vary by series
   start.
6. **Explicit Partial-Start Policy**  
   For calendar-aligned timeframes, the system MUST explicitly specify
   whether partial start bars are included or excluded.

> In ta\_lab2:

* Calendar-aligned bars EXCLUDE partial start periods and suppress
  emission until the first full bar boundary is reached.
* Calendar-anchored bars INCLUDE partial start periods and
  associate them with their correct anchored interval.

> This policy is part of bar-creation configuration and MUST NOT be
> inferred implicitly.

**Calendar Anchored Invariants**

7. **Fixed Global Boundaries**  
   Bar boundaries must be identical across all assets and series.
8. **Restricted Timeframe Set**  
   Anchoring is only permitted for explicitly defined, universally accepted
   calendar partitions.
9. **Anchor Association for Partial Bars**  
   Partial bars must still be associated with their correct anchored
   interval.

**Partial Period Invariants**

10. **Explicit Partial-Bar Policy**  
    Inclusion or exclusion of partial bars must be explicitly
    specified.
11. **No Retroactive Completion**  
    A partial bar must never be reclassified as a full bar after
    creation.

**Canonical and Preview Invariants**

12. **Canonical Supremacy**  
    Canonical bars are authoritative. Preview observations must never
    overwrite canonical values.
13. **Preview Provisionality**  
    Preview observations must be explicitly marked as provisional.
14. **No Multiple Canonical Events**  
    A bar must emit exactly one canonical close.

**Cross-Timeframe and Persistence Invariants**

15. **Lower-Timeframe Containment**  
    All preview observations must fall within the bar’s start and end
    timestamps.
16. **Stable Bar Identity**  
    A bar’s identity is immutable once created.
17. **Explicit Classification**  
    Persisted bars must encode alignment type and canonical vs preview
    status.
18. **Auditable Boundaries**  
    Bar boundaries must be re-constructible from stored metadata
    alone.

**Summary**

Bar creation defines the temporal backbone of
**ta\_lab2**. By explicitly specifying alignment, anchoring,
partial periods, preview semantics, and formal invariants, ta\_lab2
ensures that all downstream indicators operate on consistent, auditable,
and well-defined time structures.

**The Handling of Errors in Base Data**

Bar creation assumes base data is *structurally valid* and
*semantically consistent*. In practice, raw market data may
contain errors, inconsistencies, or vendor-specific quirks. This section
defines how ta\_lab2 handles base-data errors in a way that preserves
determinism, auditability, and invariant enforcement.

**Scope of “Base Data”**

Base data refers to the lowest-timeframe persisted observations used
as inputs to higher-timeframe bar aggregation. In the current system,
this is typically the canonical 1D table derived from
public.cmc\_price\_histories7 and emitted as public.cmc\_price\_bars\_1d. All
higher-timeframe bar tables must source from this canonical base table
rather than directly from raw ingest tables.

**Error Taxonomy**

Base-data errors fall into distinct categories. Each category has a
defined handling policy.

1. **Structural Errors**

   * Missing required fields (e.g., id, timestamp, open, close,
     timeopen, timeclose)
   * Duplicate primary keys or non-unique identity
   * Invalid types or unparsable timestamps
2. **Temporal Inconsistencies**

   * timeopen > timeclose
   * timestamp outside the expected bar window (if timestamp is
     treated as canonical close)
   * timehigh or timelow outside [timeopen, timeclose]
   * Non-monotonic sequences for a given id
3. **Price Inconsistencies**

   * high < low
   * high < max(open, close)
   * low > min(open, close)
   * Null prices where prices are required
4. **Completeness Errors**

   * Missing days (gaps in the series)
   * Partial availability (e.g., a day exists but has incomplete
     fields)

These categories are intentionally separated because they imply
different root causes and demand different remediation strategies.

**Base Data Contract**

The canonical base table must satisfy the following non-negotiable
properties:

* Unique identity per observation: (id, timestamp) is unique and
  stable.
* Valid time window: timeopen <= timeclose.
* Extremum containment: timehigh and timelow must lie within
  [timeopen, timeclose].
* OHLC validity: high >= low, high >= max(open, close), and
  low <= min(open, close).
* Deterministic construction: the canonical base table must be
  reproducible from raw inputs under the same configuration.

If the canonical base table satisfies these conditions,
higher-timeframe bar creation can treat the base data as trusted and
focus exclusively on aggregation semantics.

**Handling Policy**

ta\_lab2 uses a two-layer policy:

1. **Canonicalization Layer (Base Data Repair and
   Filtering)**

   * Raw ingest data is transformed into a canonical base
     table.
   * Canonicalization is the only stage where repair is
     permitted.
   * Repairs must be deterministic, rule-based, and fully
     auditable.
2. **Aggregation Layer (Bar Creation)**

   * Higher-timeframe bar creation must not “fix” base-data
     issues.
   * If a required base observation is missing or invalid, the bar
     builder must either:

     + emit is\_missing\_days = true (if configured to tolerate gaps),
       or
     + refuse to finalize the bar (for canonical bar emission), per the
       invariant violation policy.

**Deterministic Repair Rules**

When an error is repairable without introducing ambiguity, ta\_lab2
may apply deterministic canonicalization rules. Repairs must be
explicitly enumerated and must not depend on heuristics, interpolation,
or asset-specific assumptions.

**Repair Rule: Extremum Timestamp Outside Bar
Window**

A common error is timehigh or timelow falling outside the daily
window [timeopen, timeclose]. This violates containment invariants and
undermines tie-breaking logic.

If timehigh is outside the window, canonicalization must degrade the
high to an observation guaranteed to occur inside the window: the open
or close.

* **If timehigh < timeopen or timehigh >
  timeclose:**

  + Set high := max(open, close)
  + Set timehigh := timeopen if open > close, else
    timeclose

If timelow is outside the window:

* **If timelow < timeopen or timelow >
  timeclose:**

  + Set low := min(open, close)
  + Set timelow := timeopen if open < close, else
    timeclose

This approach preserves:

* containment invariants,
* deterministic attribution of extremum time,
* and compatibility with “best-known within the bar”
  semantics.

All repairs must be tracked with explicit flags (e.g.,
repaired\_timehigh, repaired\_timelow) to preserve auditability.

**Repair Rule: OHLC Internal Inconsistency**

After time repair, OHLC values must be re-validated. If the raw or
repaired bar violates OHLC constraints, the canonicalization layer must
enforce a consistent representation:

* high := max(high, open, close, low)
* low := min(low, open, close, high) (applied carefully to avoid
  reversing intended extremes)
* Ensure high >= low

If these transformations cannot restore consistency without ambiguity
(e.g., multiple nulls or nonsensical values), the row must be
rejected.

**Rejection Policy**

Some errors cannot be repaired without inventing data or applying
heuristic logic. These must be rejected.

A base row must be rejected if any of the following holds:

* Missing required identity fields: id or timestamp is
  null
* Missing required time boundaries: timeopen or timeclose is
  null
* Missing required price anchors: open or close is null
* timeopen > timeclose (window is invalid)
* After applying deterministic repairs, any invariant still fails
  (e.g., time containment or OHLC constraints)
* Duplicate identity that cannot be resolved
  deterministically

Rejected rows must be recorded in an audit table (e.g.,
cmc\_price\_bars\_1d\_rejects) including:

* the raw values,
* the computed failure reason,
* and the canonicalization configuration version.

**Auditability and Observability**

Canonicalization must be observable and diagnosable. At minimum:

* All rejected rows are persisted with a reason code.
* All repaired rows are persisted with repair flags and
  (optionally) a repair mask.
* A summary report is produced per run:

  + number of processed rows,
  + number of upserts,
  + number of repairs (timehigh/timelow),
  + number of rejects,
  + last processed timestamp per asset.

These outputs are not “nice-to-have”; they are required to uphold the
system’s audit and invariant enforcement claims.

**Incremental Processing and State**

Canonical base-data construction may be incremental, but
incrementalism must not compromise correctness.

* A state table (e.g., cmc\_price\_bars\_1d\_state) records per-asset
  progress:

  + last\_src\_ts
  + last run stats
* Incremental runs may include a deterministic lookback window
  (e.g., 3 days) to handle late revisions in raw ingest data.
* State advancement must be monotonic and must only advance when
  processing succeeds.

**Interaction With Higher-Timeframe Bar Creation**

Higher-timeframe bars must not compensate for base-data corruption.
Instead:

* If base data is missing for days inside a bar interval, bar
  builders may:

  + mark is\_missing\_days = true and continue (if configured),
    or
  + refuse canonical bar emission if the canonical close cannot be
    defined.
* Higher-timeframe bar creation MAY emit preview snapshots despite
  missing base observations, provided diagnostics are recorded. Canonical
  bar finalization is permitted only when a qualifying lower-timeframe
  canonical close exists at or before the bar’s canonical timestamp.
  Missing days do not authorize data invention and do not invalidate
  preview emission.

The canonical close rule remains authoritative: if no qualifying
lower-timeframe canonical close exists at or before the bar’s canonical
timestamp, the bar must not be finalized.

**Failure Mode Expectations**

Any base-data violation that survives canonicalization is treated as
a system error, not an acceptable edge case.

* Canonicalization failures:

  + must be surfaced explicitly (logs + rejects table),
  + must not silently pass into downstream aggregation.
* Aggregation failures due to missing canonical base inputs:

  + must emit deterministic “no bar” behavior or is\_missing\_days
    behavior as configured,
  + must never invent missing prices.

**Operational Conformance**Incremental drivers, state tables, and rebuild logic are
implementation details. These mechanisms MUST preserve semantic
invariants, **MUST** be deterministic, and **MUST
NOT** alter bar identity, partial-bar classification, or
canonical/preview status.

**Summary**

Base-data error handling is intentionally strict and explicit:

* Only the canonicalization layer may repair, and only via
  deterministic rules.
* Non-repairable errors are rejected with audit logging.
* Canonical base tables are the contract boundary for all
  higher-timeframe bar creation.
* Incremental operation is supported via a state table and
  deterministic lookback.
* Bar creation treats invariant violations as system errors and
  does not apply heuristic fixes.

If you want, I can also give you a compact “Reason Codes” appendix
(e.g., null\_open\_close, timeopen\_gt\_timeclose,
timehigh\_outside\_window\_after\_repair, etc.) that matches the rejects
table the script writes, so this section and the implementation stay
aligned.

![](./media/image1.emf)**Appendix**

**Data dictionary (columns)**

**1) Table Family**

**Definition:** Logical family of bar tables that share
the same bar-construction semantics.  
**Type:** text (enum)  
**Allowed values (current):** multi\_tf, \_cal\_iso, \_cal\_us,
\_anchor\_iso, \_anchor\_us  
**Notes:** This is the “contract scope” key.

**2) Partial Start Policy**

**Definition:** Whether the first bar is included when
the series begins mid-interval (a “partial start period”).  
**Type:** text (enum)  
**Allowed values:** include, exclude, NA  
**Interpretation:**

* include: persist the first partial bar for that interval
* exclude: do not emit/persist the first partial bar
* NA: not applicable (no calendar interval concept)

**3) Calendar Basis**

**Definition:** Whether bar boundaries are derived from
the calendar (calendar units) or from fixed-duration intervals.  
**Type:** text (enum)  
**Allowed values:** calendar, none  
**Interpretation:**

* calendar: boundaries depend on calendar units (months, weeks,
  quarters, etc.)
* none: boundaries are not calendar-derived (e.g., fixed-length
  rolling windows)

**4) Alignment Type**

**Definition:** How multi-unit bars are grouped relative
to calendar structure.  
**Type:** text (enum)  
**Allowed values:** none, aligned, anchored  
**Interpretation:**

* none: not calendar based
* aligned: respects clean calendar boundaries, but grouping can
  depend on series start
* anchored: boundaries are globally fixed and identical across all
  assets/series

**5) Calendar Convention**

**Definition:** The calendar ruleset used to interpret
boundaries (week definition, holidays if relevant, etc.).  
**Type:** text (enum)  
**Allowed values (current):** ISO, US, NA  
**Interpretation:**

* ISO: ISO week conventions (e.g., week starts Monday) and ISO-like
  calendar handling
* US: US convention defaults (commonly week starts Sunday unless
  specified otherwise)
* NA: not calendar-based

**6) Canonical Timestamp Rule**

**Definition:** Rule used to determine the canonical bar
close timestamp (the authoritative finalization time).  
**Type:** text (enum)  
**Allowed values (current):** fixed\_length\_end,
calendar\_unit\_end, anchored\_calendar\_end  
**Interpretation:**

* fixed\_length\_end: canonical close occurs at end of a
  fixed-duration interval
* calendar\_unit\_end: canonical close occurs at the end of the
  relevant calendar unit window (aligned)
* anchored\_calendar\_end: canonical close occurs at the end of the
  globally anchored interval

**7) Preview Policy**

**Definition:** Whether provisional observations are
emitted before the canonical close, and at what cadence.  
**Type:** text (enum)  
**Allowed values (recommended):** none, daily\_preview  
**Interpretation:**

* none: only canonical bars exist, no previews
* daily\_preview: preview observations exist at daily boundaries
  within an unfinished higher-TF bar (“preview days”)

**8) Preview Classification**

**Definition:** How preview observations are
distinguished from canonical observations in data.  
**Type:** text (enum)  
**Allowed values (recommended):** no\_preview\_rows,
roll\_flag, explicit\_preview\_flag  
**Interpretation:**

* no\_preview\_rows: previews do not exist
* roll\_flag: roll=true indicates preview/provisional rows;
  roll=false indicates canonical rows
* explicit\_preview\_flag: a dedicated boolean flag (e.g.,
  is\_preview) marks previews

**9) Bar Identity Basis**

**Definition:** The scheme that defines a bar’s
immutable identity such that it can be reconstructed and joined
deterministically.  
**Type:** text (enum)  
**Allowed values (recommended):** start\_end, calendar\_key,
anchor\_window  
**Interpretation:**

* start\_end: identity is determined by (tf, start\_ts, end\_ts) (plus
  asset key)
* calendar\_key: identity is determined by a canonical calendar
  label (e.g., 2025-01, 2025-Q3, 2025-W14)
* anchor\_window: identity is determined by an anchor definition +
  window index (useful for specialized anchoring)

**10) Partial Bar Flagging**

**Definition:** How partial start bars are
represented/marked in persisted data (supports invariant “explicit
classification”).  
**Type:** text (enum)  
**Allowed values (recommended):** none, is\_partial\_start,
partial\_reason=start\_only  
**Interpretation:**

* none: partiality not recorded / not applicable
* is\_partial\_start: a boolean (or equivalent) indicates the bar is
  a partial start bar
* partial\_reason=start\_only: supports extensibility (start-only vs
  other partial reasons in future)

**11) Boundary TZ Authority**

**Definition:** The timezone reference that governs bar
boundary interpretation and reconstruction.  
**Type:** text (enum)  
**Allowed values (recommended):** UTC,
calendar\_convention\_timezone, exchange\_local  
**Interpretation:**

* UTC: boundaries are defined in UTC
* calendar\_convention\_timezone: boundaries are defined in the
  timezone implied by the calendar convention/region rules
* exchange\_local: boundaries follow an exchange/venue local
  timezone (more relevant for equities)
