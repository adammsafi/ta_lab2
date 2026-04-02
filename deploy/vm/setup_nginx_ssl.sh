#!/usr/bin/env bash
# setup_nginx_ssl.sh — Install nginx, certbot, and configure HTTPS + basic auth
# for the ta_lab2 Streamlit dashboard on the Oracle Cloud VM.
#
# Usage:
#   bash setup_nginx_ssl.sh <domain>
#
# Example:
#   bash setup_nginx_ssl.sh dashboard.example.com
#
# Prerequisites (must be done before running this script):
#   1. DNS A record for <domain> must point to this VM's public IP
#   2. OCI Security List must allow ingress on TCP 80 and 443
#      (script will remind you — it cannot modify OCI console settings)
#   3. Streamlit service must already be running on 127.0.0.1:8501
#      (see setup_dashboard_env.sh and streamlit.service)
#
# Idempotent: safe to re-run; existing cert/config will not be overwritten.

set -euo pipefail

DOMAIN="${1:?Usage: $0 <domain>}"
NGINX_CONF_SRC="$(dirname "$0")/nginx_streamlit.conf"
NGINX_SITE_DEST="/etc/nginx/sites-available/streamlit"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/streamlit"
NGINX_DEFAULT_LINK="/etc/nginx/sites-enabled/default"
HTPASSWD_FILE="/etc/nginx/.htpasswd"
CERTBOT_WEBROOT="/var/www/certbot"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
info()    { echo "[INFO]  $*"; }
success() { echo "[OK]    $*"; }
warn()    { echo "[WARN]  $*"; }
die()     { echo "[ERROR] $*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || die "This script must be run as root (sudo bash $0 $DOMAIN)"
}

# ---------------------------------------------------------------------------
# Step 1: Install packages
# ---------------------------------------------------------------------------
install_packages() {
    info "Installing nginx, certbot, apache2-utils..."

    apt-get update -qq

    local packages=(nginx certbot python3-certbot-nginx apache2-utils iptables-persistent)
    local to_install=()

    for pkg in "${packages[@]}"; do
        if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
            to_install+=("$pkg")
        fi
    done

    if [[ ${#to_install[@]} -gt 0 ]]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y "${to_install[@]}"
        success "Installed: ${to_install[*]}"
    else
        success "All packages already installed"
    fi
}

# ---------------------------------------------------------------------------
# Step 2: Create htpasswd file
# ---------------------------------------------------------------------------
create_htpasswd() {
    if [[ -f "$HTPASSWD_FILE" ]]; then
        warn ".htpasswd already exists at $HTPASSWD_FILE — skipping creation"
        warn "To add more users:  htpasswd -b $HTPASSWD_FILE <username> <password>"
        warn "To replace a user:  htpasswd -b $HTPASSWD_FILE <username> <newpassword>"
        return
    fi

    info "Creating basic auth credentials..."
    echo ""
    echo "============================================================"
    echo "  ACTION REQUIRED: Create dashboard login credentials"
    echo "============================================================"
    echo ""
    read -rp ">>> Enter dashboard username: " AUTH_USER
    [[ -n "$AUTH_USER" ]] || die "Username cannot be empty"

    read -rsp ">>> Enter dashboard password: " AUTH_PASS
    echo ""
    [[ -n "$AUTH_PASS" ]] || die "Password cannot be empty"

    read -rsp ">>> Confirm password: " AUTH_PASS2
    echo ""
    [[ "$AUTH_PASS" == "$AUTH_PASS2" ]] || die "Passwords do not match"

    htpasswd -cb "$HTPASSWD_FILE" "$AUTH_USER" "$AUTH_PASS"
    chmod 640 "$HTPASSWD_FILE"
    chown root:www-data "$HTPASSWD_FILE"
    success "Created $HTPASSWD_FILE for user '$AUTH_USER'"
    echo ""
    info "To add additional users later:"
    info "  htpasswd -b $HTPASSWD_FILE <username> <password>"
}

# ---------------------------------------------------------------------------
# Step 3: Install nginx config
# ---------------------------------------------------------------------------
install_nginx_config() {
    info "Installing nginx config for domain: $DOMAIN"

    [[ -f "$NGINX_CONF_SRC" ]] || die "nginx_streamlit.conf not found at $NGINX_CONF_SRC"

    # Remove default site to avoid conflicts
    if [[ -L "$NGINX_DEFAULT_LINK" ]]; then
        rm "$NGINX_DEFAULT_LINK"
        success "Removed default nginx site"
    fi

    # Create certbot webroot directory for ACME challenge
    mkdir -p "$CERTBOT_WEBROOT"

    local cert_dir="/etc/letsencrypt/live/$DOMAIN"
    if [[ -d "$cert_dir" ]]; then
        # Certs exist — install full SSL config directly
        info "SSL certs already exist, installing full config"
        sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "$NGINX_CONF_SRC" > "$NGINX_SITE_DEST"
    else
        # No certs yet — install HTTP-only config so certbot can run
        info "No SSL certs yet — installing temporary HTTP-only config for certbot"
        cat > "$NGINX_SITE_DEST" <<HTTPCONF
server {
    listen 80;
    server_name $DOMAIN;

    auth_basic "ta_lab2 Dashboard";
    auth_basic_user_file $HTPASSWD_FILE;

    location /.well-known/acme-challenge/ {
        auth_basic off;
        root $CERTBOT_WEBROOT;
    }

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
HTTPCONF
    fi
    success "Wrote $NGINX_SITE_DEST (domain=$DOMAIN)"

    # Create symlink in sites-enabled
    if [[ ! -L "$NGINX_SITE_LINK" ]]; then
        ln -s "$NGINX_SITE_DEST" "$NGINX_SITE_LINK"
        success "Created symlink $NGINX_SITE_LINK"
    else
        success "Symlink $NGINX_SITE_LINK already exists"
    fi

    # Validate and reload nginx
    info "Testing nginx configuration..."
    nginx -t 2>&1 || die "nginx -t failed — check $NGINX_SITE_DEST"
    systemctl reload nginx 2>/dev/null || systemctl start nginx
    success "nginx running with HTTP config"
}

# ---------------------------------------------------------------------------
# Step 4: Configure firewall (Oracle Cloud dual-layer)
# ---------------------------------------------------------------------------
configure_firewall() {
    info "Configuring iptables firewall rules..."

    # Oracle Cloud has TWO firewall layers:
    #   1. Host-level iptables (this script handles)
    #   2. OCI Security List / Network Security Group (requires OCI console)

    for PORT in 80 443; do
        # Check if rule already exists
        if iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
            success "iptables rule for port $PORT already exists"
            continue
        fi

        # Find the line number of the first REJECT rule in INPUT chain
        REJECT_LINE=$(iptables -L INPUT --line-numbers -n 2>/dev/null \
            | grep -i 'REJECT\|reject' \
            | head -1 \
            | awk '{print $1}')

        if [[ -n "$REJECT_LINE" ]]; then
            # Insert BEFORE the REJECT rule (position matters — REJECT is a catch-all)
            iptables -I INPUT "$REJECT_LINE" -p tcp --dport "$PORT" -j ACCEPT
            success "Inserted iptables ACCEPT rule for port $PORT before REJECT line $REJECT_LINE"
        else
            # No REJECT rule found — append to INPUT chain
            iptables -A INPUT -p tcp --dport "$PORT" -j ACCEPT
            success "Appended iptables ACCEPT rule for port $PORT (no REJECT rule found)"
        fi
    done

    # Persist rules across reboots
    netfilter-persistent save
    success "Saved iptables rules with netfilter-persistent"

    # OCI Security List cannot be modified by a script — must be done in console
    echo ""
    echo "============================================================"
    echo "  WARNING: OCI Security List action required"
    echo "============================================================"
    echo "  This script configured host-level iptables, but Oracle"
    echo "  Cloud also enforces VCN Security Lists / NSGs."
    echo ""
    echo "  You MUST manually allow ports 80 and 443 in the OCI console:"
    echo ""
    echo "  1. Open: https://cloud.oracle.com -> Networking -> VCN"
    echo "  2. Select your VCN -> Security Lists -> Default Security List"
    echo "  3. Add Ingress Rules:"
    echo "     Protocol: TCP  |  Source: 0.0.0.0/0  |  Port: 80"
    echo "     Protocol: TCP  |  Source: 0.0.0.0/0  |  Port: 443"
    echo "============================================================"
    echo ""
    read -rp "Press ENTER after you have opened ports 80 and 443 in OCI console (or Ctrl+C to skip certbot)..."
}

# ---------------------------------------------------------------------------
# Step 5: Obtain SSL certificate with certbot
# ---------------------------------------------------------------------------
obtain_ssl_cert() {
    local cert_dir="/etc/letsencrypt/live/$DOMAIN"

    if [[ -d "$cert_dir" ]]; then
        success "SSL certificate already exists at $cert_dir"
        info "To force renewal: certbot renew --force-renewal -d $DOMAIN"
        return
    fi

    info "Obtaining Let's Encrypt SSL certificate for $DOMAIN..."

    # Use --webroot mode: nginx serves HTTP on port 80, certbot places challenge
    # files in the webroot. After cert is obtained, we install the full SSL config.
    if certbot certonly --webroot \
        -w "$CERTBOT_WEBROOT" \
        -d "$DOMAIN" \
        --non-interactive \
        --agree-tos \
        --email "admin@$DOMAIN"; then
        success "SSL certificate obtained for $DOMAIN"

        # Now install the full SSL config (certs exist)
        info "Installing full SSL nginx config..."
        sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "$NGINX_CONF_SRC" > "$NGINX_SITE_DEST"
        nginx -t 2>&1 || die "Full SSL nginx config failed validation"
        systemctl reload nginx
        success "nginx now serving HTTPS for $DOMAIN"
    else
        echo ""
        warn "certbot failed — this usually means:"
        warn "  - DNS A record for $DOMAIN does not yet point to this server's IP"
        warn "  - Port 80 is not reachable from the internet (check OCI Security List)"
        echo ""
        info "Once DNS and firewall are confirmed, retry with:"
        info "  certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN"
        info ""
        info "Or use the dry-run to test without issuing a cert:"
        info "  certbot certonly --nginx --dry-run -d $DOMAIN"
        echo ""
        # Do not exit — continue so user gets a working nginx (HTTP-only until cert obtained)
    fi
}

# ---------------------------------------------------------------------------
# Step 6: Verify certbot auto-renewal timer
# ---------------------------------------------------------------------------
verify_renewal_timer() {
    info "Checking certbot auto-renewal timer..."

    if systemctl list-timers 2>/dev/null | grep -i certbot; then
        success "certbot renewal timer is active"
    else
        warn "certbot renewal timer not found — attempting to enable..."
        systemctl enable certbot.timer 2>/dev/null && systemctl start certbot.timer 2>/dev/null || {
            warn "Could not enable certbot.timer — renewal may need to be configured manually"
            warn "Fallback: add to cron:  0 12 * * * /usr/bin/certbot renew --quiet"
        }
    fi
}

# ---------------------------------------------------------------------------
# Step 7: Reload nginx
# ---------------------------------------------------------------------------
reload_nginx() {
    info "Enabling and reloading nginx..."

    systemctl enable nginx
    systemctl start nginx || true

    # Try reload first; fall back to restart if reload fails
    if systemctl is-active --quiet nginx; then
        nginx -t && systemctl reload nginx
        success "nginx reloaded"
    else
        systemctl restart nginx
        success "nginx started"
    fi
}

# ---------------------------------------------------------------------------
# Step 8: Print summary
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    echo "============================================================"
    echo "  Setup complete"
    echo "============================================================"
    echo "  Domain   : $DOMAIN"
    echo "  URL      : https://$DOMAIN"
    echo "  Auth file: $HTPASSWD_FILE"
    echo "  Nginx cfg: $NGINX_SITE_DEST"
    echo "  Cert dir : /etc/letsencrypt/live/$DOMAIN"
    echo ""
    echo "  Add dashboard users:"
    echo "    htpasswd -b $HTPASSWD_FILE <username> <password>"
    echo ""
    echo "  Remove a user:"
    echo "    htpasswd -D $HTPASSWD_FILE <username>"
    echo ""
    echo "  Force cert renewal:"
    echo "    certbot renew --force-renewal -d $DOMAIN"
    echo ""
    echo "  Certbot renewal timers:"
    systemctl list-timers 2>/dev/null | grep -i certbot || echo "    (none active)"
    echo ""
    echo "  nginx status:"
    systemctl is-active nginx || true
    echo "============================================================"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    require_root
    echo ""
    echo "============================================================"
    echo "  ta_lab2 nginx + SSL setup for: $DOMAIN"
    echo "============================================================"
    echo ""

    install_packages
    create_htpasswd
    install_nginx_config
    configure_firewall
    obtain_ssl_cert
    verify_renewal_timer
    reload_nginx
    print_summary
}

main "$@"
