# Phase 114: Hosted Dashboard - Research

**Researched:** 2026-04-01
**Domain:** Streamlit deployment, nginx reverse proxy, Oracle Cloud VM, SSH tunnels, data sync
**Confidence:** HIGH (codebase verified directly; infrastructure patterns verified with official docs)

---

## Summary

Phase 114 hosts the existing Streamlit dashboard on the Oracle Singapore VM (161.118.209.59) behind nginx + Let's Encrypt SSL. The dashboard is a 19-page multi-page Streamlit app already coded; the work is purely deployment: systemd service, nginx config, SSL, firewall, data sync, and mobile CSS tweaks.

The primary technical risk is the Oracle Cloud dual-layer firewall (Security List + iptables must both be opened). Second risk is nginx + Streamlit WebSocket: the `/_stcore/stream` WebSocket endpoint must be explicitly proxied with HTTP upgrade headers or the dashboard hangs at "Please wait...".

For data sync, the existing `sync_hl_from_vm.py` pattern (SSH + `psql COPY`) is the correct template to invert — `sync_dashboard_to_vm.py` will `COPY ... TO STDOUT` from local and pipe into VM via SSH. Most tables use incremental watermark; a few small dimension/config tables use full replace.

**Primary recommendation:** Follow the exact SSH+COPY pattern from `sync_hl_from_vm.py` (inverted direction), use nginx basic auth with htpasswd for access control, and use a dedicated WebSocket location block for `/_stcore/stream`.

---

## Standard Stack

### Core

| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| nginx | latest stable (1.24+) | Reverse proxy, SSL termination, basic auth | De-facto for Streamlit on Ubuntu |
| certbot + python3-certbot-nginx | latest | Let's Encrypt SSL with auto-renewal | Official ACME client; handles nginx config rewrite |
| apache2-utils | any | `htpasswd` CLI to create/manage `.htpasswd` | Ships on Ubuntu, standard for nginx basic auth |
| systemd | (Ubuntu built-in) | Streamlit service management (auto-start, restart) | Standard Ubuntu service management |
| autossh | 2.2+ | Persistent reverse SSH tunnel with reconnect | More reliable than bare ssh for long-lived tunnels |

### Supporting

| Component | Version | Purpose | When to Use |
|-----------|---------|---------|-------------|
| iptables-persistent / netfilter-persistent | Ubuntu package | Persist iptables rules across reboots | Required: Oracle VM iptables rules are not saved by default |
| postgresql-client | 14+ | `psql` on VM for COPY operations | Already installed (existing sync scripts use it) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| nginx basic auth | Streamlit's own auth / OAuth | htpasswd is zero-dependency, works with WebSockets; OAuth is heavy for a private dashboard |
| certbot snap | certbot apt | Snap auto-renews via timer; apt requires manual timer setup. Use whichever Ubuntu recommends at install time |
| autossh tunnel | bare ssh tunnel (systemd restart) | Both work; autossh provides deeper monitoring; bare ssh with `Restart=always` is simpler and sufficient |

### Installation (on VM)

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx apache2-utils autossh iptables-persistent
```

---

## Architecture Patterns

### Recommended Project Structure

```
On VM (ubuntu@161.118.209.59):
/home/ubuntu/ta_lab2/                    # Codebase checkout / rsync copy
  src/ta_lab2/dashboard/app.py           # Streamlit entry point
  .streamlit/config.toml                  # Streamlit config (enableCORS=false, XSRF=false)
  db_config.env                           # VM-local DB URL (points to 127.0.0.1)

/etc/systemd/system/
  ta-dashboard.service                    # Streamlit systemd unit
  ta-reverse-tunnel.service              # Reverse SSH tunnel unit (optional)

/etc/nginx/sites-available/
  ta-dashboard                            # nginx vhost config

/etc/apache2/
  .htpasswd                               # Basic auth user file

/etc/letsencrypt/                          # certbot manages this
```

---

### Pattern 1: Streamlit systemd Service

**What:** Run Streamlit as a systemd service bound to 127.0.0.1 (never expose port 8501 directly).
**When to use:** Always for production. nginx proxies; Streamlit listens locally only.

```ini
# /etc/systemd/system/ta-dashboard.service
[Unit]
Description=ta_lab2 Streamlit Dashboard
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/ta_lab2
EnvironmentFile=/home/ubuntu/ta_lab2/db_config.env
ExecStart=/home/ubuntu/ta_lab2/.venv/bin/streamlit run \
    src/ta_lab2/dashboard/app.py \
    --server.address 127.0.0.1 \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false
Restart=always
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Critical:** `--server.address 127.0.0.1` — never `0.0.0.0`. nginx is the public-facing entry point.

---

### Pattern 2: nginx Reverse Proxy with WebSocket + Basic Auth + SSL

**What:** nginx terminates SSL, enforces basic auth, and proxies to Streamlit with correct WebSocket headers.
**Key pitfall:** Streamlit's WebSocket endpoint is `/_stcore/stream`. Must be in the proxy location block with HTTP/1.1 upgrade headers or the app hangs at "Please wait...".

```nginx
# /etc/nginx/sites-available/ta-dashboard
server {
    listen 80;
    server_name dash.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name dash.yourdomain.com;

    # SSL (certbot populates these)
    ssl_certificate     /etc/letsencrypt/live/dash.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dash.yourdomain.com/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Basic auth
    auth_basic           "ta_lab2 Dashboard";
    auth_basic_user_file /etc/apache2/.htpasswd;

    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        # WebSocket upgrade — required for /_stcore/stream
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";
        proxy_read_timeout 86400;
        proxy_buffering    off;
    }
}
```

**Note:** Applying WebSocket headers at the top-level `location /` block (not a separate `/_stcore/stream` block) is the most reliable approach. Streamlit uses `/_stcore/stream` in v1.12+ (changed from `/stream`).

---

### Pattern 3: Streamlit config.toml for Proxy Compatibility

**What:** Two settings required in `.streamlit/config.toml` when running behind a reverse proxy.

```toml
# On VM: /home/ubuntu/ta_lab2/.streamlit/config.toml
[server]
enableCORS = false
enableXsrfProtection = false
fileWatcherType = "none"
headless = true

[theme]
base = "dark"
```

`enableCORS = false` and `enableXsrfProtection = false` are required — otherwise Streamlit rejects proxied requests. `fileWatcherType = "none"` prevents inotify resource waste on server.

---

### Pattern 4: Oracle Cloud Dual-Layer Firewall

**What:** Oracle Cloud Ubuntu VMs have TWO firewalls that must BOTH allow traffic. Missing either causes silent connection refusal.
**When to use:** Any port opened for the first time.

**Layer 1 — OCI Security List (VCN-level):**
In the Oracle Cloud Console: Networking → Virtual Cloud Networks → your VCN → Security Lists → Default Security List → Add Ingress Rules:
- Source CIDR: `0.0.0.0/0`, Protocol: TCP, Port: 80
- Source CIDR: `0.0.0.0/0`, Protocol: TCP, Port: 443

**Layer 2 — iptables (VM-level):**
```bash
# Insert BEFORE the REJECT rule (position matters!)
sudo iptables -I INPUT 6 -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT

# Persist across reboots
sudo netfilter-persistent save
sudo netfilter-persistent reload
```

**Verify both:**
```bash
sudo iptables -L INPUT -n --line-numbers    # should show ACCEPT for 80/443
# From external machine:
curl -I http://161.118.209.59/               # expect nginx response, not timeout
```

---

### Pattern 5: Let's Encrypt SSL with certbot

**What:** certbot auto-configures nginx and renews every ~60 days via systemd timer.

```bash
# Install and obtain certificate
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d dash.yourdomain.com

# Verify auto-renewal timer (installed by certbot)
sudo systemctl status certbot.timer
sudo certbot renew --dry-run   # test renewal
```

Certbot modifies the nginx config directly (adds `ssl_certificate` lines). Renewal reloads nginx automatically.

---

### Pattern 6: sync_dashboard_to_vm.py — Push FROM Local TO VM

**What:** Reverse of existing sync scripts. Instead of pulling CSV from VM, push CSV to VM.
**Template:** `sync_hl_from_vm.py` but direction inverted.

The push pattern uses SSH + `psql COPY FROM STDIN`:

```python
# Source: adapted from sync_hl_from_vm.py (inverted direction)

def _local_copy_to_csv(engine, sql: str) -> str:
    """Export local table rows to CSV string via SQLAlchemy COPY TO STDOUT."""
    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        buf = io.StringIO()
        cur.copy_expert(f"COPY ({sql}) TO STDOUT WITH CSV HEADER", buf)
        return buf.getvalue()
    finally:
        raw_conn.close()


def _vm_copy_from_stdin(csv_data: str, vm_table: str, conflict_cols: list[str],
                         update_cols: list[str]) -> int:
    """Push CSV data to VM table via SSH + psql COPY FROM STDIN."""
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    conflict_str = ", ".join(conflict_cols)
    
    # Pipe CSV directly to psql on VM
    cmd = [
        "ssh", "-i", VM_SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        f"{VM_USER}@{VM_HOST}",
        f"""PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} -c "
            CREATE TEMP TABLE _staging (LIKE {vm_table} INCLUDING DEFAULTS) ON COMMIT DROP;
            COPY _staging FROM STDIN WITH CSV HEADER;
            INSERT INTO {vm_table} SELECT * FROM _staging
                ON CONFLICT ({conflict_str}) DO UPDATE SET {set_clause};
        " """
    ]
    result = subprocess.run(cmd, input=csv_data, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"VM push failed: {result.stderr}")
    return len(csv_data.split("\n")) - 1  # subtract header
```

**Sync strategy per table type:**

| Table type | Strategy | Rationale |
|-----------|---------|-----------|
| Large time-series (regimes, features, strategy_bakeoff_results, ic_results) | Incremental watermark on `ts` or `computed_at` | Can be millions of rows; incremental is essential |
| Execution tables (fills, positions, orders, drift_metrics, executor_run_log) | Incremental watermark on `filled_at`/`metric_date`/`started_at` | Medium size; fresh data matters most |
| Small config/dim tables (dim_assets, dim_executor_config, dim_risk_limits, dim_risk_state) | Full replace | <1K rows; full replace is simpler and correct |
| hyperliquid.* schema | Skip — already on VM (VM is source) | VM already has this data from collection cron |
| fred.* schema | Skip for MVP | FRED macro not critical for ops monitoring |

---

### Pattern 7: Reverse SSH Tunnel for On-Demand Refresh

**What:** The "Refresh Data" button in the dashboard needs to trigger `sync_dashboard_to_vm.py` on the local PC. This requires a reverse SSH tunnel from VM to local.

**Architecture:**
```
Local PC (running sync script) <── reverse tunnel ── Oracle VM (running dashboard)
Port 2222 on VM forwards to port 22 on local PC
```

**VM-side: Persistent reverse tunnel service (runs on local PC):**
```ini
# /etc/systemd/system/ta-reverse-tunnel.service  (on LOCAL PC)
[Unit]
Description=Reverse SSH tunnel to Oracle VM
After=network-online.target

[Service]
User=asafi
ExecStart=/usr/bin/ssh \
    -NTg \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=accept-new \
    -R 2222:localhost:22 \
    -i ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key \
    ubuntu@161.118.209.59
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

**Dashboard "Refresh Data" button calls on VM:**
```python
# In dashboard sidebar (replacing the current cache-clear Refresh button)
if st.button("Sync & Refresh", type="primary"):
    # Trigger sync on local PC via reverse tunnel
    result = subprocess.run([
        "ssh", "-p", "2222", "-o", "StrictHostKeyChecking=accept-new",
        "asafi@127.0.0.1",
        "cd ~/Downloads/ta_lab2 && python -m ta_lab2.scripts.etl.sync_dashboard_to_vm --reverse"
    ], capture_output=True, text=True, timeout=120)
    if result.returncode == 0:
        st.cache_data.clear()
        st.rerun()
    else:
        st.error(f"Sync failed: {result.stderr[:200]}")
```

**Alternative (simpler, no tunnel needed):** The dashboard sidebar's existing "Refresh Now" button clears cache and reruns. A `sync_dashboard_to_vm.py --cron` can run daily via cron on local PC (after the daily refresh pipeline). The on-demand button via reverse tunnel is an enhancement, not MVP.

---

### Pattern 8: Mobile CSS Tweaks

**What:** Streamlit's `st.columns()` does not stack on mobile by default. CSS media queries injected via `st.markdown(unsafe_allow_html=True)` are the correct approach.

```python
# Inject in app.py after set_page_config (affects all pages)
st.markdown("""
<style>
/* Stack columns on mobile */
@media (max-width: 768px) {
    [data-testid="column"] {
        width: 100% !important;
        flex: none !important;
    }
    /* Reduce chart font sizes */
    .js-plotly-plot .plotly text {
        font-size: 10px !important;
    }
    /* Full-width dataframes */
    [data-testid="stDataFrame"] {
        width: 100% !important;
    }
}
/* Ensure sidebar collapses on mobile by default */
</style>
""", unsafe_allow_html=True)
```

Streamlit already collapses the sidebar automatically on narrow viewports (fixed in 2025 release). The main need is column stacking.

---

### Anti-Patterns to Avoid

- **Exposing Streamlit directly on port 8501:** Never bind `--server.address 0.0.0.0`. All traffic must go through nginx.
- **Skipping `enableCORS = false` in config.toml:** Streamlit rejects requests from proxied origins without this.
- **Separate location block for `/_stcore/stream` without WebSocket headers:** Causes "Please wait..." hang. Put WebSocket headers in the root `location /` block for Streamlit.
- **Not inserting iptables rules before the REJECT rule:** Oracle Ubuntu VMs have a default `REJECT all` rule. Rules added at the end are ignored.
- **Running `iptables` changes without `netfilter-persistent save`:** Rules survive until reboot only.
- **Using `proxy_buffering on` for Streamlit:** Causes slow response; set `proxy_buffering off`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSL certificate management | Custom ACME client | certbot --nginx | Handles nginx config, renewal, dhparam, all edge cases |
| Password hashing | SHA/MD5 by hand | htpasswd -B (bcrypt) | Use `-B` flag for bcrypt hashing |
| WebSocket proxy | Custom TCP forwarder | nginx with upgrade headers | nginx handles HTTP→WebSocket upgrade correctly |
| Process supervision | Custom watchdog | systemd Restart=always | Handles OOM, crashes, reboots |
| SSH tunnel keepalive | Custom ping loop | ServerAliveInterval in ssh / autossh | Battle-tested reconnect logic |

**Key insight:** Every component (nginx, certbot, systemd, htpasswd) has 5+ years of production use. The only custom code is `sync_dashboard_to_vm.py` and the CSS inject.

---

## Common Pitfalls

### Pitfall 1: Oracle Cloud Dual Firewall — Silent Connection Drop
**What goes wrong:** Port 80/443 opened in OCI Security List but not iptables (or vice versa). `curl` hangs with no response, not a connection refused error.
**Why it happens:** Both firewalls must pass traffic. Either one blocks silently.
**How to avoid:** After opening both, test from an external machine immediately: `curl -v http://161.118.209.59/`. Expect nginx 301 or 200, not timeout.
**Warning signs:** `curl` hangs > 30s, no TCP reset returned.

### Pitfall 2: Streamlit "Please Wait..." Infinite Spinner
**What goes wrong:** Dashboard loads HTML but spins forever.
**Why it happens:** nginx missing `proxy_http_version 1.1` + `Upgrade`/`Connection` headers. `/_stcore/stream` WebSocket upgrade fails.
**How to avoid:** Include WebSocket headers in `location /` block. Test: open browser DevTools → Network → filter by WS — should see one successful WebSocket connection.
**Warning signs:** Browser console shows `WebSocket connection to 'wss://dash.yourdomain.com/_stcore/stream' failed`.

### Pitfall 3: Basic Auth Breaking WebSocket
**What goes wrong:** nginx basic auth prompts for credentials on the initial HTTP request, but WebSocket upgrade requests don't carry the Authorization header.
**Why it happens:** Browsers pass basic auth on HTML fetch but often not on subsequent WebSocket upgrades.
**How to avoid:** Apply `auth_basic` at the `server` block level (not a separate location). The browser caches the basic auth credential and replays it on the WebSocket upgrade. This works in all major browsers.
**Warning signs:** Dashboard prompts for credentials, user logs in, then hangs.

### Pitfall 4: Large Table Full-Replace Freezing the VM
**What goes wrong:** `sync_dashboard_to_vm.py` attempts full-replace of a large table (e.g., `features` ~millions of rows), saturates VM disk/network, crashes.
**Why it happens:** Not checking table size before choosing sync strategy.
**How to avoid:** Use incremental watermark for any table with > 10K rows. Only full-replace dim/config tables (< 1K rows).
**Warning signs:** Sync script takes > 5 minutes for a table that should be fast.

### Pitfall 5: Missing `db_config.env` on VM
**What goes wrong:** Dashboard fails to start with "No DB URL found" error.
**Why it happens:** `resolve_db_url()` looks for `db_config.env` up to 5 dirs up. VM needs its own `db_config.env` pointing to `postgresql://...@127.0.0.1/marketdata` (local VM DB).
**How to avoid:** Create `db_config.env` in the codebase root on VM with `TARGET_DB_URL=postgresql://...@127.0.0.1:5432/marketdata`.
**Warning signs:** Systemd journal shows `RuntimeError: Cannot determine DB URL`.

### Pitfall 6: SSH Host Key Verification Failure for Reverse Tunnel
**What goes wrong:** Reverse tunnel service fails with "Host key verification failed" on first connection.
**Why it happens:** `StrictHostKeyChecking` defaults to `ask` which requires interactive input.
**How to avoid:** Use `-o StrictHostKeyChecking=accept-new` in the SSH command. This accepts on first connect, rejects changes (more secure than `no`).

---

## Code Examples

### Complete nginx config (production-ready)

```nginx
# /etc/nginx/sites-available/ta-dashboard
# Source: verified pattern from Streamlit community + nginx official docs

server {
    listen 80;
    server_name dash.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name dash.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/dash.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dash.yourdomain.com/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Basic auth (applies to all locations including WebSocket upgrades)
    auth_basic           "ta_lab2 Dashboard";
    auth_basic_user_file /etc/apache2/.htpasswd;

    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        # Required for Streamlit WebSocket (/_stcore/stream)
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";
        # Prevent timeout on long-lived WebSocket connections
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering    off;
    }
}
```

### Enabling and testing the nginx config

```bash
sudo ln -s /etc/nginx/sites-available/ta-dashboard /etc/nginx/sites-enabled/
sudo nginx -t          # must say "syntax is ok" and "test is successful"
sudo systemctl reload nginx
```

### htpasswd user management

```bash
# Create .htpasswd with first user (bcrypt -B flag)
sudo htpasswd -cB /etc/apache2/.htpasswd adam

# Add additional users (no -c flag)
sudo htpasswd -B /etc/apache2/.htpasswd collaborator1

# Delete a user
sudo htpasswd -D /etc/apache2/.htpasswd olduser
```

### Systemd service management

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ta-dashboard
sudo systemctl status ta-dashboard
sudo journalctl -u ta-dashboard -f   # tail logs
```

### Verify certbot auto-renewal

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

---

## Dashboard DB Dependencies — Complete Table Inventory

All tables queried by the dashboard (traced from `src/ta_lab2/dashboard/queries/*.py` and `pages/*.py`):

### public schema (sync required — local to VM)

**Operations / Execution:**
- `positions`, `fills`, `orders` — trading state
- `executor_run_log` — executor status
- `pipeline_run_log`, `pipeline_stage_log` — pipeline ops page
- `dim_executor_config` — strategy configs
- `drift_metrics`, `v_drift_summary` (view) — drift monitor
- `dim_risk_state`, `dim_risk_limits`, `risk_events` — risk controls

**Research:**
- `strategy_bakeoff_results` — leaderboard, backtest results
- `ic_results` — research explorer
- `feature_experiments` — experiments page
- `regimes`, `regime_flips`, `regime_stats`, `regime_comovement` — regime heatmap
- `macro_regimes` — macro page
- `portfolio_allocations` — portfolio page
- `asset_stats` — asset stats page
- `corr_latest` (materialized view) — cross-asset corr
- `features` — feature time series (large — incremental only)

**Dimension tables (small, full replace):**
- `dim_assets`, `dim_timeframe`, `dim_signals`, `dim_ama_params`
- `cmc_da_info` — symbol lookup

**Coverage:**
- `asset_data_coverage` — pipeline monitor

**Dynamic (discovered at runtime):**
- `signals_ema_crossover`, `signals_rsi_mean_revert`, `signals_atr_breakout` — signal browser
- `*_stats` tables — pipeline monitor (auto-discovered via `information_schema`)

### hyperliquid schema (skip sync — VM is source)
- `hyperliquid.hl_assets`, `hyperliquid.hl_candles`, `hyperliquid.hl_funding_rates`, `hyperliquid.hl_open_interest` — all already on VM

### fred schema (skip for MVP)
- `fred.series_values` — macro page (FRED data lives on GCP VM, not Oracle VM)

### Large tables that need incremental sync (not full replace)
- `features` — ~4.1M rows, use `ts` watermark per `(id, tf)`
- `ema_multi_tf_u` — ~14.8M rows; skip unless AMA inspector needed
- `ama_multi_tf_u` — ~91.3M rows; skip unless AMA inspector needed
- `strategy_bakeoff_results` — can be large; use `completed_at` watermark
- `ic_results` — use `computed_at` watermark
- `regimes`, `regime_stats`, `regime_comovement`, `regime_flips` — use `ts` watermark

**MVP sync scope (operations focus):** Prioritize execution/ops tables. Research tables (features, ema, ama) can be deferred or synced weekly.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Streamlit `/stream` WebSocket endpoint | `/_stcore/stream` | Streamlit ~v1.12 (2023) | Existing nginx configs with `/stream` location block break |
| nginx + Streamlit: separate location for stream | WebSocket headers in root `location /` | Community consensus 2024 | Simpler; root block handles all endpoints |
| certbot cron job | certbot systemd timer (auto-installed) | Ubuntu 20.04+ | Timer is auto-enabled; no manual cron needed |
| Manual iptables commands | `netfilter-persistent save` | Standard Ubuntu | Rules survive reboots |

**Deprecated/outdated:**
- `proxy_set_header Connection "Upgrade"` (capital U): Use lowercase `"upgrade"` — both work but lowercase is nginx convention.

---

## Open Questions

1. **VM PostgreSQL setup for `public` schema tables**
   - What we know: VM has PostgreSQL with `hyperliquid` schema and `hluser` credentials
   - What's unclear: Does VM have a `marketdata` database with `public` schema matching local? Or does sync_dashboard_to_vm create/migrate the schema first?
   - Recommendation: Plan must include a VM schema migration step (run Alembic or a subset of SQL DDL to create the required tables on VM before first sync)

2. **On-demand refresh button complexity**
   - What we know: Reverse SSH tunnel from local PC to VM is viable but adds local PC dependency
   - What's unclear: Is the local PC always on? Or only during working hours?
   - Recommendation: MVP = daily cron job only. On-demand button is a Phase 114 stretch goal, not required for success criteria.

3. **Python environment on VM**
   - What we know: VM runs Python scripts (HL collection cron) but may not have ta_lab2 installed
   - What's unclear: Does ta_lab2 need full installation on VM or just dashboard + queries?
   - Recommendation: Install ta_lab2 in a venv on VM. The dashboard uses `ta_lab2.io`, `ta_lab2.scripts.refresh_utils`, and all dashboard modules.

4. **FRED data on Oracle VM**
   - What we know: `fred.series_values` is queried by the macro page; FRED data lives on GCP VM
   - What's unclear: Should FRED data be synced to Oracle VM?
   - Recommendation: Skip FRED sync for MVP. The macro page will show empty/error state on VM. Add a note in dashboard.

---

## Sources

### Primary (HIGH confidence)

- Codebase direct inspection: `src/ta_lab2/dashboard/app.py`, `queries/*.py`, `pages/*.py`, `db.py` — all table dependencies verified by reading source
- `src/ta_lab2/scripts/etl/sync_hl_from_vm.py` — SSH+COPY pattern verified by reading source
- `.streamlit/config.toml` — existing config verified
- [DigitalOcean: Secure Nginx with Let's Encrypt on Ubuntu 22.04](https://www.digitalocean.com/community/tutorials/how-to-secure-nginx-with-let-s-encrypt-on-ubuntu-22-04) — certbot commands verified
- [nginx official docs: HTTP Basic Authentication](https://docs.nginx.com/nginx/admin-guide/security-controls/configuring-http-basic-authentication/) — htpasswd directives verified
- [TechOverflow: systemd service for Streamlit (2025-03-17)](https://techoverflow.net/2025/03/17/systemd-service-file-for-autostarting-streamlit-application/) — systemd unit pattern verified

### Secondary (MEDIUM confidence)

- [Oracle Cloud: Opening ports 80/443](https://dev.to/armiedema/opening-up-port-80-and-443-for-oracle-cloud-servers-j35) — dual-layer firewall (Security List + iptables) confirmed by multiple Oracle Cloud users
- [Streamlit forum: nginx WebSocket configuration](https://discuss.streamlit.io/t/how-to-use-streamlit-with-nginx/378) — WebSocket headers confirmed
- [GitHub Gist: Persistent reverse SSH tunnel systemd service](https://gist.github.com/Duckle29/e3d2caea714dd2a5514187a6288fa743) — systemd unit pattern verified

### Tertiary (LOW confidence — validate before use)

- [GitHub issue #8223: Streamlit + htpasswd](https://github.com/streamlit/streamlit/issues/8223) — basic auth + WebSocket issue; workaround (apply auth at server level) needs testing
- Mobile CSS approach — community patterns, not Streamlit official docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all components are standard Ubuntu/nginx tooling
- Architecture (nginx + systemd): HIGH — verified against official docs and community patterns
- Data sync pattern: HIGH — directly adapted from existing codebase patterns
- Oracle Cloud firewall: MEDIUM — multiple community sources agree, not official Oracle docs
- Pitfalls: HIGH — most traced from actual Streamlit issues/discussions
- Mobile CSS: LOW — community patterns; Streamlit doesn't guarantee CSS selector stability

**Research date:** 2026-04-01
**Valid until:** 2026-06-01 (stable ecosystem; certbot/nginx/Streamlit rarely break APIs)
