CREATE TABLE ema_multi_tf_20251124_snapshot
(LIKE ema_multi_tf INCLUDING ALL);

INSERT INTO ema_multi_tf_20251124_snapshot
SELECT * FROM ema_multi_tf;

CREATE TABLE ema_multi_tf_cal_20251124_snapshot
(LIKE ema_multi_tf_cal INCLUDING ALL);

INSERT INTO ema_multi_tf_cal_20251124_snapshot
SELECT * FROM ema_multi_tf_cal;
