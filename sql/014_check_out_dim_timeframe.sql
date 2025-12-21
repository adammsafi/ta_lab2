SELECT tf, sort_order
FROM dim_timeframe
ORDER BY sort_order;

INSERT INTO dim_timeframe (
    tf,
    label,
    base_unit,
    tf_qty,
    tf_days_nominal,
    alignment_type,
    calendar_anchor,
    roll_policy,
    has_roll_flag,
    sort_order,
    description
)
VALUES
    ('1M',  '1-month',       'M',  1,  30,
     'tf_day', NULL, 'multiple_of_tf', true, 110,
     'Approx 1-month window (~30 days), tf_day style'),

    ('2M',  '2-month',       'M',  2,  60,
     'tf_day', NULL, 'multiple_of_tf', true, 111,
     'Approx 2-month window (~60 days), tf_day style'),

    ('3M',  '3-month',       'M',  3,  90,
     'tf_day', NULL, 'multiple_of_tf', true, 112,
     'Approx 3-month window (~90 days), tf_day style'),

    ('6M',  '6-month',       'M',  6, 180,
     'tf_day', NULL, 'multiple_of_tf', true, 113,
     'Approx 6-month window (~180 days), tf_day style'),

    ('9M',  '9-month',       'M',  9, 270,
     'tf_day', NULL, 'multiple_of_tf', true, 114,
     'Approx 9-month window (~270 days), tf_day style'),

    ('12M', '12-month (1Y)', 'M', 12, 365,
     'tf_day', NULL, 'multiple_of_tf', true, 115,
     'Approx 12-month window (~1Y), tf_day style');
