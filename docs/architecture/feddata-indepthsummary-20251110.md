---
title: "feddata_inDepthSummary_20251110"
author: "Adam Safi"
created: 2025-11-10T16:45:00+00:00
modified: 2025-11-10T17:29:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Foundational\feddata_inDepthSummary_20251110.docx"
original_size_bytes: 32558
---
**FRED → Postgres on a GCP VM, local access via SSH tunnel, and
packaging plan**

1. **Goal**

   * Pull FRED data on a schedule into Postgres on a VM.
   * Query it from the laptop securely (no public DB port).
   * Optionally mirror/query from local Postgres using postgres\_fdw
     (no CSVs).
   * Package the code so it’s reusable and publishable (GitHub +
     pip).
2. **Infra: Compute + OS + packages**

   * VM: Google Compute Engine, Ubuntu (x86\_64 image).
   * Installed: python3-venv, python3-pip, postgresql,
     postgresql-contrib.
   * Python venv at ~/fred/ created and used to install:

     + requests, psycopg2-binary, python-dotenv.
3. **Database setup (on VM)**

   * **Roles & DB (idempotent)**

     + **SQL**

-- Run as postgres:

CREATE ROLE freduser LOGIN PASSWORD 'ChangeMe\_Strong1';

ALTER ROLE freduser SET search\_path TO public;

CREATE DATABASE freddata OWNER freduser;

GRANT ALL PRIVILEGES ON DATABASE freddata TO freduser;

* **Schema (tables)**

  + **SQL**

-- Connect to freddata as postgres or freduser with DDL privilege

CREATE TABLE IF NOT EXISTS releases (

release\_id bigint PRIMARY KEY,

name text NOT NULL,

press\_release boolean NOT NULL DEFAULT false,

link text NOT NULL DEFAULT '',

realtime\_start date,

realtime\_end date,

updated\_at timestamptz NOT NULL DEFAULT now()

);

CREATE TABLE IF NOT EXISTS fred\_series\_values (

series\_id text NOT NULL,

date date NOT NULL,

value double precision,

PRIMARY KEY (series\_id, date)

);

CREATE TABLE IF NOT EXISTS pull\_log (

id bigserial PRIMARY KEY,

job text NOT NULL,

ran\_at timestamptz NOT NULL DEFAULT now(),

status text NOT NULL,

rows\_upserted integer NOT NULL DEFAULT 0,

note text NOT NULL DEFAULT ''

);

4. **Runtime configuration (env)**

   * Cuts Env file: ~/.fred.env (loaded by the script /
     systemd).
   * Final values you set:

     + Ini

FRED\_API\_KEY=86adcedc8f45a6484082c9f5c9102f34

PGHOST=/var/run/postgresql # local socket or 127.0.0.1

PGPORT=5432

PGUSER=freduser

PGPASSWORD=ChangeMe\_Strong1

PGDATABASE=freddata

FRED\_SERIES=FEDFUNDS,DFEDTARU,DFEDTARL

* We re-wrote the env file once to fix a mismatch and removed the
  old one.

5. **Python script (VM): ~/fred\_pull.py**

   * Two jobs exposed by CLI argument: releases and series.
   * releases fetches the FRED catalog of releases and upserts into
     releases.
   * (Current logging shows “320 rows” each run = processed rows;
     later we can switch to “changed rows” by using IS DISTINCT FROM in the
     upsert WHERE and counting RETURNING.)
   * series pulls incremental observations for FEDFUNDS, DFEDTARU,
     DFEDTARL using max(date) per series, then upserts into
     fred\_series\_values.
   * Both jobs write a row into pull\_log with job, status,
     rows\_upserted, note.
   * Manual run examples:

     + bash

~/fred/bin/python ~/fred\_pull.py releases

~/fred/bin/python ~/fred\_pull.py series

6. **Systemd service + timers (VM)**

   * You installed templated systemd units to schedule jobs.
   * Timers:

     + fred@releases.timer: hourly (pulls the release catalog every
       hour).
     + fred@series-1400.timer: daily 14:00 ET (convert to UTC on
       server).
     + fred@series-1430.timer: daily 14:30 ET (convert to UTC).
   * We verified timers running; pull\_log shows hourly success for
     releases with ~320 processed rows.
   * Useful commands:

     + bash

systemctl list-timers --all | grep -i fred

sudo systemctl status 'fred@releases.service'

journalctl -u 'fred@releases.service' --since "today" -n 100
--no-pager

7. **Observed results (sanity checks)**

   * pull\_log shows hourly runs for releases (each ~320 processed),
     and initial series backfill (~13k inserts), followed by daily small
     increments (often 0–1).
   * Example query:

     + sql

SELECT ran\_at, job, status, rows\_upserted, note

FROM pull\_log

ORDER BY ran\_at DESC

LIMIT 100;

* SELECT COUNT(\*) FROM releases; ≈ 320.

8. **Secure local access from Windows (SSH
   tunnel)**

   * Why

     + Keep Postgres on the VM bound to localhost (not public).
     + Use SSH tunnel to forward a local port to VM’s 5432.
   * Fixes done

     + Your Windows OpenSSH google\_compute\_engine key had permissive
       ACLs. We locked it down using icacls:

       1. powershell

$dir = "$env:USERPROFILE\.ssh"

$key = "$dir\google\_compute\_engine"

$acct = "$env:USERDOMAIN\$env:USERNAME"

icacls $dir /inheritance:r | Out-Null

icacls $dir /grant:r "${acct}:(OI)(CI)(F)" | Out-Null

icacls $key /inheritance:r | Out-Null

icacls $key /grant:r "${acct}:(R)" | Out-Null

1. Ensured the public key is in ~/.ssh/authorized\_keys on the VM for
   adammsafi\_gmail\_com.

* Tunnel command (works)

  1. powershell

ssh -N -L 55432:127.0.0.1:5432 `

-i $env:USERPROFILE\.ssh\google\_compute\_engine `

adammsafi\_gmail\_com@<VM\_PUBLIC\_IP>

1. Keep that window open to keep the tunnel alive.

* Verify

  1. powershell

Get-NetTCPConnection -LocalPort 55432

psql -h 127.0.0.1 -p 55432 -U freduser -d freddata -c "select
now();"

9. **Querying from Windows**

   * Installed psql client (confirmed on PATH).
   * Connect through the tunnel:

     + Powershell

psql -h 127.0.0.1 -p 55432 -U freduser -d freddata

1. Optional: password-less via pgpass.conf

* ruby

%APPDATA%\postgresql\pgpass.conf

127.0.0.1:55432:freddata:freduser:ChangeMe\_Strong1

10. **postgres\_fdw for live access from a local Postgres (no
    CSVs)**

    * FDW is a live link (not replication). Requires the tunnel to be
      up.
    * Do this on your LOCAL Postgres as superuser (postgres):

      + sql

-- Local DB to hold FDW objects

CREATE DATABASE freddata\_local;

\c freddata\_local

-- 1) Enable FDW

CREATE EXTENSION IF NOT EXISTS postgres\_fdw;

-- 2) Define remote server via the tunnel

DROP SERVER IF EXISTS fred\_vm CASCADE;

CREATE SERVER fred\_vm

FOREIGN DATA WRAPPER postgres\_fdw

OPTIONS (host '127.0.0.1', port '55432', dbname 'freddata');

-- 3) Map local role to remote credentials

CREATE USER MAPPING FOR postgres

SERVER fred\_vm

OPTIONS (user 'freduser', password 'ChangeMe\_Strong1');

-- 4) Optional: tidy schema

CREATE SCHEMA IF NOT EXISTS remote\_fdw;

-- 5) Import desired tables (or define each explicitly)

IMPORT FOREIGN SCHEMA public

LIMIT TO (releases, fred\_series\_values, pull\_log)

FROM SERVER fred\_vm

INTO remote\_fdw;

-- 6) Query live

SELECT count(\*) FROM remote\_fdw.releases;

SELECT series\_id, max(date) FROM remote\_fdw.fred\_series\_values GROUP
BY 1;

* Offline-friendly caching (optional)

  + Use materialized views to cache FDW data when you’re online:

    1. sql

CREATE MATERIALIZED VIEW IF NOT EXISTS mv\_releases AS

SELECT \* FROM remote\_fdw.releases;

CREATE INDEX IF NOT EXISTS mv\_releases\_release\_id\_idx ON mv\_releases
(release\_id);

REFRESH MATERIALIZED VIEW CONCURRENTLY mv\_releases;

11. **Alternatives to FDW**

    * Logical replication (pub/sub):

      + Pros: Maintains a local copy; subscriber catches up after
        downtime.
      + Cons: More ops (replication slot on publisher,
        publication/subscription management).
    * CSV/pg\_dump:

      + Simple snapshots (manual or scripted); not live.
    * Building a small API:

      + Could expose endpoints to fetch deltas; unnecessary for now given
        FDW/replication.

Given your needs (“often online, sometimes offline, frequent
checks”), FDW + materialized views is a great start; upgrade to
replication later if needed.

12. **Why rows\_upserted is always 320 for releases**

    * Current code logs the number processed (len(rows)) rather than
      the number of changed rows.
    * To log “changed rows,” alter the upsert to only update when
      values differ (using IS DISTINCT FROM) and count RETURNING 1. We have a
      ready-to-paste version when you want it.
13. **Packaging the code for GitHub & reuse**

    * Option A: as a subpackage of fedtools2 (e.g.,
      fedtools2/fred/…)

      + Structure

        1. Arduino

fedtools2/

fedtools2/

fred/

\_\_init\_\_.py

config.py # env parsing

db.py # connect(), log\_run()

fred\_api.py # pull\_releases(), pull\_series()

cli.py # argparse entrypoint

tests/

pyproject.toml # add console script

.env.example

README.md

.gitignore

* pyproject.toml (snippet)

  1. toml

[project]

name = "fedtools2"

version = "0.1.0"

dependencies = ["requests>=2.32", "psycopg2-binary>=2.9"]

[project.scripts]

fedtools-fred = "fedtools2.fred.cli:main"

* CLI usage

  1. Bash

fedtools-fred init # (optional) create tables if needed

fedtools-fred releases

fedtools-fred series

* systemd ExecStart (safer than raw python)

  1. ini

ExecStart=/usr/bin/env fedtools-fred releases

* Option B: standalone package (e.g., fredsync)

  + Structure

    1. Arduino

fredsync/

src/fredsync/

\_\_init\_\_.py

config.py

db.py

fred\_api.py

cli.py

tests/

pyproject.toml

.env.example

README.md

.gitignore

* pyproject.toml (snippet)

  1. toml

[project]

name = "fredsync"

version = "0.1.0"

dependencies = ["requests>=2.32", "psycopg2-binary>=2.9"]

[project.scripts]

fredsync = "fredsync.cli:main"

* CLI usage

  1. Bash

fredsync init

fredsync releases

fredsync series "FEDFUNDS,DFEDTARU,DFEDTARL"

* Pros/Cons

  1. Subpackage: everything in one repo, easy internal reuse.
  2. Standalone: cleaner modularity/versioning; fedtools2 can depend
     on it later.
* Common packaging notes

  1. Switch releases logging from “processed rows” to “changed rows”
     (optional).
  2. Choose packaging route:

     1. subpackage in fedtools2 with fedtools-fred CLI
     2. standalone fredsync package with fredsync CLI
  3. I can generate the exact file tree and ready-to-paste code
     (pyproject, config.py, db.py, fred\_api.py, cli.py, and a couple of
     tests) for whichever path you pick.

14. **Troubleshooting cheatsheet**

    * SSH Key perms (Windows)

      + powershell

$dir="$env:USERPROFILE\.ssh"; $key="$dir\google\_compute\_engine";
$acct="$env:USERDOMAIN\$env:USERNAME"

icacls $dir /inheritance:r

icacls $dir /grant:r "${acct}:(OI)(CI)(F)"

icacls $key /inheritance:r

icacls $key /grant:r "${acct}:(R)"

* Add public key to VM

  + bash

mkdir -p ~/.ssh && chmod 700 ~/.ssh

echo 'ssh-ed25519 AAAA...your\_pub...' >>
~/.ssh/authorized\_keys

chmod 600 ~/.ssh/authorized\_keys

* Open tunnel

  + powershell

ssh -N -L 55432:127.0.0.1:5432 -i
$env:USERPROFILE\.ssh\google\_compute\_engine
adammsafi\_gmail\_com@<VM\_IP>

* Confirm tunnel

  + powershell

Get-NetTCPConnection -LocalPort 55432

psql -h 127.0.0.1 -p 55432 -U freduser -d freddata -c "select
now();"

* psql on PATH

  + powershell

where.exe psql

Get-Command psql

* Systemd

  + bash

systemctl list-timers --all | grep -i fred

sudo systemctl status 'fred@\*.service'

journalctl -u 'fred@releases.service' -n 100 --no-pager

15. **Open items / next decisions**

    * Switch releases logging from “processed rows” to “changed rows”
      (optional).
    * Choose packaging route:

      + A) subpackage in fedtools2 with fedtools-fred CLI
      + B) standalone fredsync package with fredsync CLI
    * I can generate the exact file tree and ready-to-paste code
      (pyproject, config.py, db.py, fred\_api.py, cli.py, and a couple of
      tests) for whichever path you pick.

That’s the complete context. In the new chat, tell me the packaging
route (A or B) and the repo name, and I’ll drop in the scaffolded files
you can copy/paste and push to GitHub.