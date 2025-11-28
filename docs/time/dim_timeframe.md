# dim_timeframe

Canonical definition of all supported timeframes used in ta_lab2.

## Purpose
Defines:
- tf_day horizons (pure spans like 1D, 63D, 945D)
- weekly semantic aliases (1W, 2W...)
- calendar-aligned frames (1W_CAL, 1M_CAL, 1Y_CAL)
- roll policies, anchors, and tf_days_nominal

## SQL Reference
Defined in:
- `sql/lookups/010_dim_timeframe_create.sql`
- `011_dim_timeframe_insert_daily.sql`
- `012_dim_timeframe_insert_weekly.sql`
- `013_dim_timeframe_insert_monthly.sql`
- `014_dim_timeframe_insert_yearly.sql`

## Conceptual Diagram

```
tf_day (pure)
  |
  +-- semantic aliases (1W, 2W, 10W)
  |
  +-- calendar-aligned (_CAL) ----------------+
        |                                     |
     EOM, EOQ, WEEK_END, EOY anchors      roll_policy=calendar_anchor
```

## Fields
| Column | Meaning |
|--------|---------|
| tf | Unique timeframe name |
| base_unit | D/W/M/Y |
| tf_qty | Quantity of base_unit |
| tf_days_nominal | Nominal span in days |
| alignment_type | tf_day or calendar |
| calendar_anchor | null/EOM/EOQ/EOY/WEEK_END |
| roll_policy | multiple_of_tf or calendar_anchor |
| has_roll_flag | use roll semantics |
| sort_order | deterministic ordering |
| description | human readable |

## How Computation Uses dim_timeframe
- EMA selects alpha via span_days = tf_days_nominal * period
- Calendar frames determine roll=True events
- Multi-TF EMA joins dim_timeframe to classify nodes

