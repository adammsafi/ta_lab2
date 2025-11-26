# -*- coding: utf-8 -*-
"""
Created on Thu Nov 20 14:08:20 2025

@author: asafi
"""

"""
Created on Thu Nov 20 11:03:44 2025

@author: asafi
"""

# run_refresh_ema_daily_stats.py
"""
Helper script to run the cmc_ema_daily data-quality checks from Spyder.

Usage in Spyder (IPython console):

    %runfile C:/Users/asafi/Downloads/Data_Tools/run_refresh_ema_multi_tf_stats.py \
        --wdir C:/Users/asafi/Downloads/ta_lab2

Optionally override the DB URL:

    %runfile C:/Users/asafi/Downloads/Data_Tools/run_refresh_ema_multi_tf_stats.py \
        --wdir C:/Users/asafi/Downloads/ta_lab2 --db-url "postgresql://user:pass@host:5432/dbname"

Any --db-url argument is forwarded to ta_lab2.scripts.refresh_ema_multi_tf_stats.main().
"""

from ta_lab2.scripts.emas.stats.mulit_tf.refresh_ema_multi_tf_stats import main


if __name__ == "__main__":
    # Let refresh_ema_daily_stats.main() handle any --db-url CLI arg.
    main()