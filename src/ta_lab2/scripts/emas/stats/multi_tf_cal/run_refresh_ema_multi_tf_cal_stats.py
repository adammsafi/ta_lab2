# -*- coding: utf-8 -*-
"""
Created on Thu Nov 20 15:30:00 2025

@author: asafi
"""

# run_refresh_ema_multi_tf_cal_stats.py
"""
Helper script to run the cmc_ema_multi_tf_cal data-quality checks from Spyder.

Usage in Spyder (IPython console):

    %runfile C:/Users/asafi/Downloads/Data_Tools/run_refresh_ema_multi_tf_cal_stats.py \
        --wdir C:/Users/asafi/Downloads/ta_lab2

Optionally override the DB URL:

    %runfile C:/Users/asafi/Downloads/Data_Tools/run_refresh_ema_multi_tf_cal_stats.py \
        --wdir C:/Users/asafi/Downloads/ta_lab2 --db-url "postgresql://user:pass@host:5432/dbname"

Any --db-url argument is forwarded to
ta_lab2.scripts.refresh_ema_multi_tf_cal_stats.main().
"""

from ta_lab2.scripts.emas.stats.multi_tf_cal.refresh_ema_multi_tf_cal_stats import main


if __name__ == "__main__":
    # Let refresh_ema_multi_tf_cal_stats.main() handle any --db-url CLI arg.
    main()
