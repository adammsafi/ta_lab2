---
title: "Updating Price Data Rough"
author: "Adam Safi"
created: 2025-11-16T23:45:00+00:00
modified: 2025-11-16T23:50:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\ProcessDocuments\Updating Price Data Rough.docx"
original_size_bytes: 23392
---
Updating Price Data – Rough

Gotcha, so now we’re talking **pipelines**, not tests:
you don’t want ema.py and ema\_multi\_timeframe.py to recompute 15 years
of BTC every time you add 3 new days.

Let’s treat this in two layers:

* **Daily EMAs → cmc\_ema\_daily** (ema.py)
* **Multi-TF EMAs → cmc\_ema\_multi\_tf**
  (ema\_multi\_timeframe.py)

And design them to be **incremental +
self-healing**.

---

**Big picture: how we want this to behave**

For both scripts:

1. **First time / backfill**

   * If the EMA table is empty for an asset → run from a global start
     (e.g. 2010-01-01).
2. **Normal daily run**

   * Look at what’s already in the EMA table.
   * Pick a **short “warmup” window** that goes a bit
     **before** the last computed ts.
   * Recompute EMAs only from that point forward and upsert.
3. **Occasional full recompute** (optional)

   * If you change core logic (e.g. EMA definition, tf mapping), you
     run the script with start="2010-01-01" once, accept that it’s heavier,
     and then go back to incremental mode.

The warmup is important: EMAs are path-dependent, but if you
recompute the last, say, 200–400 days, you:

* avoid re-running from 2010, and
* guarantee continuity, because overlapping rows get overwritten
  with consistent values.

---

**A. Incremental strategy for ema.py
(cmc\_ema\_daily)**

I don’t have the file here, but given your schema it almost
certainly:

* pulls daily OHLCV for a given id over [start, end],
* computes EMAs with something like ewm(span=period,
  min\_periods=period),
* writes to cmc\_ema\_daily with ON CONFLICT (id, ts, period) DO
  UPDATE.

**1. Decide a warmup window**

Pick something like:

* DAILY\_EMA\_WARMUP\_DAYS = 365 (or 2× max period if you want to be
  tight; e.g. if max period is 200, warmup 400 days).

This is just “how far back do I recompute from the last EMA
point.”

**2. Get the incremental start from the DB**

Per asset, or globally if you run per asset:

SELECT MAX(ts) AS last\_ema\_ts

FROM cmc\_ema\_daily

WHERE id = :asset\_id;

Pseudo-Python:

from datetime import timedelta

def get\_daily\_ema\_window(conn, asset\_id, fallback\_start="2010-01-01",
warmup\_days=365):

last\_ts = conn.execute(

text("""

SELECT MAX(ts) AS last\_ema\_ts

FROM public.cmc\_ema\_daily

WHERE id = :id

"""),

{"id": asset\_id},

).scalar()

if last\_ts is None:

# first run for this id

start = fallback\_start

else:

start = (last\_ts.date() -
timedelta(days=warmup\_days)).isoformat()

# end=None → “up to latest available price” in your loader

return start, None

Then in **ema.py**, instead of hard-coding
start="2010-01-01":

* if user passes start, respect it
* if user leaves start=None, do:

if incremental and start is None:

start, end = get\_daily\_ema\_window(conn, asset\_id=...,
warmup\_days=365)

So one “daily task” could be:

* connect to DB,
* for each id in [1, 1027, 1839, ...]:

  + call get\_daily\_ema\_window,
  + call your existing “compute & write EMAs” function over that
    smaller window.

Because you’re doing INSERT ... ON CONFLICT DO UPDATE, any
overlapping EMAs get cleanly overwritten, and new ones get appended.

---

**B. Incremental strategy for ema\_multi\_timeframe.py
(cmc\_ema\_multi\_tf)**

We actually *do* have this file, and it already has a nice
structure:

* build\_multi\_timeframe\_ema\_frame(...)

  + calls load\_cmc\_ohlcv\_daily(ids, start, end, ...)
  + computes multi-TF EMAs on the **daily grid**,
    including roll, d1, d2, d1\_roll, d2\_roll.
* write\_multi\_timeframe\_ema\_to\_db(...)

  + calls build\_multi\_timeframe\_ema\_frame(...)
  + writes into cmc\_ema\_multi\_tf via INSERT ... ON CONFLICT (id, tf,
    ts, period) DO UPDATE.

Right now, both build\_multi\_timeframe\_ema\_frame and
write\_multi\_timeframe\_ema\_to\_db default to:

start: str = "2010-01-01"

So unless you override it, you **always** reload from
2010.

We want the exact same pattern as for daily EMAs, but with a slightly
bigger warmup that’s keyed to **effective period**:

* effective\_period = period \* tf\_days[tf]

**1. Pick a warmup rule for multi-TF**

Options:

* **Simple**: fixed warmup, e.g. MULTI\_TF\_WARMUP\_DAYS
  = 720 (2 years).
* **Smarter**: warmup = k × max\_effective\_period,
  e.g.

> max\_effective = max(p \* TF\_DAYS[tf] for tf in tfs for p in
> ema\_periods)
>
> warmup\_days = 3 \* max\_effective

For you, with big tfs like 12M and periods up to 200, max\_effective
can be large, so a fixed warmup like 1–2 years is probably enough, since
you’re recomputing slopes and EMAs exactly from the source prices.

**2. Get incremental start from cmc\_ema\_multi\_tf**

Same pattern:

SELECT MAX(ts) AS last\_tf\_ema\_ts

FROM cmc\_ema\_multi\_tf

WHERE id = ANY(:ids);

Or per id if you process them separately.

Pseudo-Python (per batch of ids):

from datetime import timedelta

def get\_multi\_tf\_window(conn, ids, fallback\_start="2010-01-01",
warmup\_days=720):

ids = list(ids)

if not ids:

raise ValueError("ids must be non-empty")

last\_ts = conn.execute(

text("""

SELECT MAX(ts) AS last\_ts

FROM public.cmc\_ema\_multi\_tf

WHERE id = ANY(:ids)

"""),

{"ids": ids},

).scalar()

if last\_ts is None:

# first run for this group of ids

start = fallback\_start

else:

start = (last\_ts.date() -
timedelta(days=warmup\_days)).isoformat()

return start, None # end=None → latest price

Then in write\_multi\_timeframe\_ema\_to\_db:

* Add params incremental: bool = True and maybe warmup\_days: int =
  720.
* If incremental and start is None, compute it from DB:

def write\_multi\_timeframe\_ema\_to\_db(

ids: Iterable[int],

start: str | None = None,

end: str | None = None,

ema\_periods: Iterable[int] = (10, 21, 50, 100, 200),

tfs: Dict[str, str] | None = None,

\*,

db\_url: str | None = None,

schema: str = "public",

price\_table: str = "cmc\_price\_histories7",

out\_table: str = "cmc\_ema\_multi\_tf",

incremental: bool = True,

warmup\_days: int = 720,

) -> int:

engine = \_get\_engine(db\_url)

with engine.begin() as conn:

if incremental and start is None:

start, end = get\_multi\_tf\_window(conn, ids,
fallback\_start="2010-01-01", warmup\_days=warmup\_days)

frame = build\_multi\_timeframe\_ema\_frame(

ids=ids,

start=start,

end=end,

ema\_periods=ema\_periods,

tfs=tfs,

db\_url=db\_url,

)

# existing temp-table + upsert logic stays the same

That way:

* First run (table empty) → last\_ts is None → start from
  2010-01-01.
* Daily run later → last\_ts might be e.g. 2025-11-15 → start from
  ~2023-11-15; recompute last 2 years and upsert.

You avoid reprocessing 2010–2023 every single time.

---

**C. Coordination between daily EMAs and multi-TF
EMAs**

You don’t strictly *need* daily EMAs to compute multi-TF EMAs
(they’re using raw closes + compute\_ema with effective periods), but
conceptually:

* It’s nice if **both** scripts follow the same
  incremental pattern:

  + daily EMA script up to date for each id,
  + then multi-TF script runs on the same latest timeclose
    grid.

If you want to be extra neat, you can:

* Ensure **daily EMAs are run first** (per id / per
  day).
* Let multi-TF script use end=None (→ up to latest daily price) and
  its own incremental start.

---

**D. How this looks operationally**

What you’d actually run on a “new data day”:

1. Ingest new rows into cmc\_price\_histories7 (for BTC, ETH,
   etc).
2. Run **ema.py** in incremental mode:

   * For each id or batch of ids, compute start from cmc\_ema\_daily
     using last\_ema\_ts - warmup\_days.
   * Compute and upsert daily EMAs.
3. Run **ema\_multi\_timeframe.py** in incremental
   mode:

   * Compute start from cmc\_ema\_multi\_tf using last\_ts -
     warmup\_days.
   * Compute and upsert multi-TF EMAs.

No touching 2010 data unless you explicitly ask it to.

---

If you’d like, next step I can do is:

* sketch the exact helper(s) and updated signatures for
  **both** ema.py and ema\_multi\_timeframe.py (copy-paste
  style),
* keeping your current behavior as the default when
  incremental=False, but making the “smart incremental” behavior kick in
  when you omit start.