CREATE TABLE cmc_ema_multi_tf_20251124_snapshot
(LIKE cmc_ema_multi_tf INCLUDING ALL);

INSERT INTO cmc_ema_multi_tf_20251124_snapshot
SELECT * FROM cmc_ema_multi_tf;

CREATE TABLE cmc_ema_multi_tf_cal_20251124_snapshot
(LIKE cmc_ema_multi_tf_cal INCLUDING ALL);

INSERT INTO cmc_ema_multi_tf_cal_20251124_snapshot
SELECT * FROM cmc_ema_multi_tf_cal;
