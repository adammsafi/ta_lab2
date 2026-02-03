CREATE TABLE IF NOT EXISTS releases (
  release_id    bigint PRIMARY KEY,
  name          text NOT NULL,
  press_release boolean NOT NULL DEFAULT false,
  link          text NOT NULL DEFAULT '',
  realtime_start date,
  realtime_end   date,
  updated_at     timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fred_series_values (
  series_id text NOT NULL,
  date      date NOT NULL,
  value     double precision,
  PRIMARY KEY (series_id, date)
);

CREATE TABLE IF NOT EXISTS pull_log (
  id bigserial PRIMARY KEY,
  job text NOT NULL,
  ran_at timestamp with time zone NOT NULL DEFAULT now(),
  status text NOT NULL,
  rows_upserted integer NOT NULL DEFAULT 0,
  note text NOT NULL DEFAULT ''
);
