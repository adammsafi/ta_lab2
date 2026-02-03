---
title: "EMA_loo"
author: "Adam Safi"
created: 2025-12-28T21:29:00+00:00
modified: 2026-01-08T08:16:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\EMAs\EMA_loo.docx"
original_size_bytes: 17139
---
**What’s accurate (schema-wise)**

* Both tables have the **same 12 columns** and the
  same names: id, ts, tf, period, ema, ingested\_at, d1, d2, tf\_days, roll,
  d1\_roll, d2\_roll. ✅
* Types match your doc for most fields:

  + ts is timestamp with time zone ✅
  + tf is text ✅
  + period is integer ✅
  + ema/d1/d2/d1\_roll/d2\_roll are double precision ✅
  + ingested\_at has default now() ✅

**What needs updating in the document (based on DB truth + your
Codex excerpts)**

**1) id type differs between v1 and v2**

* cmc\_ema\_multi\_tf.id = **integer**
* cmc\_ema\_multi\_tf\_v2.id = **bigint**

Your doc currently says **INTEGER** for both.

**Doc fix:**  
Change id definition to:

Type: INTEGER (v1) / BIGINT (v2).  
Semantics are the same; type differs due to ingestion / upstream
typing.

(Or, better: standardize later, but for now the doc must reflect
reality.)

**2) Nullability differs for tf\_days and roll between v1 and
v2**

* v1: tf\_days **nullable**, roll
  **nullable**
* v2: tf\_days **NOT NULL**, roll **NOT
  NULL**

Your doc implies both are always present and defined.

**Doc fix:**  
Add a “DB constraints” note:

In v1, tf\_days and roll may be NULL (historical rows or earlier
refresh versions).  
In v2, both are required (NOT NULL).

**3) v1 behavior section must be corrected (implementation
mismatch)**

Based on your Codex code excerpts, the doc needs these
corrections:

* Remove “rolling rows use daily alpha; canonical rows use bar
  alpha.”
* Replace “EMA resets” with “canonical rows snap to bar EMA;
  preview rows are computed off last bar EMA state.”

I’d update the v1 section to something like:

v1 uses tf-day bar closes as canonical anchors. For non-bar days, an
EMA preview is computed using alpha\_bar = 2/(period+1) applied to
today’s close and the previous bar EMA state carried forward. On
canonical bar timestamps, the stored EMA value is set to the bar EMA.
This can create discontinuities at canonical timestamps, but it is not a
reinitialization.

**4) Canonical vs rolling definition must be split by
version**

Your doc currently uses a single modulo-from-origin description.
That’s not true for v1.

Replace with:

* **v1:** roll = NOT (ts in bar\_close\_ts\_set) (bar
  timestamps are canonical)
* **v2:** canonical rows are every tf\_days-th daily
  bar using 1-based indexing: ((day\_index+1) % tf\_days) == 0 (origin is
  the start of the series window used for the computation)

**5) Add one explicit sentence about d1\_roll/d2\_roll storage
behavior**

Your doc is conceptually right, but add this DB-aligned line:

d1\_roll and d2\_roll are populated only on roll = FALSE rows; they are
NULL on roll = TRUE rows.

That matches the code and the nullable schema.
