# Phase 114: Hosted Dashboard - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Host the existing Streamlit dashboard on the Oracle Singapore VM behind nginx + SSL, accessible from any device (mobile, other machines) without the local PC running. Includes data sync from local to VM, authentication, and mobile CSS tweaks.

</domain>

<decisions>
## Implementation Decisions

### Data sync strategy
- VM-local DB copy: sync pushes dashboard-relevant tables to VM PostgreSQL; dashboard queries locally on VM
- Sync approach: Claude's discretion on incremental watermark vs full replace (based on table sizes and existing sync patterns)
- Refresh frequency: once daily by default (after pipeline), with on-demand option
- On-demand refresh button in dashboard: triggers sync via reverse SSH tunnel from VM to local PC
- `sync_dashboard_to_vm` script handles the push; dashboard includes a "Refresh Data" button that invokes it

### Access control
- nginx basic auth with `.htpasswd` file (browser native login prompt)
- Multiple users supported: 2-3 users initially (user + collaborators)
- No IP allowlist — auth alone is sufficient
- User management via CLI (`htpasswd` command on VM), no in-dashboard admin page

### SSL & domain setup
- User has a domain; dashboard served on a subdomain (e.g., dash.yourdomain.com)
- Let's Encrypt SSL with certbot auto-renewal (systemd timer)
- HTTP (port 80) redirects to HTTPS (port 443)
- Firewall status unknown: plan must include verification + setup of Oracle security lists and iptables for ports 80/443
- Fresh deployment: Streamlit not currently running on VM
- Streamlit runs as a systemd service (auto-start on boot, auto-restart on crash)

### Mobile experience
- All dashboard features should work on mobile: status checks, full analysis, and emergency response (kill switch, risk overrides)
- CSS tweaks for improved mobile layout: column stacking, font sizes, chart widths
- No PWA — browser-only access, bookmarkable
- No specific performance concerns; verify <2s page load target on VM

### Claude's Discretion
- Exact sync approach (incremental watermark vs full replace per table)
- Which tables to include in the sync set
- nginx configuration details (buffer sizes, timeouts, WebSocket proxy for Streamlit)
- Streamlit systemd unit file configuration
- Specific CSS customizations for mobile responsiveness
- Reverse SSH tunnel implementation for the refresh button

</decisions>

<specifics>
## Specific Ideas

- On-demand refresh button in the dashboard that triggers a sync via reverse SSH tunnel to local PC
- Subdomain-based URL (not path-based) for cleaner nginx config and Streamlit compatibility
- systemd service for Streamlit matches the pattern used for other VM services (HL data collection, etc.)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 114-hosted-dashboard*
*Context gathered: 2026-04-01*
