# Schemas 20260114

*Converted from: Schemas_20260114.xlsx*

## cmc_price_histories7

<!-- Complex formatting may not be preserved -->

| column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- |
| id | integer | NO | nan | nan | 32.0 | 0.0 |
| name | text | NO | nan | nan | nan | nan |
| timeopen | timestamp with time zone | YES | nan | nan | nan | nan |
| timeclose | timestamp with time zone | YES | nan | nan | nan | nan |
| timehigh | timestamp with time zone | YES | nan | nan | nan | nan |
| timelow | timestamp with time zone | YES | nan | nan | nan | nan |
| timestamp | timestamp with time zone | NO | nan | nan | nan | nan |
| open | double precision | YES | nan | nan | 53.0 | nan |
| high | double precision | YES | nan | nan | 53.0 | nan |
| low | double precision | YES | nan | nan | 53.0 | nan |
| close | double precision | YES | nan | nan | 53.0 | nan |
| volume | double precision | YES | nan | nan | 53.0 | nan |
| marketcap | double precision | YES | nan | nan | 53.0 | nan |
| circulatingsupply | double precision | YES | nan | nan | 53.0 | nan |
| date | date | YES | nan | nan | nan | nan |
| source_file | text | YES | nan | nan | nan | nan |
| load_ts | timestamp with time zone | NO | now() | nan | nan | nan |

## consolidated_price_bars

<!-- Complex formatting may not be preserved -->

| order | ordinal_positions | table_name | column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | cmc_price_bars_1d | id | integer | NO | nan | nan | 32.0 | 0.0 |
| 2 | 2 | cmc_price_bars_1d | timestamp | timestamp with time zone | NO | nan | nan | nan | nan |
| 3 | 3 | cmc_price_bars_1d | tf | text | NO | nan | nan | nan | nan |
| 4 | 4 | cmc_price_bars_1d | bar_seq | bigint | NO | nan | nan | 64.0 | 0.0 |
| 5 | 5 | cmc_price_bars_1d | time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| 6 | 6 | cmc_price_bars_1d | time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| 7 | 7 | cmc_price_bars_1d | time_high | timestamp with time zone | NO | nan | nan | nan | nan |
| 8 | 8 | cmc_price_bars_1d | time_low | timestamp with time zone | NO | nan | nan | nan | nan |
| 9 | 9 | cmc_price_bars_1d | open | double precision | NO | nan | nan | 53.0 | nan |
| 10 | 10 | cmc_price_bars_1d | high | double precision | NO | nan | nan | 53.0 | nan |
| 11 | 11 | cmc_price_bars_1d | low | double precision | NO | nan | nan | 53.0 | nan |
| 12 | 12 | cmc_price_bars_1d | close | double precision | NO | nan | nan | 53.0 | nan |
| 13 | 13 | cmc_price_bars_1d | is_partial_start | boolean | NO | False | nan | nan | nan |
| 14 | 14 | cmc_price_bars_1d | is_partial_end | boolean | NO | False | nan | nan | nan |
| 15 | 15 | cmc_price_bars_1d | is_missing_days | boolean | NO | False | nan | nan | nan |
| 16 | 16 | cmc_price_bars_1d | src_name | text | YES | nan | nan | nan | nan |
| 17 | 17 | cmc_price_bars_1d | src_load_ts | timestamp with time zone | YES | nan | nan | nan | nan |
| 18 | 18 | cmc_price_bars_1d | src_file | text | YES | nan | nan | nan | nan |
| 19 | 19 | cmc_price_bars_1d | repaired_timehigh | boolean | NO | False | nan | nan | nan |
| 20 | 20 | cmc_price_bars_1d | repaired_timelow | boolean | NO | False | nan | nan | nan |
| 21 | 1 | cmc_price_bars_multi_tf | id | integer | NO | nan | nan | 32.0 | 0.0 |
| 22 | 2 | cmc_price_bars_multi_tf | tf | text | NO | nan | nan | nan | nan |
| 23 | 3 | cmc_price_bars_multi_tf | tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 24 | 4 | cmc_price_bars_multi_tf | bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| 25 | 5 | cmc_price_bars_multi_tf | time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| 26 | 6 | cmc_price_bars_multi_tf | time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| 27 | 7 | cmc_price_bars_multi_tf | time_high | timestamp with time zone | YES | nan | nan | nan | nan |
| 28 | 8 | cmc_price_bars_multi_tf | time_low | timestamp with time zone | YES | nan | nan | nan | nan |
| 29 | 9 | cmc_price_bars_multi_tf | open | double precision | NO | nan | nan | 53.0 | nan |
| 30 | 10 | cmc_price_bars_multi_tf | high | double precision | NO | nan | nan | 53.0 | nan |
| 31 | 11 | cmc_price_bars_multi_tf | low | double precision | NO | nan | nan | 53.0 | nan |
| 32 | 12 | cmc_price_bars_multi_tf | close | double precision | NO | nan | nan | 53.0 | nan |
| 33 | 13 | cmc_price_bars_multi_tf | volume | double precision | YES | nan | nan | 53.0 | nan |
| 34 | 14 | cmc_price_bars_multi_tf | market_cap | double precision | YES | nan | nan | 53.0 | nan |
| 35 | 15 | cmc_price_bars_multi_tf | ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| 36 | 16 | cmc_price_bars_multi_tf | is_partial_start | boolean | NO | False | nan | nan | nan |
| 37 | 17 | cmc_price_bars_multi_tf | is_partial_end | boolean | NO | False | nan | nan | nan |
| 38 | 18 | cmc_price_bars_multi_tf | is_missing_days | boolean | NO | False | nan | nan | nan |
| 39 | 19 | cmc_price_bars_multi_tf | count_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 40 | 20 | cmc_price_bars_multi_tf | count_days_remaining | integer | NO | nan | nan | 32.0 | 0.0 |
| 41 | 21 | cmc_price_bars_multi_tf | count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| 42 | 22 | cmc_price_bars_multi_tf | count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| 43 | 23 | cmc_price_bars_multi_tf | count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| 44 | 24 | cmc_price_bars_multi_tf | count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| 45 | 25 | cmc_price_bars_multi_tf | missing_days_where | text | YES | nan | nan | nan | nan |
| 46 | 26 | cmc_price_bars_multi_tf | timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| 47 | 27 | cmc_price_bars_multi_tf | last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| 48 | 28 | cmc_price_bars_multi_tf | pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| 49 | 29 | cmc_price_bars_multi_tf | first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 50 | 30 | cmc_price_bars_multi_tf | last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 51 | 1 | cmc_price_bars_multi_tf_cal_iso | id | integer | NO | nan | nan | 32.0 | 0.0 |
| 52 | 2 | cmc_price_bars_multi_tf_cal_iso | tf | text | NO | nan | nan | nan | nan |
| 53 | 3 | cmc_price_bars_multi_tf_cal_iso | tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 54 | 4 | cmc_price_bars_multi_tf_cal_iso | bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| 55 | 5 | cmc_price_bars_multi_tf_cal_iso | time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| 56 | 6 | cmc_price_bars_multi_tf_cal_iso | time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| 57 | 7 | cmc_price_bars_multi_tf_cal_iso | time_high | timestamp with time zone | YES | nan | nan | nan | nan |
| 58 | 8 | cmc_price_bars_multi_tf_cal_iso | time_low | timestamp with time zone | YES | nan | nan | nan | nan |
| 59 | 9 | cmc_price_bars_multi_tf_cal_iso | open | double precision | YES | nan | nan | 53.0 | nan |
| 60 | 10 | cmc_price_bars_multi_tf_cal_iso | high | double precision | YES | nan | nan | 53.0 | nan |
| 61 | 11 | cmc_price_bars_multi_tf_cal_iso | low | double precision | YES | nan | nan | 53.0 | nan |
| 62 | 12 | cmc_price_bars_multi_tf_cal_iso | close | double precision | YES | nan | nan | 53.0 | nan |
| 63 | 13 | cmc_price_bars_multi_tf_cal_iso | volume | double precision | YES | nan | nan | 53.0 | nan |
| 64 | 14 | cmc_price_bars_multi_tf_cal_iso | market_cap | double precision | YES | nan | nan | 53.0 | nan |
| 65 | 15 | cmc_price_bars_multi_tf_cal_iso | is_partial_start | boolean | NO | nan | nan | nan | nan |
| 66 | 16 | cmc_price_bars_multi_tf_cal_iso | is_partial_end | boolean | NO | nan | nan | nan | nan |
| 67 | 17 | cmc_price_bars_multi_tf_cal_iso | is_missing_days | boolean | NO | nan | nan | nan | nan |
| 68 | 18 | cmc_price_bars_multi_tf_cal_iso | count_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 69 | 19 | cmc_price_bars_multi_tf_cal_iso | count_days_remaining | integer | NO | nan | nan | 32.0 | 0.0 |
| 70 | 20 | cmc_price_bars_multi_tf_cal_iso | count_missing_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 71 | 21 | cmc_price_bars_multi_tf_cal_iso | count_missing_days_start | integer | NO | nan | nan | 32.0 | 0.0 |
| 72 | 22 | cmc_price_bars_multi_tf_cal_iso | count_missing_days_end | integer | NO | nan | nan | 32.0 | 0.0 |
| 73 | 23 | cmc_price_bars_multi_tf_cal_iso | count_missing_days_interior | integer | NO | nan | nan | 32.0 | 0.0 |
| 74 | 24 | cmc_price_bars_multi_tf_cal_iso | missing_days_where | text | YES | nan | nan | nan | nan |
| 75 | 25 | cmc_price_bars_multi_tf_cal_iso | ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| 76 | 26 | cmc_price_bars_multi_tf_cal_iso | timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| 77 | 27 | cmc_price_bars_multi_tf_cal_iso | last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| 78 | 28 | cmc_price_bars_multi_tf_cal_iso | pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| 79 | 29 | cmc_price_bars_multi_tf_cal_iso | first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 80 | 30 | cmc_price_bars_multi_tf_cal_iso | last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 81 | 1 | cmc_price_bars_multi_tf_cal_us | id | integer | NO | nan | nan | 32.0 | 0.0 |
| 82 | 2 | cmc_price_bars_multi_tf_cal_us | tf | text | NO | nan | nan | nan | nan |
| 83 | 3 | cmc_price_bars_multi_tf_cal_us | tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 84 | 4 | cmc_price_bars_multi_tf_cal_us | bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| 85 | 5 | cmc_price_bars_multi_tf_cal_us | time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| 86 | 6 | cmc_price_bars_multi_tf_cal_us | time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| 87 | 7 | cmc_price_bars_multi_tf_cal_us | time_high | timestamp with time zone | YES | nan | nan | nan | nan |
| 88 | 8 | cmc_price_bars_multi_tf_cal_us | time_low | timestamp with time zone | YES | nan | nan | nan | nan |
| 89 | 9 | cmc_price_bars_multi_tf_cal_us | open | double precision | YES | nan | nan | 53.0 | nan |
| 90 | 10 | cmc_price_bars_multi_tf_cal_us | high | double precision | YES | nan | nan | 53.0 | nan |
| 91 | 11 | cmc_price_bars_multi_tf_cal_us | low | double precision | YES | nan | nan | 53.0 | nan |
| 92 | 12 | cmc_price_bars_multi_tf_cal_us | close | double precision | YES | nan | nan | 53.0 | nan |
| 93 | 13 | cmc_price_bars_multi_tf_cal_us | volume | double precision | YES | nan | nan | 53.0 | nan |
| 94 | 14 | cmc_price_bars_multi_tf_cal_us | market_cap | double precision | YES | nan | nan | 53.0 | nan |
| 95 | 15 | cmc_price_bars_multi_tf_cal_us | timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| 96 | 16 | cmc_price_bars_multi_tf_cal_us | last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| 97 | 17 | cmc_price_bars_multi_tf_cal_us | pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| 98 | 18 | cmc_price_bars_multi_tf_cal_us | is_partial_start | boolean | YES | nan | nan | nan | nan |
| 99 | 19 | cmc_price_bars_multi_tf_cal_us | is_partial_end | boolean | YES | nan | nan | nan | nan |
| 100 | 20 | cmc_price_bars_multi_tf_cal_us | count_days_remaining | integer | YES | nan | nan | 32.0 | 0.0 |
| 101 | 21 | cmc_price_bars_multi_tf_cal_us | is_missing_days | boolean | YES | nan | nan | nan | nan |
| 102 | 22 | cmc_price_bars_multi_tf_cal_us | count_days | integer | YES | nan | nan | 32.0 | 0.0 |
| 103 | 23 | cmc_price_bars_multi_tf_cal_us | count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| 104 | 24 | cmc_price_bars_multi_tf_cal_us | count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| 105 | 25 | cmc_price_bars_multi_tf_cal_us | count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| 106 | 26 | cmc_price_bars_multi_tf_cal_us | count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| 107 | 27 | cmc_price_bars_multi_tf_cal_us | missing_days_where | text | YES | nan | nan | nan | nan |
| 108 | 28 | cmc_price_bars_multi_tf_cal_us | first_missing_day | date | YES | nan | nan | nan | nan |
| 109 | 29 | cmc_price_bars_multi_tf_cal_us | last_missing_day | date | YES | nan | nan | nan | nan |
| 110 | 30 | cmc_price_bars_multi_tf_cal_us | ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| 111 | 1 | cmc_price_bars_multi_tf_cal_anchor_iso | id | integer | NO | nan | nan | 32.0 | 0.0 |
| 112 | 2 | cmc_price_bars_multi_tf_cal_anchor_iso | tf | text | NO | nan | nan | nan | nan |
| 113 | 3 | cmc_price_bars_multi_tf_cal_anchor_iso | tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 114 | 4 | cmc_price_bars_multi_tf_cal_anchor_iso | bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| 115 | 5 | cmc_price_bars_multi_tf_cal_anchor_iso | time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| 116 | 6 | cmc_price_bars_multi_tf_cal_anchor_iso | time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| 117 | 7 | cmc_price_bars_multi_tf_cal_anchor_iso | time_high | timestamp with time zone | NO | nan | nan | nan | nan |
| 118 | 8 | cmc_price_bars_multi_tf_cal_anchor_iso | time_low | timestamp with time zone | NO | nan | nan | nan | nan |
| 119 | 9 | cmc_price_bars_multi_tf_cal_anchor_iso | open | double precision | NO | nan | nan | 53.0 | nan |
| 120 | 10 | cmc_price_bars_multi_tf_cal_anchor_iso | high | double precision | NO | nan | nan | 53.0 | nan |
| 121 | 11 | cmc_price_bars_multi_tf_cal_anchor_iso | low | double precision | NO | nan | nan | 53.0 | nan |
| 122 | 12 | cmc_price_bars_multi_tf_cal_anchor_iso | close | double precision | NO | nan | nan | 53.0 | nan |
| 123 | 13 | cmc_price_bars_multi_tf_cal_anchor_iso | volume | double precision | NO | nan | nan | 53.0 | nan |
| 124 | 14 | cmc_price_bars_multi_tf_cal_anchor_iso | market_cap | double precision | NO | nan | nan | 53.0 | nan |
| 125 | 15 | cmc_price_bars_multi_tf_cal_anchor_iso | ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| 126 | 16 | cmc_price_bars_multi_tf_cal_anchor_iso | is_partial_start | boolean | NO | False | nan | nan | nan |
| 127 | 17 | cmc_price_bars_multi_tf_cal_anchor_iso | is_partial_end | boolean | NO | False | nan | nan | nan |
| 128 | 18 | cmc_price_bars_multi_tf_cal_anchor_iso | is_missing_days | boolean | NO | False | nan | nan | nan |
| 129 | 19 | cmc_price_bars_multi_tf_cal_anchor_iso | count_days | integer | YES | nan | nan | 32.0 | 0.0 |
| 130 | 20 | cmc_price_bars_multi_tf_cal_anchor_iso | count_days_remaining | integer | YES | nan | nan | 32.0 | 0.0 |
| 131 | 21 | cmc_price_bars_multi_tf_cal_anchor_iso | count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| 132 | 22 | cmc_price_bars_multi_tf_cal_anchor_iso | count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| 133 | 23 | cmc_price_bars_multi_tf_cal_anchor_iso | count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| 134 | 24 | cmc_price_bars_multi_tf_cal_anchor_iso | count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| 135 | 25 | cmc_price_bars_multi_tf_cal_anchor_iso | missing_days_where | text | YES | nan | nan | nan | nan |
| 136 | 26 | cmc_price_bars_multi_tf_cal_anchor_iso | timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| 137 | 27 | cmc_price_bars_multi_tf_cal_anchor_iso | last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| 138 | 28 | cmc_price_bars_multi_tf_cal_anchor_iso | pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| 139 | 29 | cmc_price_bars_multi_tf_cal_anchor_iso | first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 140 | 30 | cmc_price_bars_multi_tf_cal_anchor_iso | last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 141 | 31 | cmc_price_bars_multi_tf_cal_anchor_iso | bar_anchor_offset | integer | YES | nan | nan | 32.0 | 0.0 |
| 142 | 1 | cmc_price_bars_multi_tf_cal_anchor_us | id | integer | NO | nan | nan | 32.0 | 0.0 |
| 143 | 2 | cmc_price_bars_multi_tf_cal_anchor_us | tf | text | NO | nan | nan | nan | nan |
| 144 | 3 | cmc_price_bars_multi_tf_cal_anchor_us | tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| 145 | 4 | cmc_price_bars_multi_tf_cal_anchor_us | bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| 146 | 5 | cmc_price_bars_multi_tf_cal_anchor_us | time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| 147 | 6 | cmc_price_bars_multi_tf_cal_anchor_us | time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| 148 | 7 | cmc_price_bars_multi_tf_cal_anchor_us | time_high | timestamp with time zone | NO | nan | nan | nan | nan |
| 149 | 8 | cmc_price_bars_multi_tf_cal_anchor_us | time_low | timestamp with time zone | NO | nan | nan | nan | nan |
| 150 | 9 | cmc_price_bars_multi_tf_cal_anchor_us | open | double precision | NO | nan | nan | 53.0 | nan |
| 151 | 10 | cmc_price_bars_multi_tf_cal_anchor_us | high | double precision | NO | nan | nan | 53.0 | nan |
| 152 | 11 | cmc_price_bars_multi_tf_cal_anchor_us | low | double precision | NO | nan | nan | 53.0 | nan |
| 153 | 12 | cmc_price_bars_multi_tf_cal_anchor_us | close | double precision | NO | nan | nan | 53.0 | nan |
| 154 | 13 | cmc_price_bars_multi_tf_cal_anchor_us | volume | double precision | NO | nan | nan | 53.0 | nan |
| 155 | 14 | cmc_price_bars_multi_tf_cal_anchor_us | market_cap | double precision | NO | nan | nan | 53.0 | nan |
| 156 | 15 | cmc_price_bars_multi_tf_cal_anchor_us | ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| 157 | 16 | cmc_price_bars_multi_tf_cal_anchor_us | is_partial_start | boolean | NO | False | nan | nan | nan |
| 158 | 17 | cmc_price_bars_multi_tf_cal_anchor_us | is_partial_end | boolean | NO | False | nan | nan | nan |
| 159 | 18 | cmc_price_bars_multi_tf_cal_anchor_us | is_missing_days | boolean | NO | False | nan | nan | nan |
| 160 | 19 | cmc_price_bars_multi_tf_cal_anchor_us | count_days | integer | YES | nan | nan | 32.0 | 0.0 |
| 161 | 20 | cmc_price_bars_multi_tf_cal_anchor_us | count_days_remaining | integer | YES | nan | nan | 32.0 | 0.0 |
| 162 | 21 | cmc_price_bars_multi_tf_cal_anchor_us | count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| 163 | 22 | cmc_price_bars_multi_tf_cal_anchor_us | count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| 164 | 23 | cmc_price_bars_multi_tf_cal_anchor_us | count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| 165 | 24 | cmc_price_bars_multi_tf_cal_anchor_us | count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| 166 | 25 | cmc_price_bars_multi_tf_cal_anchor_us | missing_days_where | text | YES | nan | nan | nan | nan |
| 167 | 26 | cmc_price_bars_multi_tf_cal_anchor_us | timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| 168 | 27 | cmc_price_bars_multi_tf_cal_anchor_us | last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| 169 | 28 | cmc_price_bars_multi_tf_cal_anchor_us | pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| 170 | 29 | cmc_price_bars_multi_tf_cal_anchor_us | first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 171 | 30 | cmc_price_bars_multi_tf_cal_anchor_us | last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| 172 | 31 | cmc_price_bars_multi_tf_cal_anchor_us | bar_anchor_offset | integer | YES | nan | nan | 32.0 | 0.0 |

## cmc_price_bars_1d

<!-- Complex formatting may not be preserved -->

| column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- |
| id | integer | NO | nan | nan | 32.0 | 0.0 |
| timestamp | timestamp with time zone | NO | nan | nan | nan | nan |
| tf | text | NO | nan | nan | nan | nan |
| bar_seq | bigint | NO | nan | nan | 64.0 | 0.0 |
| time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| time_high | timestamp with time zone | NO | nan | nan | nan | nan |
| time_low | timestamp with time zone | NO | nan | nan | nan | nan |
| open | double precision | NO | nan | nan | 53.0 | nan |
| high | double precision | NO | nan | nan | 53.0 | nan |
| low | double precision | NO | nan | nan | 53.0 | nan |
| close | double precision | NO | nan | nan | 53.0 | nan |
| is_partial_start | boolean | NO | 0.0 | nan | nan | nan |
| is_partial_end | boolean | NO | 0.0 | nan | nan | nan |
| is_missing_days | boolean | NO | 0.0 | nan | nan | nan |
| src_name | text | YES | nan | nan | nan | nan |
| src_load_ts | timestamp with time zone | YES | nan | nan | nan | nan |
| src_file | text | YES | nan | nan | nan | nan |
| repaired_timehigh | boolean | NO | 0.0 | nan | nan | nan |
| repaired_timelow | boolean | NO | 0.0 | nan | nan | nan |

## cmc_price_bars_multi_tf

<!-- Complex formatting may not be preserved -->

| column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- |
| id | integer | NO | nan | nan | 32.0 | 0.0 |
| tf | text | NO | nan | nan | nan | nan |
| tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| time_high | timestamp with time zone | YES | nan | nan | nan | nan |
| time_low | timestamp with time zone | YES | nan | nan | nan | nan |
| open | double precision | NO | nan | nan | 53.0 | nan |
| high | double precision | NO | nan | nan | 53.0 | nan |
| low | double precision | NO | nan | nan | 53.0 | nan |
| close | double precision | NO | nan | nan | 53.0 | nan |
| volume | double precision | YES | nan | nan | 53.0 | nan |
| market_cap | double precision | YES | nan | nan | 53.0 | nan |
| ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| is_partial_start | boolean | NO | False | nan | nan | nan |
| is_partial_end | boolean | NO | False | nan | nan | nan |
| is_missing_days | boolean | NO | False | nan | nan | nan |
| count_days | integer | NO | nan | nan | 32.0 | 0.0 |
| count_days_remaining | integer | NO | nan | nan | 32.0 | 0.0 |
| count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| missing_days_where | text | YES | nan | nan | nan | nan |
| timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |

## cmc_price_bars_multi_tf_cal_iso

<!-- Complex formatting may not be preserved -->

| column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- |
| id | integer | NO | nan | nan | 32.0 | 0.0 |
| tf | text | NO | nan | nan | nan | nan |
| tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| time_high | timestamp with time zone | YES | nan | nan | nan | nan |
| time_low | timestamp with time zone | YES | nan | nan | nan | nan |
| open | double precision | YES | nan | nan | 53.0 | nan |
| high | double precision | YES | nan | nan | 53.0 | nan |
| low | double precision | YES | nan | nan | 53.0 | nan |
| close | double precision | YES | nan | nan | 53.0 | nan |
| volume | double precision | YES | nan | nan | 53.0 | nan |
| market_cap | double precision | YES | nan | nan | 53.0 | nan |
| is_partial_start | boolean | NO | nan | nan | nan | nan |
| is_partial_end | boolean | NO | nan | nan | nan | nan |
| is_missing_days | boolean | NO | nan | nan | nan | nan |
| count_days | integer | NO | nan | nan | 32.0 | 0.0 |
| count_days_remaining | integer | NO | nan | nan | 32.0 | 0.0 |
| count_missing_days | integer | NO | nan | nan | 32.0 | 0.0 |
| count_missing_days_start | integer | NO | nan | nan | 32.0 | 0.0 |
| count_missing_days_end | integer | NO | nan | nan | 32.0 | 0.0 |
| count_missing_days_interior | integer | NO | nan | nan | 32.0 | 0.0 |
| missing_days_where | text | YES | nan | nan | nan | nan |
| ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |

## cmc_price_bars_multi_tf_cal_us

<!-- Complex formatting may not be preserved -->

| column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- |
| id | integer | NO | nan | nan | 32.0 | 0.0 |
| tf | text | NO | nan | nan | nan | nan |
| tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| time_high | timestamp with time zone | YES | nan | nan | nan | nan |
| time_low | timestamp with time zone | YES | nan | nan | nan | nan |
| open | double precision | YES | nan | nan | 53.0 | nan |
| high | double precision | YES | nan | nan | 53.0 | nan |
| low | double precision | YES | nan | nan | 53.0 | nan |
| close | double precision | YES | nan | nan | 53.0 | nan |
| volume | double precision | YES | nan | nan | 53.0 | nan |
| market_cap | double precision | YES | nan | nan | 53.0 | nan |
| timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| is_partial_start | boolean | YES | nan | nan | nan | nan |
| is_partial_end | boolean | YES | nan | nan | nan | nan |
| count_days_remaining | integer | YES | nan | nan | 32.0 | 0.0 |
| is_missing_days | boolean | YES | nan | nan | nan | nan |
| count_days | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| missing_days_where | text | YES | nan | nan | nan | nan |
| first_missing_day | date | YES | nan | nan | nan | nan |
| last_missing_day | date | YES | nan | nan | nan | nan |
| ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |

## bars_multi_tf_cal_anchor_iso

<!-- Complex formatting may not be preserved -->

| column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- |
| id | integer | NO | nan | nan | 32.0 | 0.0 |
| tf | text | NO | nan | nan | nan | nan |
| tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| time_high | timestamp with time zone | NO | nan | nan | nan | nan |
| time_low | timestamp with time zone | NO | nan | nan | nan | nan |
| open | double precision | NO | nan | nan | 53.0 | nan |
| high | double precision | NO | nan | nan | 53.0 | nan |
| low | double precision | NO | nan | nan | 53.0 | nan |
| close | double precision | NO | nan | nan | 53.0 | nan |
| volume | double precision | NO | nan | nan | 53.0 | nan |
| market_cap | double precision | NO | nan | nan | 53.0 | nan |
| ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| is_partial_start | boolean | NO | False | nan | nan | nan |
| is_partial_end | boolean | NO | False | nan | nan | nan |
| is_missing_days | boolean | NO | False | nan | nan | nan |
| count_days | integer | YES | nan | nan | 32.0 | 0.0 |
| count_days_remaining | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| missing_days_where | text | YES | nan | nan | nan | nan |
| timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| bar_anchor_offset | integer | YES | nan | nan | 32.0 | 0.0 |

## bars_multi_tf_cal_anchor_us

<!-- Complex formatting may not be preserved -->

| column_name | data_type | is_nullable | column_default | character_maximum_length | numeric_precision | numeric_scale |
| --- | --- | --- | --- | --- | --- | --- |
| id | integer | NO | nan | nan | 32.0 | 0.0 |
| tf | text | NO | nan | nan | nan | nan |
| tf_days | integer | NO | nan | nan | 32.0 | 0.0 |
| bar_seq | integer | NO | nan | nan | 32.0 | 0.0 |
| time_open | timestamp with time zone | NO | nan | nan | nan | nan |
| time_close | timestamp with time zone | NO | nan | nan | nan | nan |
| time_high | timestamp with time zone | NO | nan | nan | nan | nan |
| time_low | timestamp with time zone | NO | nan | nan | nan | nan |
| open | double precision | NO | nan | nan | 53.0 | nan |
| high | double precision | NO | nan | nan | 53.0 | nan |
| low | double precision | NO | nan | nan | 53.0 | nan |
| close | double precision | NO | nan | nan | 53.0 | nan |
| volume | double precision | NO | nan | nan | 53.0 | nan |
| market_cap | double precision | NO | nan | nan | 53.0 | nan |
| ingested_at | timestamp with time zone | NO | now() | nan | nan | nan |
| is_partial_start | boolean | NO | False | nan | nan | nan |
| is_partial_end | boolean | NO | False | nan | nan | nan |
| is_missing_days | boolean | NO | False | nan | nan | nan |
| count_days | integer | YES | nan | nan | 32.0 | 0.0 |
| count_days_remaining | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_start | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_end | integer | YES | nan | nan | 32.0 | 0.0 |
| count_missing_days_interior | integer | YES | nan | nan | 32.0 | 0.0 |
| missing_days_where | text | YES | nan | nan | nan | nan |
| timestamp | timestamp with time zone | YES | nan | nan | nan | nan |
| last_ts_half_open | timestamp with time zone | YES | nan | nan | nan | nan |
| pos_in_bar | integer | YES | nan | nan | 32.0 | 0.0 |
| first_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| last_missing_day | timestamp with time zone | YES | nan | nan | nan | nan |
| bar_anchor_offset | integer | YES | nan | nan | 32.0 | 0.0 |
