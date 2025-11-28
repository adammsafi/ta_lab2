CREATE TABLE IF NOT EXISTS dim_timeframe (
    tf               text PRIMARY KEY,  -- e.g. '1D', '5D', '1W', '1M', '1Y', '1W_CAL'
    label            text NOT NULL,     -- human-readable name
    base_unit        text NOT NULL CHECK (base_unit IN ('D','W','M','Q','Y')),
    tf_qty           integer NOT NULL CHECK (tf_qty > 0),

    -- Nominal number of days this timeframe roughly covers.
    -- For calendar frames this is approximate (e.g. 30 for 1M, 90 for 3M, 365 for 1Y).
    tf_days_nominal  integer NOT NULL CHECK (tf_days_nominal > 0),

    -- How this timeframe is aligned:
    --  - 'tf_day'   : purely N-day horizons (e.g., 5D, 10D, 45D, 63D)
    --  - 'calendar' : aligned to calendar boundaries (EOM, EOQ, WEEK_END, EOY)
    alignment_type   text NOT NULL CHECK (alignment_type IN ('tf_day','calendar')),

    -- For calendar frames, where they anchor:
    --  - 'EOM'      : end-of-month
    --  - 'EOQ'      : end-of-quarter
    --  - 'EOY'      : end-of-year
    --  - 'WEEK_END' : end-of-week (market-specific DOW via trading calendar)
    -- NULL for pure tf_day frames.
    calendar_anchor  text NULL CHECK (
        calendar_anchor IS NULL
        OR calendar_anchor IN ('EOM','EOQ','EOY','WEEK_END')
    ),

    -- How roll flags should be interpreted:
    --  - 'multiple_of_tf' : roll=true on bars that are integer multiples of this TF
    --  - 'calendar_anchor': roll=true on calendar anchors (EOM, EOQ, WEEK_END, EOY)
    roll_policy      text NOT NULL CHECK (roll_policy IN ('multiple_of_tf','calendar_anchor')),

    -- Whether roll semantics are defined / meaningful for this timeframe.
    has_roll_flag    boolean NOT NULL DEFAULT true,

    -- For future extension to intraday (e.g., '1H', '4H', '15m').
    is_intraday      boolean NOT NULL DEFAULT false,

    -- For stable ordering in queries and UIs.
    sort_order       integer NOT NULL CHECK (sort_order > 0),

    description      text
);
