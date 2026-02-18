CREATE TABLE IF NOT EXISTS public.dim_timeframe
(
    tf text NOT NULL,
    label text NOT NULL,
    base_unit text NOT NULL,
    tf_qty integer NOT NULL,
    tf_days_nominal integer NOT NULL,
    alignment_type text NOT NULL,
    calendar_anchor text,
    roll_policy text NOT NULL,
    has_roll_flag boolean NOT NULL DEFAULT true,
    is_intraday boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL,
    description text,
    is_canonical boolean NOT NULL DEFAULT false,
    calendar_scheme text,
    allow_partial_start boolean NOT NULL DEFAULT false,
    allow_partial_end boolean NOT NULL DEFAULT false,
    tf_days_min integer,
    tf_days_max integer,

    CONSTRAINT dim_timeframe_tf_pk PRIMARY KEY (tf),

    CONSTRAINT dim_timeframe_base_unit_check CHECK (base_unit = ANY (ARRAY['D','W','M','Q','Y'])),
    CONSTRAINT dim_timeframe_tf_qty_check CHECK (tf_qty > 0),
    CONSTRAINT dim_timeframe_tf_days_nominal_check CHECK (tf_days_nominal > 0),
    CONSTRAINT dim_timeframe_alignment_type_check CHECK (alignment_type = ANY (ARRAY['tf_day','calendar'])),
    CONSTRAINT dim_timeframe_roll_policy_check CHECK (roll_policy = ANY (ARRAY['multiple_of_tf','calendar_anchor'])),
    CONSTRAINT dim_timeframe_sort_order_check CHECK (sort_order > 0),
    CONSTRAINT dim_timeframe_calendar_anchor_check CHECK (calendar_anchor IS NULL OR (calendar_anchor = ANY (ARRAY['EOM','EOQ','EOY','WEEK_END','ISO-WEEK']))),
    CONSTRAINT dim_timeframe_tf_days_min_le_max CHECK (tf_days_min IS NULL OR tf_days_max IS NULL OR tf_days_min <= tf_days_max),

    CONSTRAINT dim_tf_calendar_fields_by_alignment
      CHECK (
        (alignment_type = 'tf_day'
          AND calendar_anchor IS NULL
          AND calendar_scheme IS NULL
          AND allow_partial_start = FALSE
          AND allow_partial_end   = FALSE
          AND roll_policy = 'multiple_of_tf'
        )
        OR
        (alignment_type = 'calendar'
          AND calendar_anchor IS NOT NULL
          AND roll_policy = 'calendar_anchor'
        )
      ),

    CONSTRAINT dim_tf_calendar_scheme_allowed
      CHECK (calendar_scheme IS NULL OR calendar_scheme IN ('US','ISO')),

    CONSTRAINT dim_tf_semantic_unique
      UNIQUE (
        alignment_type,
        tf_days_nominal,
        calendar_anchor,
        calendar_scheme,
        allow_partial_start,
        allow_partial_end
      )
);
