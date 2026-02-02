# Db Schemas Keys

*Converted from: db_schemas_keys.xlsx*

## Overview

<!-- Complex formatting may not be preserved -->

| name | type | source | majorCategory | minorCategory | type.1 | sourceURL1 | sourceURL2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cmc_da_ids | table | external | reference | asset | API | https://pro-api.coinmarketcap.com/v1/cryptocurrency/map?CMC_PRO_API_KEY=UNIFIED-CRYPTOASSET-INDEX&listing_status=active | nan |
| cmc_da_info | table | external | reference | asset | API | https://pro-api.coinmarketcap.com/v1/cryptocurrency/info?CMC_PRO_API_KEY=UNIFIED-CRYPTOASSET-INDEX&id=1 | nan |
| cmc_exchange_info | table | external | reference | exchange | API | https://pro-api.coinmarketcap.com/v1/exchange/info?CMC_PRO_API_KEY=UNIFIED-CRYPTOASSET-INDEX&id=16 | nan |
| cmc_exchange_map | table | external | reference | exchange | API | https://pro-api.coinmarketcap.com/v1/exchange/map?CMC_PRO_API_KEY=UNIFIED-CRYPTOASSET-INDEX&listing_status=active | nan |
| cmc_price_histories7 | table | nan | price data | da | csv | C:\Users\asafi\Downloads\cmc_price_histories\Backfill | C:\Users\asafi\Downloads\cmc_price_histories\Updates |
| cmc_ema_daily | table | derived | features | ema | .py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\features\ema.py | nan |
| cmc_ema_multi_tf | table | derived | features | ema | .py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\features\m_tf\ema_multi_timeframe.py | nan |
| cmc_ema_multi_tf_cal | table | nan | features | ema | nan | nan | nan |
| cmc_alpha_lut | table | internal | features | ema | .sql | C:\Users\asafi\Downloads\ta_lab2\sql\001_ema_alpha_lookup.sql | nan |
| all_emas | view | nan | features | ema | .sql | C:\Users\asafi\Downloads\ta_lab2\sql\create_alter_all_emas.sql | nan |
| cmc_price_with_emas | view | nan | features | ema | .sql | C:\Users\asafi\Downloads\ta_lab2\sql\create_alter_cmc_price_with_emas.sql | nan |
| cmc_price_with_emas_d1d2 | view | nan | features | ema | .sql | C:\Users\asafi\Downloads\ta_lab2\sql\create_alter_cmc_price_with_emas_d1d2.sql | nan |
| price_histories7_stats | table | nan | price data | da_testing | .py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\run_refresh_price_histories7_stats.py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\refresh_price_histories7_stats.py |
| ema_daily_stats | table | nan | features | ema_testing | .py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\refresh_ema_daily_stats.py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\refresh_ema_daily_stats.py |
| ema_multi_tf_stats | table | nan | features | ema_testing | .py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\run_refresh_ema_multi_tf.py | C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\refresh_ema_multi_tf_stats.py |
| cmc_ema_multi_tf_cal_stats | table | nan | features | ema_testing | nan | nan | nan |
| cmc_price_ranges | table | nan | price data | da_testing | .sql | C:\Users\asafi\Downloads\ta_lab2\sql\cmc_price_ranges.sql | nan |
| _stg_cmc_price_histories7 | table | nan | price data | da_helper | nan | nan | nan |

## cmc_da_ids

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |
| --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key |
| id | bigint | NO | nan | YES |
| rank | bigint | YES | nan | NO |
| name | text | YES | nan | NO |
| symbol | text | YES | nan | NO |
| slug | text | YES | nan | NO |
| is_active | bigint | YES | nan | NO |
| status | bigint | YES | nan | NO |
| first_historical_data | text | YES | nan | NO |
| last_historical_data | text | YES | nan | NO |
| platform | double precision | YES | nan | NO |
| platform.id | double precision | YES | nan | NO |
| platform.name | text | YES | nan | NO |
| platform.symbol | text | YES | nan | NO |
| platform.slug | text | YES | nan | NO |
| platform.token_address | text | YES | nan | NO |
| ingested_at | timestamp with time zone | YES | nan | NO |

## cmc_da_info

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |
| --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key |
| id | bigint | YES | nan | NO |
| name | text | YES | nan | NO |
| symbol | text | YES | nan | NO |
| category | text | YES | nan | NO |
| description | text | YES | nan | NO |
| slug | text | YES | nan | NO |
| logo | text | YES | nan | NO |
| subreddit | text | YES | nan | NO |
| notice | text | YES | nan | NO |
| tags | text | YES | nan | NO |
| tag-names | text | YES | nan | NO |
| tag-groups | text | YES | nan | NO |
| platform | text | YES | nan | NO |
| date_added | text | YES | nan | NO |
| twitter_username | text | YES | nan | NO |
| is_hidden | bigint | YES | nan | NO |
| date_launched | text | YES | nan | NO |
| contract_address | text | YES | nan | NO |
| self_reported_circulating_supply | text | YES | nan | NO |
| self_reported_tags | text | YES | nan | NO |
| self_reported_market_cap | text | YES | nan | NO |
| infinite_supply | boolean | YES | nan | NO |
| __id | text | YES | nan | NO |
| urls.website | text | YES | nan | NO |
| urls.twitter | text | YES | nan | NO |
| urls.message_board | text | YES | nan | NO |
| urls.chat | text | YES | nan | NO |
| urls.facebook | text | YES | nan | NO |
| urls.explorer | text | YES | nan | NO |
| urls.reddit | text | YES | nan | NO |
| urls.technical_doc | text | YES | nan | NO |
| urls.source_code | text | YES | nan | NO |
| urls.announcement | text | YES | nan | NO |
| ingested_at | timestamp with time zone | YES | nan | NO |
| row_hash | text | NO | nan | YES |
| platform.id | text | YES | nan | NO |
| platform.name | text | YES | nan | NO |
| platform.slug | text | YES | nan | NO |
| platform.symbol | text | YES | nan | NO |
| platform.token_address | text | YES | nan | NO |

## cmc_exchange_info

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |
| --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key |
| id | bigint | NO | nan | YES |
| name | text | YES | nan | NO |
| slug | text | YES | nan | NO |
| description | text | YES | nan | NO |
| notice | text | YES | nan | NO |
| logo | text | YES | nan | NO |
| countries | text | YES | nan | NO |
| fiats | text | YES | nan | NO |
| tags | text | YES | nan | NO |
| type | text | YES | nan | NO |
| porStatus | bigint | YES | nan | NO |
| porAuditStatus | bigint | YES | nan | NO |
| walletSourceStatus | bigint | YES | nan | NO |
| porSwitch | text | YES | nan | NO |
| alertType | bigint | YES | nan | NO |
| alertLink | text | YES | nan | NO |
| date_launched | text | YES | nan | NO |
| is_hidden | bigint | YES | nan | NO |
| is_redistributable | bigint | YES | nan | NO |
| maker_fee | double precision | YES | nan | NO |
| taker_fee | double precision | YES | nan | NO |
| on_ramp_direct_deposit | text | YES | nan | NO |
| on_ramp_card_visa_mastercard | text | YES | nan | NO |
| on_ramp_google_apple_pay | text | YES | nan | NO |
| on_ramp_third_party | text | YES | nan | NO |
| on_ramp_p2p | text | YES | nan | NO |
| off_ramp_direct_withdrawal | text | YES | nan | NO |
| off_ramp_p2p | text | YES | nan | NO |
| spot_volume_usd | double precision | YES | nan | NO |
| spot_volume_last_updated | text | YES | nan | NO |
| weekly_visits | bigint | YES | nan | NO |
| __id | text | YES | nan | NO |
| urls.chat | text | YES | nan | NO |
| urls.website | text | YES | nan | NO |
| urls.actual | text | YES | nan | NO |
| urls.blog | text | YES | nan | NO |
| urls.fee | text | YES | nan | NO |
| urls.register | text | YES | nan | NO |
| urls.twitter | text | YES | nan | NO |
| ingested_at | timestamp with time zone | YES | nan | NO |

## cmc_exchange_map

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |
| --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key |
| id | bigint | NO | nan | YES |
| name | text | YES | nan | NO |
| slug | text | YES | nan | NO |
| is_active | bigint | YES | nan | NO |
| is_listed | bigint | YES | nan | NO |
| is_redistributable | bigint | YES | nan | NO |
| first_historical_data | text | YES | nan | NO |
| last_historical_data | text | YES | nan | NO |
| ingested_at | timestamp with time zone | YES | nan | NO |

## cmc_price_histories7

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |
| --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key |
| id | integer | NO | nan | YES |
| name | text | NO | nan | NO |
| timeopen | timestamp with time zone | YES | nan | NO |
| timeclose | timestamp with time zone | YES | nan | NO |
| timehigh | timestamp with time zone | YES | nan | NO |
| timelow | timestamp with time zone | YES | nan | NO |
| timestamp | timestamp with time zone | NO | nan | YES |
| open | double precision | YES | nan | NO |
| high | double precision | YES | nan | NO |
| low | double precision | YES | nan | NO |
| close | double precision | YES | nan | NO |
| volume | double precision | YES | nan | NO |
| marketcap | double precision | YES | nan | NO |
| circulatingsupply | double precision | YES | nan | NO |
| date | date | YES | nan | NO |
| source_file | text | YES | nan | NO |
| load_ts | timestamp with time zone | NO | now() | NO |

## cmc_ema_daily

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |
| --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key |
| id | integer | NO | nan | YES |
| ts | timestamp with time zone | NO | nan | YES |
| period | integer | NO | nan | YES |
| ema | double precision | NO | nan | NO |
| ingested_at | timestamp with time zone | NO | now() | NO |
| d1 | double precision | YES | nan | NO |
| d2 | double precision | YES | nan | NO |
| tf_days | integer | YES | nan | NO |
| roll | boolean | YES | nan | NO |
| d1_roll | double precision | YES | nan | NO |
| d2_roll | double precision | YES | nan | NO |
| tf | text | NO | '1D'::text | NO |

## cmc_ema_multi_tf

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |  |
| --- | --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key | description |
| id | integer | NO | nan | YES | the da_id maps directly to cmc_da_ids.id |
| ts | timestamp with time zone | NO | nan | YES | ts is the timestamp, which equals timeclose |
| tf | text | NO | nan | YES | tf is timeframe, the number of periods the ema is using to calculate the ema, generally 10, 21, 50, 100, 200 |
| period | integer | NO | nan | YES | the period is the bar size used in the ema calulation and is based off of either a number or day called tf_days or the calendar |
| ema | double precision | NO | nan | NO | nan |
| ingested_at | timestamp with time zone | NO | now() | NO | nan |
| d1 | double precision | YES | nan | NO | nan |
| d2 | double precision | YES | nan | NO | nan |
| tf_days | integer | YES | nan | NO | nan |
| roll | boolean | YES | nan | NO | nan |
| d1_roll | double precision | YES | nan | NO | nan |
| d2_roll | double precision | YES | nan | NO | nan |

## ema_alpha_lut

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |  |
| --- | --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default | is_primary_key |
| tf | text | NO | nan | YES |
| tf_days | integer | NO | nan | NO |
| period | integer | NO | nan | YES |
| alpha_bar | double precision | NO | nan | NO |
| effective_days | integer | NO | nan | NO |
| alpha_daily_eq | double precision | YES | nan | NO |

## all_emas

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |
| --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default |
| id | integer | YES | nan |
| ts | timestamp with time zone | YES | nan |
| tf | text | YES | nan |
| tf_days | integer | YES | nan |
| period | integer | YES | nan |
| ema | double precision | YES | nan |
| d1 | double precision | YES | nan |
| d2 | double precision | YES | nan |
| d1_close | double precision | YES | nan |
| d2_close | double precision | YES | nan |
| roll | boolean | YES | nan |

## cmc_price_with_emas

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |
| --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default |
| id | integer | YES | nan |
| bar_ts | timestamp with time zone | YES | nan |
| close | double precision | YES | nan |
| volume | double precision | YES | nan |
| marketcap | double precision | YES | nan |
| tf | text | YES | nan |
| tf_days | integer | YES | nan |
| ema_ts | timestamp with time zone | YES | nan |
| period | integer | YES | nan |
| ema | double precision | YES | nan |

## cmc_price_with_emas_d1d2

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |
| --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default |
| id | integer | YES | nan |
| bar_ts | timestamp with time zone | YES | nan |
| close | double precision | YES | nan |
| volume | double precision | YES | nan |
| marketcap | double precision | YES | nan |
| tf | text | YES | nan |
| tf_days | integer | YES | nan |
| ema_ts | timestamp with time zone | YES | nan |
| period | integer | YES | nan |
| ema | double precision | YES | nan |
| d1 | double precision | YES | nan |
| d2 | double precision | YES | nan |
| d1_close | double precision | YES | nan |
| d2_close | double precision | YES | nan |
| roll | boolean | YES | nan |

## price_histories7_stats

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |
| --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default |
| stat_id | bigint | NO | nextval('price_histories7_stats_stat_id_seq'::regclass) |
| table_name | text | NO | nan |
| test_name | text | NO | nan |
| asset_id | integer | YES | nan |
| tf | text | YES | nan |
| period | integer | YES | nan |
| status | text | NO | nan |
| actual | numeric | YES | nan |
| expected | numeric | YES | nan |
| extra | jsonb | YES | nan |
| checked_at | timestamp with time zone | NO | now() |

## ema_daily_stats

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |
| --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default |
| stat_id | bigint | NO | nextval('cmc_data_stats_stat_id_seq'::regclass) |
| table_name | text | NO | nan |
| test_name | text | NO | nan |
| asset_id | integer | YES | nan |
| tf | text | YES | nan |
| period | integer | YES | nan |
| status | text | NO | nan |
| actual | numeric | YES | nan |
| expected | numeric | YES | nan |
| extra | jsonb | YES | nan |
| checked_at | timestamp with time zone | NO | now() |

## ema_multi_tf_stats

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |
| --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default |
| stat_id | bigint | NO | nextval('ema_multi_tf_stats_stat_id_seq'::regclass) |
| table_name | text | NO | nan |
| test_name | text | NO | nan |
| asset_id | integer | YES | nan |
| tf | text | YES | nan |
| period | integer | YES | nan |
| status | text | NO | nan |
| actual | numeric | YES | nan |
| expected | numeric | YES | nan |
| extra | jsonb | YES | nan |
| checked_at | timestamp with time zone | NO | now() |

## cmc_price_ranges

<!-- Complex formatting may not be preserved -->

| Overview |  |  |  |
| --- | --- | --- | --- |
| column_name | data_type | is_nullable | column_default |
| asset_id | integer | NO | nan |
| low_min | numeric | YES | nan |
| low_max | numeric | YES | nan |
| high_min | numeric | YES | nan |
| high_max | numeric | YES | nan |
| note | text | YES | nan |
