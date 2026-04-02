---
phase: 114-hosted-dashboard
plan: 05
subsystem: deploy
tags: [deployment, nginx, ssl, mobile, dashboard, vm]

requires:
  - phase: 114-hosted-dashboard
    plan: 01
    provides: sync_dashboard_to_vm.py
  - phase: 114-hosted-dashboard
    plan: 02
    provides: VM deployment artifacts (setup_dashboard_env.sh, streamlit.service, streamlit_config.toml)
  - phase: 114-hosted-dashboard
    plan: 03
    provides: nginx + SSL + basic auth (setup_nginx_ssl.sh, nginx_streamlit.conf)
  - phase: 114-hosted-dashboard
    plan: 04
    provides: Mobile responsive CSS (mobile.py, app.py updates)
provides:
  - deploy_dashboard.sh master deployment orchestrator
  - Live dashboard at https://pacificbit.io with SSL + basic auth

affects: [daily-operations, monitoring, mobile-access]

tech-stack:
  added: [nginx, certbot, htpasswd]
  patterns:
    - "Wheel-based deploy: build locally, SCP single .whl, pip install on VM"
    - "HTTP-first certbot: temporary HTTP-only nginx config for cert acquisition, then switch to full SSL"
    - "Dual-layer firewall: iptables INSERT before REJECT + OCI Security List manual step"

key-files:
  created:
    - deploy/vm/deploy_dashboard.sh

key-decisions:
  - "Wheel-based deploy instead of rsync: matches Phase 113 executor pattern, single file vs 30K files"
  - "WSL SSH key auto-copy: cp from /mnt/c/ to ~/.ssh/ with chmod 600 to work around 0777 mount permissions"
  - "HTTP-first certbot flow: install HTTP-only nginx, get cert via --webroot, then sed-replace to full SSL config"
  - "TRUNCATE CASCADE for dim tables: FK references from data tables prevent plain TRUNCATE"
  - "Regular staging tables (not TEMP): TEMP tables don't persist across separate psql SSH sessions"

duration: 120min (including DNS propagation, OCI firewall setup, debugging deploy issues)
completed: 2026-04-02
---

# Phase 114 Plan 05: Master Deploy Script + Live Verification

**Single-command deployment orchestrator verified against live production deployment at https://pacificbit.io**

## Performance

- **Duration:** ~2 hours (including DNS, OCI, debugging)
- **Started:** 2026-04-02T06:29:00Z
- **Completed:** 2026-04-02T08:00:00Z
- **Tasks:** 2 (1 auto + 1 checkpoint)
- **Files modified:** 1 created + 4 fixed

## Accomplishments

- Created `deploy/vm/deploy_dashboard.sh`: wheel build + SCP + VM setup + nginx/SSL + data push + verification, with --code-only and --data-only flags
- Dashboard live at https://pacificbit.io with Let's Encrypt SSL (expires 2026-07-01, auto-renews)
- Basic auth via htpasswd protecting all routes
- Streamlit service running on 127.0.0.1:8501 behind nginx reverse proxy
- Fixed multiple deployment issues discovered during live deploy:
  - SSH key path resolution across WSL/Git Bash/PowerShell
  - CRLF line endings breaking bash scripts on Linux VM
  - Certbot chicken-and-egg (SSL config references certs before they exist)
  - sync_dashboard_to_vm.py: bytes/str mismatch, TRUNCATE CASCADE, staging tables, watermark column names

## Task Commits

1. **Task 1: Create master deploy script** - `704a58fa` (feat)
2. **Task 2: Human verification** - Approved: dashboard live at https://pacificbit.io
3. **Post-checkpoint fixes** - `4383229e` (fix)

## Files Created/Modified

- `deploy/vm/deploy_dashboard.sh` - Master deployment orchestrator
- `deploy/vm/setup_nginx_ssl.sh` - Fixed HTTP-first certbot flow + clear prompts
- `deploy/vm/setup_dashboard_env.sh` - Fixed BASE_DIR variable reference
- `src/ta_lab2/scripts/etl/sync_dashboard_to_vm.py` - Fixed bytes/str, CASCADE, staging, watermarks

## Deviations from Plan

- Wheel-based deploy instead of rsync (matching Phase 113 pattern, faster)
- HTTP-first certbot flow instead of --nginx plugin (avoids chicken-and-egg with SSL config)
- Multiple SSH key path resolution strategies for cross-platform compatibility

## Issues Encountered

- DNS propagation delay (~30 min) with GoDaddy parking IPs conflicting
- Squarespace locked A records required disconnection before cleanup
- WSL mounts Windows files as 0777, SSH rejects — auto-copy to ~/.ssh/ with chmod 600
- pg_dump schema had "already exists" errors on VM (tables from Phase 113) — harmless, CREATE IF NOT EXISTS
- sync_dashboard_to_vm still has remaining issues (some tables need further watermark column fixes) — iterative improvement

---
*Phase: 114-hosted-dashboard*
*Completed: 2026-04-02*
