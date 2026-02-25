-- v_cmc_positions_agg: Aggregate position view across all non-aggregate exchanges.
-- Computes weighted average cost basis using absolute quantity as weights.
-- Reference DDL -- actual migration is in alembic/versions/9e692eb7b762_order_fill_store.py

CREATE OR REPLACE VIEW public.v_cmc_positions_agg AS
SELECT
    asset_id,
    'aggregate'::TEXT                                   AS exchange,
    SUM(quantity)                                       AS quantity,
    CASE
        WHEN SUM(ABS(quantity)) = 0 THEN 0
        ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
    END                                                 AS avg_cost_basis,
    SUM(realized_pnl)                                   AS realized_pnl,
    SUM(COALESCE(unrealized_pnl, 0))                   AS unrealized_pnl,
    MAX(last_mark_price)                                AS last_mark_price,
    MAX(last_updated)                                   AS last_updated
FROM public.cmc_positions
WHERE exchange != 'aggregate'
GROUP BY asset_id;

COMMENT ON VIEW public.v_cmc_positions_agg IS
    'Aggregate position across all exchanges per asset_id. '
    'Uses weighted average cost basis (weight = ABS(quantity)). '
    'Excludes rows where exchange = ''aggregate'' to prevent double-counting.';
