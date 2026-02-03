ALTER TABLE dim_timeframe
    ADD COLUMN is_canonical BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE dim_timeframe
SET calendar_anchor = 'ISO-WEEK'
WHERE tf LIKE '%W_CAL';

SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conname = 'dim_timeframe_calendar_anchor_check';

ALTER TABLE dim_timeframe
DROP CONSTRAINT dim_timeframe_calendar_anchor_check;

ALTER TABLE dim_timeframe
ADD CONSTRAINT dim_timeframe_calendar_anchor_check
CHECK (
    calendar_anchor IS NULL
    OR calendar_anchor = ANY (
        ARRAY[
            'EOM'::text,
            'EOQ'::text,
            'EOY'::text,
            'WEEK_END'::text,
            'ISO-WEEK'::text
        ]
    )
);

UPDATE dim_timeframe
SET calendar_anchor = 'ISO-WEEK'
WHERE tf LIKE '%W_CAL';

s
