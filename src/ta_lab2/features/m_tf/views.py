from __future__ import annotations

"""
SQL view definitions for the EMA pipeline.

These constants are imported by `refresh_cmc_emas.py` to (re)create
the helper views:

- public.all_emas
- public.cmc_price_with_emas
- public.cmc_price_with_emas_d1d2

If you ever want to change the shape of the views, you only need to
edit this file.
"""

# Combines daily and multi-timeframe EMAs into one tall view
VIEW_ALL_EMAS_SQL = """
CREATE OR REPLACE VIEW public.all_emas AS
    -- Daily EMAs (tf = '1D')
    SELECT
        d.id,
        d.ts,
        '1D'::text AS tf,
        1          AS tf_days,
        d.period,
        d.ema,
        d.d1_roll AS d1,
        d.d2_roll AS d2,
        d.d1      AS d1_close,
        d.d2      AS d2_close,
        d.roll
    FROM public.cmc_ema_daily d

    UNION ALL

    -- Multi-timeframe EMAs (2D, 3D, 1W, 1M, …)
    SELECT
        m.id,
        m.ts,
        m.tf,
        m.tf_days,
        m.period,
        m.ema,
        m.d1_roll AS d1,
        m.d2_roll AS d2,
        m.d1      AS d1_close,
        m.d2      AS d2_close,
        m.roll
    FROM public.cmc_ema_multi_tf m;
"""


# Joins daily prices to all EMA rows (tall, not pivoted)
VIEW_PRICE_WITH_EMAS_SQL = """
CREATE OR REPLACE VIEW public.cmc_price_with_emas AS
SELECT
    p.*,
    e.tf,
    e.tf_days,
    e.period,
    e.ema,
    e.d1,
    e.d2,
    e.d1_close,
    e.d2_close,
    e.roll
FROM public.cmc_price_histories7 p
LEFT JOIN public.all_emas e
  ON e.id = p.id
 AND e.ts = p."timestamp";
"""


# For now this is just an alias of cmc_price_with_emas.
# If you later want a more specialised view (e.g. only canonical
# bars, or only certain periods), you can change the definition here.
VIEW_PRICE_WITH_EMAS_D1D2_SQL = """
CREATE OR REPLACE VIEW public.cmc_price_with_emas_d1d2 AS
SELECT *
FROM public.cmc_price_with_emas;
"""
