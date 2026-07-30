#!/bin/bash
# ============================================================
#  AlphaSync — Contabo VPS Initial Server Setup
#  Run this ONCE on a fresh Ubuntu 22.04/24.04 server
#  Usage: ssh root@YOUR_SERVER_IP 'bash -s' < deploy/setup-server.sh
# ============================================================
set -euo pipefail

DOMAIN="www.alphasync.app"
APP_DIR="/opt/alphasync"
DEPLOY_USER="deploy"

echo "=========================================="
echo "  AlphaSync Server Setup — Contabo VPS"
echo "=========================================="

# ── 1. System Update ────────────────────────────────────────
echo "→ Updating system packages..."
apt-get update && apt-get upgrade -y

# ── 2. Install Docker ───────────────────────────────────────
echo "→ Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi
echo "  Docker $(docker --version)"

# ── 3. Install Docker Compose plugin ────────────────────────
echo "→ Verifying Docker Compose..."
docker compose version || {
    apt-get install -y docker-compose-plugin
}

# ── 4. Create deploy user ──────────────────────────────────
echo "→ Creating deploy user..."
if ! id "$DEPLOY_USER" &>/dev/null; then
    useradd -m -s /bin/bash -G docker "$DEPLOY_USER"
    mkdir -p /home/$DEPLOY_USER/.ssh
    cp /root/.ssh/authorized_keys /home/$DEPLOY_USER/.ssh/ 2>/dev/null || true
    chown -R $DEPLOY_USER:$DEPLOY_USER /home/$DEPLOY_USER/.ssh
    chmod 700 /home/$DEPLOY_USER/.ssh
    chmod 600 /home/$DEPLOY_USER/.ssh/authorized_keys 2>/dev/null || true
    echo "  Created user: $DEPLOY_USER"
else
    echo "  User $DEPLOY_USER already exists"
fi

# ── 5. Setup application directory ──────────────────────────
echo "→ Setting up $APP_DIR..."
mkdir -p $APP_DIR/deploy/nginx
chown -R $DEPLOY_USER:$DEPLOY_USER $APP_DIR

# ── 6. Firewall (UFW) ──────────────────────────────────────
echo "→ Configuring firewall..."
apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw --force enable
echo "  Firewall: SSH, HTTP, HTTPS allowed"

# ── 7. Fail2Ban (brute-force protection) ────────────────────
echo "→ Installing fail2ban..."
apt-get install -y fail2ban
systemctl enable fail2ban
systemctl start fail2ban

# ── 8. Swap space (if < 4GB RAM available) ──────────────────
echo "→ Checking swap..."
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "  Created 2GB swap"
else
    echo "  Swap already configured"
fi

# ── 9. SSH hardening ───────────────────────────────────────
echo "→ Hardening SSH..."
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/#PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart sshd

# ── 10. Auto security updates ──────────────────────────────
echo "→ Enabling auto security updates..."
apt-get install -y unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

echo ""
echo "=========================================="
echo "  ✅ Server setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Copy .env.production to $APP_DIR/.env and fill in secrets"
echo "  2. Point DNS: $DOMAIN → $(curl -s ifconfig.me)"
echo "  3. Run SSL setup: ssh $DEPLOY_USER@$(curl -s ifconfig.me) 'bash /opt/alphasync/deploy/setup-ssl.sh'"
echo "  4. Push to GitHub main branch to trigger deployment"
echo ""
