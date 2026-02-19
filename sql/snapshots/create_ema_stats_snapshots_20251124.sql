CREATE TABLE ema_multi_tf_stats_20251124_snapshot
(LIKE ema_multi_tf_stats INCLUDING ALL);

INSERT INTO ema_multi_tf_stats_20251124_snapshot
SELECT * FROM ema_multi_tf_stats;


CREATE TABLE ema_multi_tf_cal_stats_20251124_snapshot
(LIKE ema_multi_tf_cal_stats INCLUDING ALL);

INSERT INTO ema_multi_tf_cal_stats_20251124_snapshot
SELECT * FROM ema_multi_tf_cal_stats;
