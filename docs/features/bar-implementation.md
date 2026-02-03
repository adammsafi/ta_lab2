---
title: "bar_implementation"
author: "Adam Safi"
created: 2026-01-02T17:39:00+00:00
modified: 2026-01-02T18:09:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\Bars\DesriptiveDocuments\bar_implementation.docx"
original_size_bytes: 29724
---
**Behaviors both should standardize**

**1) Deterministic time\_high/time\_low tie-break**

Adopt **cal\_us’s explicit tie-break rule** everywhere:
“earliest timestamp among ties.” It prevents flaky mismatches when
highs/lows repeat and you have multiple equal maxima/minima. (Your
cal\_us script already encodes this as a helper; multi\_tf should do the
same.)

**Why it matters:** makes OHLC correctness tests stable
and eliminates “why did time\_high move?” surprises.

**2) The “1 row per local day” guardrail**

Adopt **cal\_us’s \_assert\_one\_row\_per\_local\_day** (or
equivalent) in multi\_tf.

**Why it matters:** rolling bars assume *daily*
cadence. If ingestion ever duplicates a day in local time (DST/UTC
conversion bugs, reorg artifacts, vendor issues), multi\_tf silently
produces wrong bars. Failing fast is better.

**3) Missing-days diagnostics, but adapt to each
model**

* cal\_us already has rich diagnostics (start/end/interior + date
  list).
* multi\_tf currently treats everything as “interior” and doesn’t
  track *where*.

**Recommendation:** lift the **diagnostic
richness** into multi\_tf, but define “where” appropriately:

* For rolling N-day bars: “start” means missing days before the
  first observed day inside the bar window, “end” means missing between
  last observed day and snapshot day, “interior” means gaps between
  observed days.
* For cal\_us: keep as-is (it’s already calendar-correct).

**Why it matters:** when something looks off, you can
quickly determine whether it’s a data issue or a boundary/logic
issue.

**4) Watermark/state reconciliation logic**

Both should implement the same “triage” behaviors cleanly:

* **state missing but bars exist → seed state from
  bars**
* **state exists but bars missing → rebuild**
* **daily\_min moved earlier → rebuild**
* **daily\_max <= last\_time\_close → noop but bump
  watermarks**

Your cal\_us “updated” style worker already has a full triage ladder;
ensure multi\_tf matches that structure as well (if it doesn’t already in
your current version).

**Why it matters:** these are operational realities, not
timeframe semantics.

**5) Snapshot key + upsert consistency**

Standardize the uniqueness and upsert semantics:

* Primary key: (id, tf, bar\_seq, time\_close) is correct for daily
  snapshots.
* Ensure both scripts never “invent” a new bar\_seq for an existing
  time\_close (that’s the classic corruption pattern).

**Why it matters:** makes downstream analytics and QA
tables reliable across both families.

**Behaviors each could borrow selectively**

**What cal\_us should borrow from multi\_tf**

1. **Incremental carry-forward when safe**  
   If cal\_us recomputes from bar\_start often, it can be slow. Borrow
   multi\_tf’s carry-forward pattern *only when invariants
   hold*:

* same bar\_seq
* last snapshot day is exactly yesterday in local time
* no missing days
* extrema tie-break still deterministic

Then you can do constant-time update of high/low/volume and
close.

2. **Pluggable “tf\_days” for weekly buckets**  
   Weeks are fixed; you can treat W as 7\*n always. That makes optimization
   easier and reduces per-snapshot calendar computations.

**What multi\_tf should borrow from cal\_us**

1. **Explicit semantic invariants**  
   Cal\_us is very explicit about what it guarantees (no partial-start,
   etc.). Multi\_tf should document and enforce:

* what time\_open means in rolling bars
* whether bar\_seq is row-count-based vs time-window-based
* how missing days are handled (do they “count” as empty days or
  compress time?)

2. **Better missing-day definition**  
   Instead of timestamp diffs only, define missing days based on local
   dates expected between bar\_start and snapshot day, same as cal\_us. This
   avoids DST and timezone weirdness.

**One thing they should *not* adopt from each
other**

* multi\_tf should **not** adopt cal\_us’s “start at
  first full calendar boundary” rule; it defeats rolling
  semantics.
* cal\_us should **not** adopt multi\_tf’s “nominal
  30/365 day months/years” style; it breaks true calendar
  alignment.

**If you want a clean standard**

I’d define a shared “snapshot contract” that both builders
follow:

* Shared invariants (always true): keys, tie-breaks, missing-day
  counters, one-row-per-local-day
* Model-specific parts: bar indexing and bar boundaries (rolling vs
  calendar)
* Shared incremental triage ladder (state/table/daily min/max
  reconciliation)

If you tell me which parts you value most (speed vs debuggability vs
strict invariants), I can recommend the exact minimal set of refactors
that will pay off immediately without conflating the two bar
definitions.

Yes give me a clean standard

Below is a **clean, unified standard** you can adopt for
both multi\_tf (rolling N-day) and cal\_us (calendar-aligned) without
blurring their different semantics. Think of it as a **Bar
Snapshot Contract + Builder Interface + Incremental Driver
Rules**.

**Bar Snapshot Standard**

**A) Canonical model**

**1) What a “snapshot row” is**

Snapshot rows correspond to preview observations (and the final
canonical observation) as defined in the bar-creation specification.
Preview rows are identified by roll = true.

**Primary key (MUST):**

* (id, tf, bar\_seq, time\_close)

**Meaning:**

* time\_close = the daily close timestamp (UTC) for that snapshot
  day
* bar\_seq = the bar number for that timeframe, *per
  id*
* Multiple snapshots per bar\_seq exist while the bar is
  forming

**Semantic vs snapshot identity:**  
A semantic bar is defined by its interval (start and end timestamps). A
snapshot row represents the state of that semantic bar as-of a specific
daily close. Snapshot identity (id, tf, bar\_seq, time\_close) is a
storage key and does not redefine the semantic bar.

**2) Required output columns (shared contract)**

Both pipelines MUST write these columns, with identical
semantics:

**Identity / time**

* id (int64)
* tf (text)
* bar\_seq (int64)
* time\_open (timestamptz, UTC)
* time\_close (timestamptz, UTC)
* time\_high (timestamptz, UTC or NULL)
* time\_low (timestamptz, UTC or NULL)

**OHLCV + market data**

* open (double)
* high (double)
* low (double)
* close (double)
* volume (double)
* market\_cap (double)

**Bar completeness**

* tf\_days (int) ✅ for weeks/months/years this is bar length in
  days; for rolling bars this is fixed N
* pos\_in\_bar (int) ✅ Expected position within the bar based on
  elapsed calendar days from bar start. Missing days advance position even
  when no observation exists.
* is\_partial\_start (bool)
* is\_partial\_end (bool)

**Missing-days diagnostics**

* is\_missing\_days (bool)
* count\_days (int) ✅ number of local calendar days from
  bar\_start..snapshot\_day inclusive
* count\_missing\_days (int)
* count\_missing\_days\_start (int)
* count\_missing\_days\_end (int)
* count\_missing\_days\_interior (int)
* missing\_days\_where (text, nullable)

  + If missing: a **capped comma-separated list** of
    missing local dates YYYY-MM-DD (cap e.g. 50), plus optionally a suffix
    "...(+N more)"

**Operational**

* ingested\_at (timestamptz default now()) ✅ set on insert and
  update

If your existing tables don’t have all of these, the standard is
still the target. Add columns over time; until then, populate what
exists and keep the computation in code.

**B) Deterministic extrema timestamps (MUST)**

When computing time\_high / time\_low:

* high = max(high)
* time\_high = **earliest** timehigh (or ts if you
  don’t trust timehigh) among rows achieving that max
* low = min(low)
* time\_low = **earliest** timelow (or ts) among rows
  achieving that min

This tie-break rule MUST be identical across builders.

**C) “1 row per local day” invariant (MUST)**

Before building snapshots for an (id, tf) over a slice:

* Convert ts to local\_day = ts.tz\_convert(tz).date()
* Assert local\_day is unique

  + If duplicates exist: raise with a helpful error and sample
    offending days

This is *the* guardrail that prevents silent corruption.

**Builder Interface Standard**

You keep two different builders, but make them conform to one
interface and one set of invariants.

**A) Inputs (common)**

Builders receive:

* df\_daily: sorted by ts ascending, contains at least:

  + id, ts, open, high, low, close, volume, market\_cap, timehigh,
    timelow
* tz: "America/New\_York"
* tf\_spec: metadata used to map snapshot day → bar window and
  bar\_seq

**B) Two bar-indexing modes (explicit)**

Every tf\_spec has exactly one of these modes:

**Mode 1: Rolling (multi\_tf)**

* tf\_days = N and bar assignment is based on **observation
  order**
* The k-th daily row belongs to:

  + bar\_seq = floor((k-1)/N)+1
  + pos\_in\_bar = ((k-1) mod N)+1

**Missing days do NOT create synthetic rows.**  
They only show up in diagnostics.

**Mode 2: Calendar (cal\_us)**

* bar windows are **true calendar buckets** in local
  tz:

  + W: week buckets aligned to US week start rule (your existing
    rule)
  + M: calendar months (actual month length)
  + Y: calendar years (365/366)
* tf\_days is **the number of local days in that bar
  window** (month length, leap years)
* pos\_in\_bar = count\_days - count\_missing\_days\_start (or simply
  number of expected days elapsed within the bar), but you must define it
  consistently:

  + Recommended: pos\_in\_bar = count\_days (expected days
    elapsed)  
    and allow missing to be tracked separately via missing
    counters.

**Partial-start policy for calendar:**

* If allow\_partial\_start = FALSE (your current cal\_us posture), the
  first emitted bar must start at the **first full boundary**
  after data begins.
* That rule is part of tf\_spec (don’t hardcode it).

**Snapshot Emission Standard**

For a given (id, tf\_spec) and daily history:

**1) Emit exactly one snapshot per available daily
close**

Each daily close contributes at most one row.

**2) time\_open definition (standardized)**

time\_open = the UTC timestamp of the **local day open**
for the bar’s first local day:

* bar\_start\_day\_local @ 00:00:00.001 localized to tz then converted
  to UTC  
  (Your current “prev close + 1ms” can be made consistent with this; pick
  one standard and use it everywhere.)

**3) is\_partial\_end**

* True until snapshot\_day reaches the bar window’s scheduled end
  local day
* False only for the canonical final day snapshot

**4) is\_partial\_start**

* Rolling: always False (unless you introduce “start mid-stream”
  semantics)
* Calendar:

  + False if partial starts disallowed
  + True if allowed and the first bar began after bar\_start\_day but
    before full boundary

**Missing-days Diagnostics Standard**

For each snapshot day:

1. Compute bar\_start\_day\_local and snapshot\_day\_local
2. Expected days = every local date in [bar\_start\_day\_local,
   snapshot\_day\_local]
3. Observed days = local dates present in df rows used for this
   snapshot window
4. Missing = expected - observed

Then derive:

* count\_days = len(expected)
* count\_missing\_days = len(missing)
* count\_missing\_days\_start = missing days from bar\_start forward
  until first observed day
* count\_missing\_days\_end = missing days from last observed day
  until snapshot day
* count\_missing\_days\_interior = everything else
* missing\_days\_where = capped list of missing dates

This exact diagnostic algorithm should be shared code used by both
builders.

**Missing-days policy:** Snapshot emission is permitted
even when missing days exist and MUST surface complete diagnostics.
Canonical finalization is governed solely by the canonical close rule;
missing days do not independently block finalization.

**Incremental Driver Standard (shared triage
ladder)**

For each (id, tf):

1. Load daily min/max for id
2. Load state row (optional)
3. Load last snapshot info from bars table (optional)

Then:

**Case A: no state and no bars**

* Full build from daily history
* Upsert bars
* Write state

**Case B: no state but bars exist**

* Seed state from bars (last\_bar\_seq, last\_time\_close), and set
  daily\_min/max seen

**Case C: state exists but bars missing**

* Full rebuild (delete bars for id/tf then build)
* Write state

**Case D: backfill detected**

If daily\_min\_ts < state.daily\_min\_seen:

* Delete + full rebuild
* Write state

**Case E: no new data**

If daily\_max\_ts <= last\_time\_close:

* Noop (but update watermarks)

**Case F: forward append**

* Load a slice that covers:

  + the active bar window start day (or enough history to recompute
    the active bar)
  + plus all new days after last\_time\_close
* Recompute snapshots from the **active bar start**
  forward OR do carry-forward only when safe:

  + Safe carry-forward conditions:

    - last snapshot day == yesterday (local)
    - no missing days at tail
    - same bar window (calendar) or same bar\_seq with pos < tf\_days
      (rolling)
    - extrema tie-break deterministic helper in place

**Always upsert** appended snapshots, update state to
newest (bar\_seq, time\_close).

**Operational Standard**

**Parallelization (optional but
standard-compatible)**

Parallelize by **id** only (each worker handles all tfs
for one id). Requirements:

* Worker is top-level picklable
* Pool under if \_\_name\_\_ == "\_\_main\_\_":
* maxtasksperchild=50
* CLI --num-processes with clamp to cpu\_count()

**Batch DB patterns**

* Batch-load last snapshot info for all tfs per id (you already
  like this)
* Batch upsert bars (chunked execute\_many)

**Logging (same fields everywhere)**

For each tf:

* action: seed | rebuild | noop | append
* daily\_min\_ts, daily\_max\_ts
* last\_time\_close\_before, last\_time\_close\_after
* rows\_upserted
