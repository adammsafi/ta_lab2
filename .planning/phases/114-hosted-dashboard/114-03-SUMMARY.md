---
phase: 114-hosted-dashboard
plan: 03
subsystem: infra
tags: [nginx, ssl, certbot, letsencrypt, htpasswd, iptables, streamlit, websocket, reverse-proxy, oracle-cloud]

# Dependency graph
requires:
  - phase: 114-02
    provides: Streamlit service running on 127.0.0.1:8501 on Oracle VM
provides:
  - nginx reverse proxy config with server-level basic auth and WebSocket support
  - Let's Encrypt SSL setup script for Oracle Cloud VM
  - iptables dual-layer firewall configuration (host + OCI Security List guidance)
affects:
  - 114-04 (systemd/cron automation, sync integration)
  - 114-05 (final verification and go-live)

# Tech tracking
tech-stack:
  added: [nginx, certbot, python3-certbot-nginx, apache2-utils, iptables-persistent]
  patterns:
    - nginx server-level auth_basic (not location-level) to preserve WebSocket handshake
    - proxy_buffering off for Streamlit Server-Sent Events streaming
    - DOMAIN_PLACEHOLDER pattern for sed-based config templating
    - iptables INSERT before REJECT line (Oracle Cloud requires exact rule ordering)
    - certbot --nginx non-interactive with graceful failure and retry instructions

key-files:
  created:
    - deploy/vm/nginx_streamlit.conf
    - deploy/vm/setup_nginx_ssl.sh

key-decisions:
  - "auth_basic at server block level (not location level) — location-level auth breaks WebSocket upgrade handshake"
  - "WebSocket headers (Upgrade/Connection) in root / location, not in separate /_stcore/stream block — Streamlit internal path can change across versions"
  - "proxy_buffering off is mandatory — omitting causes infinite 'Please wait...' spinner in Streamlit"
  - "iptables -I INPUT before REJECT line, not append — Oracle Cloud default iptables has a catch-all REJECT that blocks if not ordered correctly"
  - "OCI Security List printed as WARNING with exact console steps — script cannot modify VCN-level rules"
  - "certbot failure is non-fatal in setup script — prints retry instructions to allow running before DNS is pointed"

patterns-established:
  - "DOMAIN_PLACEHOLDER: sed-replaceable token in nginx conf, replaced by setup_nginx_ssl.sh"
  - "Idempotent VM scripts: check existing cert/htpasswd/packages before acting"

# Metrics
duration: 2min
completed: 2026-04-01
---

# Phase 114 Plan 03: nginx + SSL + Basic Auth Summary

**nginx reverse proxy with server-level htpasswd auth, Let's Encrypt SSL via certbot, and Oracle Cloud dual-layer iptables firewall — WebSocket-safe Streamlit setup**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-04-02T05:44:44Z
- **Completed:** 2026-04-02T05:46:44Z
- **Tasks:** 2/2
- **Files created:** 2

## Accomplishments

- Created `nginx_streamlit.conf` with HTTP-to-HTTPS redirect, ACME challenge passthrough, server-level basic auth, and WebSocket-safe proxy_pass to Streamlit
- Created `setup_nginx_ssl.sh` — idempotent VM setup script covering nginx install, htpasswd creation, certbot SSL, dual-layer Oracle Cloud firewall, and renewal timer verification
- Documented all critical anti-patterns (auth_basic in location, buffering on, separate WebSocket location) inline in both files

## Task Commits

1. **Task 1: Create nginx config template** - `24550baf` (feat)
2. **Task 2: Create nginx + SSL setup script** - `c97143b9` (feat)

**Plan metadata:** (docs commit follows this summary commit)

## Files Created/Modified

- `deploy/vm/nginx_streamlit.conf` — nginx server blocks: HTTP redirect, HTTPS with SSL, server-level auth_basic, WebSocket proxy_pass to 127.0.0.1:8501, proxy_buffering off
- `deploy/vm/setup_nginx_ssl.sh` — idempotent setup script: installs packages, creates .htpasswd, deploys conf, configures iptables, obtains certbot cert, verifies renewal timer

## Decisions Made

- **auth_basic at server level, not location level:** Location-level auth breaks WebSocket upgrade handshake because nginx re-evaluates auth per location during the upgrade request. Server-level applies to all requests including WebSocket upgrades.

- **WebSocket headers in root / block, not /_stcore/stream:** Streamlit's internal streaming path (`/_stcore/stream`) is version-specific. Placing WebSocket headers in root location covers all paths regardless of Streamlit version.

- **proxy_buffering off mandatory:** Without this, nginx buffers the response from Streamlit, preventing Server-Sent Events from reaching the browser immediately. This causes the infinite "Please wait..." spinner.

- **iptables INSERT before REJECT, not APPEND:** Oracle Cloud's default iptables configuration includes a catch-all REJECT rule. Appending ACCEPT rules after REJECT has no effect — rules must be inserted before the REJECT line.

- **certbot failure is non-fatal:** Setup script continues even if certbot fails (e.g., DNS not yet pointed). Prints exact retry commands. Allows running setup script before DNS propagation.

- **OCI Security List printed as WARNING:** The VCN-level security list cannot be modified by a shell script — it requires the OCI console. Script prints exact navigation path and pauses for user acknowledgment.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- `nginx_streamlit.conf` and `setup_nginx_ssl.sh` ready for VM deployment
- Phase 114-04 can add cron/systemd automation for dashboard data refresh
- Phase 114-05 (go-live verification) can reference `setup_nginx_ssl.sh` for deployment checklist

---
*Phase: 114-hosted-dashboard*
*Completed: 2026-04-01*
