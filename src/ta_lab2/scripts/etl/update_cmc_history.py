# scripts/etl/update_cmc_history.py
from ta_lab2.io import upsert_cmc_history

if __name__ == "__main__":
    upsert_cmc_history(
        db_url=...,
        source_file="C:/Users/Adam/Downloads/cmc_XXXX.json",
    )
