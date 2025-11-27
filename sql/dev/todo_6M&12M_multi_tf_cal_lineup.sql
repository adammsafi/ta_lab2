select * 
from cmc_ema_multi_tf_cal
where id = 1 and tf like '6M' and period = 21 and roll = false
order by ts desc

---Not on the right intervals need to investigate ts should be 06-30 and 12-31