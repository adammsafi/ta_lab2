--A. Bar tables: canonical uniqueness
--Canonical bars = is_partial_end = FALSE
--Unique key = (id, tf, timestamp)

-- BARS: canonical close uniqueness
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf__canon_close
ON public.cmc_price_bars_multi_tf (id, tf, "timestamp")
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_us__canon_close
ON public.cmc_price_bars_multi_tf_cal_us (id, tf, "timestamp")
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_iso__canon_close
ON public.cmc_price_bars_multi_tf_cal_iso (id, tf, "timestamp")
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_us__canon_close
ON public.cmc_price_bars_multi_tf_cal_anchor_us (id, tf, "timestamp")
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_iso__canon_close
ON public.cmc_price_bars_multi_tf_cal_anchor_iso (id, tf, "timestamp")
WHERE is_partial_end = FALSE;


--B. EMA tables: canonical uniqueness
--Canonical EMA = roll = FALSE
	--For non-_u: unique key = (id, tf, period, ts) where roll=false
	--For _u: unique key = (id, tf, period, ts, alignment_source) where roll=false

-- EMA: canonical ts uniqueness
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf__canon_ts
ON public.cmc_ema_multi_tf (id, tf, period, ts)
WHERE roll = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf_cal_us__canon_ts
ON public.cmc_ema_multi_tf_cal_us (id, tf, period, ts)
WHERE roll = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf_cal_iso__canon_ts
ON public.cmc_ema_multi_tf_cal_iso (id, tf, period, ts)
WHERE roll = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf_cal_anchor_us__canon_ts
ON public.cmc_ema_multi_tf_cal_anchor_us (id, tf, period, ts)
WHERE roll = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf_cal_anchor_iso__canon_ts
ON public.cmc_ema_multi_tf_cal_anchor_iso (id, tf, period, ts)
WHERE roll = FALSE;

-- EMA_U: canonical must include alignment_source
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf_u__canon_ts
ON public.cmc_ema_multi_tf_u (id, tf, period, ts, alignment_source)
WHERE roll = FALSE;


--C. Returns tables: uniqueness
--C1) Returns-from-bars
--PK = (id, "timestamp", tf) — roll is a regular boolean column.

-- RETURNS (bars): unique timestamp per (id,tf)
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf__timestamp
ON public.cmc_returns_bars_multi_tf (id, tf, "timestamp");

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_us__timestamp
ON public.cmc_returns_bars_multi_tf_cal_us (id, tf, "timestamp");

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_iso__timestamp
ON public.cmc_returns_bars_multi_tf_cal_iso (id, tf, "timestamp");

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_anchor_us__timestamp
ON public.cmc_returns_bars_multi_tf_cal_anchor_us (id, tf, "timestamp");

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_anchor_iso__timestamp
ON public.cmc_returns_bars_multi_tf_cal_anchor_iso (id, tf, "timestamp");


--C2) Returns-from-EMA (non-_u)
--PK = (id, tf, period, ts) — roll is NOT part of PK.

-- RETURNS (ema): all non-_u tables share same PK structure
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf__key
ON public.cmc_returns_ema_multi_tf (id, tf, period, ts);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_us__key
ON public.cmc_returns_ema_multi_tf_cal_us (id, tf, period, ts);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_iso__key
ON public.cmc_returns_ema_multi_tf_cal_iso (id, tf, period, ts);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_anchor_us__key
ON public.cmc_returns_ema_multi_tf_cal_anchor_us (id, tf, period, ts);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_anchor_iso__key
ON public.cmc_returns_ema_multi_tf_cal_anchor_iso (id, tf, period, ts);


--C3) Returns-from-EMA _u
--PK = (id, tf, period, alignment_source, ts) — roll is NOT part of PK.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_u__key
ON public.cmc_returns_ema_multi_tf_u (id, tf, period, alignment_source, ts);
