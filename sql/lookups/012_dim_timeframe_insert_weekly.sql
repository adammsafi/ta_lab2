-- === Weekly semantic frames (tf_day) ===
-- These sit on top of your daily horizons (7D, 14D, 21D, 28D, 42D, 56D, 70D)
-- but are named in weekly trader language.

INSERT INTO dim_timeframe
(tf, label, base_unit, tf_qty, tf_days_nominal,
 alignment_type, calendar_anchor, roll_policy,
 has_roll_flag, is_intraday, sort_order, description)
VALUES
('1W', '1 week (~7D rolling)', 'W', 1, 7,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 205, '1-week window treated as ~7-day tf_day span'),

('2W', '2 weeks (~14D rolling)', 'W', 2, 14,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 206, '2-week window treated as ~14-day tf_day span'),

('3W', '3 weeks (~21D rolling)', 'W', 3, 21,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 207, '3-week window treated as ~21-day tf_day span'),

('4W', '4 weeks (~28D rolling)', 'W', 4, 28,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 208, '4-week window treated as ~28-day tf_day span'),

('6W', '6 weeks (~42D rolling)', 'W', 6, 42,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 209, '6-week window treated as ~42-day tf_day span'),

('8W', '8 weeks (~56D rolling)', 'W', 8, 56,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 210, '8-week window treated as ~56-day tf_day span'),

('10W', '10 weeks (~70D rolling)', 'W', 10, 70,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 211, '10-week window treated as ~70-day tf_day span')
ON CONFLICT (tf) DO NOTHING;

-- === Weekly calendar-aligned frames (1W_CAL, 2W_CAL, ..., 10W_CAL) ===
-- These share nominal tf_days with their rolling siblings but are anchored to WEEK_END.

INSERT INTO dim_timeframe
(tf, label, base_unit, tf_qty, tf_days_nominal,
 alignment_type, calendar_anchor, roll_policy,
 has_roll_flag, is_intraday, sort_order, description)
VALUES
('1W_CAL', '1 week (calendar week end)', 'W', 1, 7,
 'calendar', 'WEEK_END', 'calendar_anchor',
 true, false, 220, 'Calendar-aligned week ending on market-specific WEEK_END'),

('2W_CAL', '2 weeks (calendar, week end)', 'W', 2, 14,
 'calendar', 'WEEK_END', 'calendar_anchor',
 true, false, 221, '2-week calendar window aggregated to every 2nd week end'),

('3W_CAL', '3 weeks (calendar, week end)', 'W', 3, 21,
 'calendar', 'WEEK_END', 'calendar_anchor',
 true, false, 222, '3-week calendar window aggregated to every 3rd week end'),

('4W_CAL', '4 weeks (calendar, week end)', 'W', 4, 28,
 'calendar', 'WEEK_END', 'calendar_anchor',
 true, false, 223, '4-week calendar window aggregated to every 4th week end'),

('6W_CAL', '6 weeks (calendar, week end)', 'W', 6, 42,
 'calendar', 'WEEK_END', 'calendar_anchor',
 true, false, 224, '6-week calendar window aggregated to every 6th week end'),

('8W_CAL', '8 weeks (calendar, week end)', 'W', 8, 56,
 'calendar', 'WEEK_END', 'calendar_anchor',
 true, false, 225, '8-week calendar window aggregated to every 8th week end'),

('10W_CAL', '10 weeks (calendar, week end)', 'W', 10, 70,
 'calendar', 'WEEK_END', 'calendar_anchor',
 true, false, 226, '10-week calendar window aggregated to every 10th week end')
ON CONFLICT (tf) DO NOTHING;
