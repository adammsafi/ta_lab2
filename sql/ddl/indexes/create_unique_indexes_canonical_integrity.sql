--A. Bar tables: canonical uniqueness
--Canonical bars = is_partial_end = FALSE
--Unique key = (id, tf, time_close)

-- BARS: canonical close uniqueness
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf__canon_close
ON public.cmc_price_bars_multi_tf (id, tf, time_close)
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_us__canon_close
ON public.cmc_price_bars_multi_tf_cal_us (id, tf, time_close)
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_iso__canon_close
ON public.cmc_price_bars_multi_tf_cal_iso (id, tf, time_close)
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_us__canon_close
ON public.cmc_price_bars_multi_tf_cal_anchor_us (id, tf, time_close)
WHERE is_partial_end = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_price_bars_multi_tf_cal_anchor_iso__canon_close
ON public.cmc_price_bars_multi_tf_cal_anchor_iso (id, tf, time_close)
WHERE is_partial_end = FALSE;


--B. EMA tables: canonical uniqueness
--Canonical EMA = roll = FALSE
	--For non-_u: unique key = (id, tf, period, ts) where roll=false
	--For _u: unique key = (id, tf, period, ts, alignment_source) where roll=false

-- EMA: canonical ts uniqueness
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf__canon_ts
ON public.cmc_ema_multi_tf (id, tf, period, ts)
WHERE roll = FALSE;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_ema_multi_tf_v2__canon_ts
ON public.cmc_ema_multi_tf_v2 (id, tf, period, ts)
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
--Key = (id, tf, time_close) (no roll/series concept)


-- RETURNS (bars): unique time_close per (id,tf)
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf__time_close
ON public.cmc_returns_bars_multi_tf (id, tf, time_close);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_us__time_close
ON public.cmc_returns_bars_multi_tf_cal_us (id, tf, time_close);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_iso__time_close
ON public.cmc_returns_bars_multi_tf_cal_iso (id, tf, time_close);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_anchor_us__time_close
ON public.cmc_returns_bars_multi_tf_cal_anchor_us (id, tf, time_close);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_cal_anchor_iso__time_close
ON public.cmc_returns_bars_multi_tf_cal_anchor_iso (id, tf, time_close);

-- If you actually have this table later, add it then:
-- CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_bars_multi_tf_u__time_close
-- ON public.cmc_returns_bars_multi_tf_u (id, tf, time_close);


--C2) Returns-from-EMA (non-_u)
--You just discovered the important bit: series is part of identity (ema vs ema_bar).
--Key = (id, tf, period, roll, ts, series)


-- RETURNS (ema): series matters
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf__key
ON public.cmc_returns_ema_multi_tf (id, tf, period, roll, ts, series);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_v2__key
ON public.cmc_returns_ema_multi_tf_v2 (id, tf, period, roll, ts, series);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_us__key
ON public.cmc_returns_ema_multi_tf_cal_us (id, tf, period, roll, ts, series);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_iso__key
ON public.cmc_returns_ema_multi_tf_cal_iso (id, tf, period, roll, ts, series);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_anchor_us__key
ON public.cmc_returns_ema_multi_tf_cal_anchor_us (id, tf, period, roll, ts, series);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_cal_anchor_iso__key
ON public.cmc_returns_ema_multi_tf_cal_anchor_iso (id, tf, period, roll, ts, series);


--C3) Returns-from-EMA _u
--Key = (id, tf, period, alignment_source, series, roll, ts)
-- RETURNS (ema_u): alignment_source + series both matter
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_cmc_returns_ema_multi_tf_u__key
ON public.cmc_returns_ema_multi_tf_u (id, tf, period, alignment_source, series, roll, ts);
