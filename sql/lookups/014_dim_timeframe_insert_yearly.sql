-- === Calendar year frames (CAL versions only) ===
-- Non-calendar equivalents (1Y horizon, 2Y horizon, ...) live in *_D rows like 365D, 730D, ... up to 7300D.

INSERT INTO dim_timeframe
(tf, label, base_unit, tf_qty, tf_days_nominal,
 alignment_type, calendar_anchor, roll_policy,
 has_roll_flag, is_intraday, sort_order, description)
VALUES
('1Y_CAL', '1 year (EOY)', 'Y', 1, 365,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 350, '1-year calendar window, rolled at end-of-year'),

('2Y_CAL', '2 years (EOY)', 'Y', 2, 730,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 351, '2-year calendar window, rolled at end-of-year'),

('3Y_CAL', '3 years (EOY)', 'Y', 3, 1095,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 352, '3-year calendar window, rolled at end-of-year'),

('4Y_CAL', '4 years (EOY)', 'Y', 4, 1460,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 353, '4-year calendar window, rolled at end-of-year'),

('5Y_CAL', '5 years (EOY)', 'Y', 5, 1825,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 354, '5-year calendar window, rolled at end-of-year'),

('6Y_CAL', '6 years (EOY)', 'Y', 6, 2190,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 355, '6-year calendar window, rolled at end-of-year'),

('7Y_CAL', '7 years (EOY)', 'Y', 7, 2555,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 356, '7-year calendar window, rolled at end-of-year'),

('8Y_CAL', '8 years (EOY)', 'Y', 8, 2920,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 357, '8-year calendar window, rolled at end-of-year'),

('9Y_CAL', '9 years (EOY)', 'Y', 9, 3285,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 358, '9-year calendar window, rolled at end-of-year'),

('10Y_CAL', '10 years (EOY)', 'Y', 10, 3650,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 359, '10-year calendar window, rolled at end-of-year'),

('11Y_CAL', '11 years (EOY)', 'Y', 11, 4015,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 360, '11-year calendar window, rolled at end-of-year'),

('12Y_CAL', '12 years (EOY)', 'Y', 12, 4380,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 361, '12-year calendar window, rolled at end-of-year'),

('13Y_CAL', '13 years (EOY)', 'Y', 13, 4745,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 362, '13-year calendar window, rolled at end-of-year'),

('14Y_CAL', '14 years (EOY)', 'Y', 14, 5110,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 363, '14-year calendar window, rolled at end-of-year'),

('15Y_CAL', '15 years (EOY)', 'Y', 15, 5475,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 364, '15-year calendar window, rolled at end-of-year'),

('16Y_CAL', '16 years (EOY)', 'Y', 16, 5840,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 365, '16-year calendar window, rolled at end-of-year'),

('17Y_CAL', '17 years (EOY)', 'Y', 17, 6205,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 366, '17-year calendar window, rolled at end-of-year'),

('18Y_CAL', '18 years (EOY)', 'Y', 18, 6570,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 367, '18-year calendar window, rolled at end-of-year'),

('19Y_CAL', '19 years (EOY)', 'Y', 19, 6935,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 368, '19-year calendar window, rolled at end-of-year'),

('20Y_CAL', '20 years (EOY)', 'Y', 20, 7300,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 369, '20-year calendar window, rolled at end-of-year')
ON CONFLICT (tf) DO NOTHING;
