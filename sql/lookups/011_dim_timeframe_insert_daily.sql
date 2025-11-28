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
 true, false, 107, 'Pure 72000-day tf_day horizon');
