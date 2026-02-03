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


INSERT INTO dim_timeframe
(tf, label, base_unit, tf_qty, tf_days_nominal,
 alignment_type, calendar_anchor, roll_policy,
 has_roll_flag, is_intraday, sort_order, description)
VALUES
-- === 98 pure daily tf_day timeframes built from unique(days) ===
('1D', '1 day', 'D', 1, 1,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 10, 'Pure 1-day tf_day horizon'),

('2D', '2 days', 'D', 2, 2,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 11, 'Pure 2-day tf_day horizon'),

('3D', '3 days', 'D', 3, 3,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 12, 'Pure 3-day tf_day horizon'),

('4D', '4 days', 'D', 4, 4,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 13, 'Pure 4-day tf_day horizon'),

('5D', '5 days', 'D', 5, 5,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 14, 'Pure 5-day tf_day horizon'),

('7D', '7 days', 'D', 7, 7,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 15, 'Pure 7-day tf_day horizon'),

('10D', '10 days', 'D', 10, 10,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 16, 'Pure 10-day tf_day horizon'),

('14D', '14 days', 'D', 14, 14,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 17, 'Pure 14-day tf_day horizon'),

('15D', '15 days', 'D', 15, 15,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 18, 'Pure 15-day tf_day horizon'),

('20D', '20 days', 'D', 20, 20,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 19, 'Pure 20-day tf_day horizon'),

('21D', '21 days', 'D', 21, 21,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 20, 'Pure 21-day tf_day horizon'),

('25D', '25 days', 'D', 25, 25,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 21, 'Pure 25-day tf_day horizon'),

('28D', '28 days', 'D', 28, 28,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 22, 'Pure 28-day tf_day horizon'),

('30D', '30 days', 'D', 30, 30,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 23, 'Pure 30-day tf_day horizon'),

('40D', '40 days', 'D', 40, 40,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 24, 'Pure 40-day tf_day horizon'),

('42D', '42 days', 'D', 42, 42,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 25, 'Pure 42-day tf_day horizon'),

('45D', '45 days', 'D', 45, 45,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 26, 'Pure 45-day tf_day horizon'),

('50D', '50 days', 'D', 50, 50,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 27, 'Pure 50-day tf_day horizon'),

('56D', '56 days', 'D', 56, 56,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 28, 'Pure 56-day tf_day horizon'),

('60D', '60 days', 'D', 60, 60,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 29, 'Pure 60-day tf_day horizon'),

('63D', '63 days', 'D', 63, 63,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 30, 'Pure 63-day tf_day horizon'),

('70D', '70 days', 'D', 70, 70,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 31, 'Pure 70-day tf_day horizon'),

('84D', '84 days', 'D', 84, 84,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 32, 'Pure 84-day tf_day horizon'),

('90D', '90 days', 'D', 90, 90,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 33, 'Pure 90-day tf_day horizon'),

('100D', '100 days', 'D', 100, 100,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 34, 'Pure 100-day tf_day horizon'),

('105D', '105 days', 'D', 105, 105,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 35, 'Pure 105-day tf_day horizon'),

('140D', '140 days', 'D', 140, 140,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 36, 'Pure 140-day tf_day horizon'),

('147D', '147 days', 'D', 147, 147,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 37, 'Pure 147-day tf_day horizon'),

('150D', '150 days', 'D', 150, 150,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 38, 'Pure 150-day tf_day horizon'),

('180D', '180 days', 'D', 180, 180,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 39, 'Pure 180-day tf_day horizon'),

('200D', '200 days', 'D', 200, 200,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 40, 'Pure 200-day tf_day horizon'),

('210D', '210 days', 'D', 210, 210,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 41, 'Pure 210-day tf_day horizon'),

('250D', '250 days', 'D', 250, 250,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 42, 'Pure 250-day tf_day horizon'),

('270D', '270 days', 'D', 270, 270,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 43, 'Pure 270-day tf_day horizon'),

('280D', '280 days', 'D', 280, 280,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 44, 'Pure 280-day tf_day horizon'),

('294D', '294 days', 'D', 294, 294,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 45, 'Pure 294-day tf_day horizon'),

('300D', '300 days', 'D', 300, 300,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 46, 'Pure 300-day tf_day horizon'),

('315D', '315 days', 'D', 315, 315,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 47, 'Pure 315-day tf_day horizon'),

('350D', '350 days', 'D', 350, 350,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 48, 'Pure 350-day tf_day horizon'),

('360D', '360 days', 'D', 360, 360,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 49, 'Pure 360-day tf_day horizon'),

('400D', '400 days', 'D', 400, 400,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 50, 'Pure 400-day tf_day horizon'),

('420D', '420 days', 'D', 420, 420,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 51, 'Pure 420-day tf_day horizon'),

('441D', '441 days', 'D', 441, 441,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 52, 'Pure 441-day tf_day horizon'),

('450D', '450 days', 'D', 450, 450,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 53, 'Pure 450-day tf_day horizon'),

('500D', '500 days', 'D', 500, 500,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 54, 'Pure 500-day tf_day horizon'),

('525D', '525 days', 'D', 525, 525,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 55, 'Pure 525-day tf_day horizon'),

('560D', '560 days', 'D', 560, 560,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 56, 'Pure 560-day tf_day horizon'),

('588D', '588 days', 'D', 588, 588,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 57, 'Pure 588-day tf_day horizon'),

('600D', '600 days', 'D', 600, 600,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 58, 'Pure 600-day tf_day horizon'),

('630D', '630 days', 'D', 630, 630,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 59, 'Pure 630-day tf_day horizon'),

('700D', '700 days', 'D', 700, 700,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 60, 'Pure 700-day tf_day horizon'),

('750D', '750 days', 'D', 750, 750,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 61, 'Pure 750-day tf_day horizon'),

('800D', '800 days', 'D', 800, 800,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 62, 'Pure 800-day tf_day horizon'),

('882D', '882 days', 'D', 882, 882,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 63, 'Pure 882-day tf_day horizon'),

('900D', '900 days', 'D', 900, 900,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 64, 'Pure 900-day tf_day horizon'),

('945D', '945 days', 'D', 945, 945,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 65, 'Pure 945-day tf_day horizon'),

('1000D', '1000 days', 'D', 1000, 1000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 66, 'Pure 1000-day tf_day horizon'),

('1050D', '1050 days', 'D', 1050, 1050,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 67, 'Pure 1050-day tf_day horizon'),

('1176D', '1176 days', 'D', 1176, 1176,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 68, 'Pure 1176-day tf_day horizon'),

('1250D', '1250 days', 'D', 1250, 1250,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 69, 'Pure 1250-day tf_day horizon'),

('1260D', '1260 days', 'D', 1260, 1260,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 70, 'Pure 1260-day tf_day horizon'),

('1400D', '1400 days', 'D', 1400, 1400,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 71, 'Pure 1400-day tf_day horizon'),

('1470D', '1470 days', 'D', 1470, 1470,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 72, 'Pure 1470-day tf_day horizon'),

('1500D', '1500 days', 'D', 1500, 1500,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 73, 'Pure 1500-day tf_day horizon'),

('1800D', '1800 days', 'D', 1800, 1800,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 74, 'Pure 1800-day tf_day horizon'),

('1890D', '1890 days', 'D', 1890, 1890,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 75, 'Pure 1890-day tf_day horizon'),

('2000D', '2000 days', 'D', 2000, 2000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 76, 'Pure 2000-day tf_day horizon'),

('2100D', '2100 days', 'D', 2100, 2100,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 77, 'Pure 2100-day tf_day horizon'),

('2250D', '2250 days', 'D', 2250, 2250,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 78, 'Pure 2250-day tf_day horizon'),

('2500D', '2500 days', 'D', 2500, 2500,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 79, 'Pure 2500-day tf_day horizon'),

('2700D', '2700 days', 'D', 2700, 2700,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 80, 'Pure 2700-day tf_day horizon'),

('2800D', '2800 days', 'D', 2800, 2800,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 81, 'Pure 2800-day tf_day horizon'),

('3000D', '3000 days', 'D', 3000, 3000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 82, 'Pure 3000-day tf_day horizon'),

('3500D', '3500 days', 'D', 3500, 3500,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 83, 'Pure 3500-day tf_day horizon'),

('3600D', '3600 days', 'D', 3600, 3600,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 84, 'Pure 3600-day tf_day horizon'),

('3780D', '3780 days', 'D', 3780, 3780,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 85, 'Pure 3780-day tf_day horizon'),

('4000D', '4000 days', 'D', 4000, 4000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 86, 'Pure 4000-day tf_day horizon'),

('4200D', '4200 days', 'D', 4200, 4200,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 87, 'Pure 4200-day tf_day horizon'),

('4500D', '4500 days', 'D', 4500, 4500,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 88, 'Pure 4500-day tf_day horizon'),

('5000D', '5000 days', 'D', 5000, 5000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 89, 'Pure 5000-day tf_day horizon'),

('5600D', '5600 days', 'D', 5600, 5600,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 90, 'Pure 5600-day tf_day horizon'),

('5670D', '5670 days', 'D', 5670, 5670,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 91, 'Pure 5670-day tf_day horizon'),

('6000D', '6000 days', 'D', 6000, 6000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 92, 'Pure 6000-day tf_day horizon'),

('7000D', '7000 days', 'D', 7000, 7000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 93, 'Pure 7000-day tf_day horizon'),

('7560D', '7560 days', 'D', 7560, 7560,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 94, 'Pure 7560-day tf_day horizon'),

('8400D', '8400 days', 'D', 8400, 8400,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 95, 'Pure 8400-day tf_day horizon'),

('9000D', '9000 days', 'D', 9000, 9000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 96, 'Pure 9000-day tf_day horizon'),

('10000D', '10000 days', 'D', 10000, 10000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 97, 'Pure 10000-day tf_day horizon'),

('11200D', '11200 days', 'D', 11200, 11200,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 98, 'Pure 11200-day tf_day horizon'),

('12000D', '12000 days', 'D', 12000, 12000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 99, 'Pure 12000-day tf_day horizon'),

('13500D', '13500 days', 'D', 13500, 13500,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 100, 'Pure 13500-day tf_day horizon'),

('14000D', '14000 days', 'D', 14000, 14000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 101, 'Pure 14000-day tf_day horizon'),

('18000D', '18000 days', 'D', 18000, 18000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 102, 'Pure 18000-day tf_day horizon'),

('20000D', '20000 days', 'D', 20000, 20000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 103, 'Pure 20000-day tf_day horizon'),

('27000D', '27000 days', 'D', 27000, 27000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 104, 'Pure 27000-day tf_day horizon'),

('36000D', '36000 days', 'D', 36000, 36000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 105, 'Pure 36000-day tf_day horizon'),

('54000D', '54000 days', 'D', 54000, 54000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 106, 'Pure 54000-day tf_day horizon'),

('72000D', '72000 days', 'D', 72000, 72000,
 'tf_day', NULL, 'multiple_of_tf',
 true, false, 107, 'Pure 72000-day tf_day horizon'),

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
