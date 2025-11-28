-- === Calendar month frames (CAL versions only) ===
-- Non-calendar equivalents already exist in the 98 *_D horizons
-- (30D ~ 1M, 60D ~ 2M, 90D ~ 3M, 180D ~ 6M, 270D ~ 9M, 360D ~ 12M).

INSERT INTO dim_timeframe
(tf, label, base_unit, tf_qty, tf_days_nominal,
 alignment_type, calendar_anchor, roll_policy,
 has_roll_flag, is_intraday, sort_order, description)
VALUES
('1M_CAL', '1 month (EOM)', 'M', 1, 30,
 'calendar', 'EOM', 'calendar_anchor',
 true, false, 300, 'Calendar month, rolled at end-of-month'),

('2M_CAL', '2 months (EOM)', 'M', 2, 60,
 'calendar', 'EOM', 'calendar_anchor',
 true, false, 301, '2-month calendar window, rolled at end-of-month'),

('3M_CAL', '3 months (EOQ-ish)', 'M', 3, 90,
 'calendar', 'EOQ', 'calendar_anchor',
 true, false, 302, 'Quarterly calendar window, rolled at end-of-quarter'),

('6M_CAL', '6 months (semi-annual)', 'M', 6, 180,
 'calendar', 'EOQ', 'calendar_anchor',
 true, false, 303, 'Semi-annual calendar window, rolled at quarter/half-year boundaries'),

('9M_CAL', '9 months', 'M', 9, 270,
 'calendar', 'EOQ', 'calendar_anchor',
 true, false, 304, '9-month calendar window, aligned to quarter ends'),

('12M_CAL', '12 months (EOY)', 'M', 12, 360,
 'calendar', 'EOY', 'calendar_anchor',
 true, false, 305, '12-month / 1-year calendar window expressed in months')
ON CONFLICT (tf) DO NOTHING;
