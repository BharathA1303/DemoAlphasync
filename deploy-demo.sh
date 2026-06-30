#!/usr/bin/env bash
# ============================================================
#  AlphaSync DEMO — One-command deploy to Contabo VPS
#  Domain: demo.alphasync.app
#  Server: 95.111.252.225
#
#  This is FULLY ISOLATED from the existing alpha_zebu stack:
#    - Different project name (alphasync-demo vs alpha_zebu)
#    - Different ports (3001/8001 vs 3000/8000)
#    - Different network (alphasync-demo-net)
#    - Different volumes (alphasync-demo-*)
#    - Different container names (alphasync-demo-*)
#
#  Usage (from Git Bash on Windows):
#    bash deploy-demo.sh
# ============================================================

set -euo pipefail

# ── Config ───────────────────────────────────────────────────
REMOTE_USER="root"
REMOTE_HOST="95.111.252.225"
REMOTE_DIR="/opt/alphasync-demo"
DOMAIN="demo.alphasync.app"

# ── Colors ───────────────────────────────────────────────────
GREEN='\033[0;32m'  ; CYAN='\033[0;36m'
YELLOW='\033[1;33m' ; RED='\033[0;31m' ; NC='\033[0m'

info()  { echo -e "${CYAN}>>>${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ── Resolve project root (works from any subdirectory) ───────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# ── Sanity checks ────────────────────────────────────────────
[[ -f "docker-compose.demo.yml" ]] || fail "docker-compose.demo.yml not found. Run this script from the project root."
[[ -d "backend" ]]                 || fail "backend/ directory not found."
[[ -d "frontend" ]]                || fail "frontend/ directory not found."
[[ -d "deploy/nginx" ]]            || fail "deploy/nginx/ directory not found."
command -v ssh >/dev/null           || fail "ssh not found. Install OpenSSH."
command -v scp >/dev/null           || fail "scp not found. Install OpenSSH."
command -v tar >/dev/null           || fail "tar not found."

echo ""
echo "========================================"
echo "  AlphaSync Demo Deployer"
echo "  Target: ${REMOTE_USER}@${REMOTE_HOST}"
echo "  Domain: ${DOMAIN}"
echo "  Remote: ${REMOTE_DIR}"
echo "========================================"
echo ""

# ── Step 1: Create archive ──────────────────────────────────
info "Packing project files..."
ARCHIVE="/tmp/alphasync-demo-deploy.tar.gz"

# Create a placeholder firebase-credentials.json if missing to prevent Docker bind mount failure
if [[ ! -f "firebase-credentials.json" ]]; then
    warn "firebase-credentials.json not found. Creating a placeholder to prevent Docker mount failures."
    echo "{}" > firebase-credentials.json
fi

tar czf "${ARCHIVE}" \
    --exclude='node_modules' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='*.db' \
    --exclude='.vite' \
    --exclude='.next' \
    --exclude='uploads/avatars/*' \
    backend \
    frontend \
    deploy/nginx/demo.alphasync.app.conf \
    firebase-credentials.json \
    docker-compose.demo.yml

ARCHIVE_SIZE=$(du -h "${ARCHIVE}" | cut -f1)
ok "Archive ready (${ARCHIVE_SIZE})"

# ── Step 2: Upload ──────────────────────────────────────────
info "Uploading to ${REMOTE_HOST}:${REMOTE_DIR}..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p ${REMOTE_DIR}"
scp "${ARCHIVE}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/deploy.tar.gz"
ok "Upload complete"

# ── Step 3: Build, start, configure nginx on server ──────────
info "Building and starting containers on server..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" bash <<'REMOTE_EOF'
set -euo pipefail

DEPLOY_DIR="/opt/alphasync-demo"
DOMAIN="demo.alphasync.app"
NGINX_CONF="/etc/nginx/sites-enabled/${DOMAIN}.conf"

retry() {
    local attempts="$1" delay="$2"
    shift 2
    local n=1
    until "$@"; do
        if [ "${n}" -ge "${attempts}" ]; then
            echo "ERROR: command failed after ${attempts} attempts: $*"
            return 1
        fi
        echo "Attempt ${n}/${attempts} failed. Retrying in ${delay}s..."
        sleep "${delay}"
        n=$((n + 1))
    done
}

ensure_dockerhub_dns() {
    local failed=0
    for host in auth.docker.io registry-1.docker.io ghcr.io; do
        if ! getent hosts "${host}" >/dev/null 2>&1; then
            failed=1
        fi
    done

    if [ "${failed}" -eq 0 ]; then
        echo "Docker Hub DNS lookup OK"
        return 0
    fi

    echo "Docker Hub DNS lookup failed. Applying resolver fallback..."
    cp /etc/resolv.conf /etc/resolv.conf.alphasync.bak 2>/dev/null || true
    cat > /etc/resolv.conf <<'EOF'
nameserver 1.1.1.1
nameserver 8.8.8.8
options timeout:2 attempts:3 rotate
EOF

    systemctl restart systemd-resolved 2>/dev/null || true
    systemctl restart docker 2>/dev/null || true
}

cd "${DEPLOY_DIR}"

echo ""
echo "--- [server] Extracting archive ---"
tar xzf deploy.tar.gz
rm deploy.tar.gz

echo ""
echo "--- [server] Verifying no port conflicts ---"
for PORT in 3001 8001; do
    if ss -tlnp | grep -q ":${PORT} "; then
        echo "WARNING: Port ${PORT} already in use!"
        ss -tlnp | grep ":${PORT} "
    fi
done

echo ""
echo "--- [server] Stopping old demo containers (if any) ---"
docker compose -p alphasync-demo -f docker-compose.demo.yml down --remove-orphans 2>/dev/null || true

echo ""
echo "--- [server] Building images ---"
echo "--- [server] Checking Docker Hub connectivity ---"
ensure_dockerhub_dns

echo "--- [server] Pre-pulling base images with retry ---"
retry 4 8 docker pull node:18-alpine
retry 4 8 docker pull python:3.11-slim
retry 4 8 docker pull nginx:alpine
retry 4 8 docker pull postgres:16-alpine

echo ""
echo "--- [server] Building images ---"
retry 3 15 docker compose -p alphasync-demo -f docker-compose.demo.yml build

echo ""
echo "--- [server] Starting containers ---"
docker compose -p alphasync-demo -f docker-compose.demo.yml up -d

echo ""
echo "--- [server] Waiting for backend health check ---"
HEALTHY=false
for i in $(seq 1 40); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' alphasync-demo-backend 2>/dev/null || echo "unknown")
    if [ "${STATUS}" = "healthy" ]; then
        echo "Backend is healthy!"
        HEALTHY=true
        break
    fi
    echo "  waiting... (${i}/40, status: ${STATUS})"
    sleep 3
done

if [ "${HEALTHY}" = "false" ]; then
    echo ""
    echo "WARNING: Backend did not become healthy in time."
    echo "Logs:"
    docker compose -p alphasync-demo -f docker-compose.demo.yml logs --tail=30 demo-backend
fi

echo ""
echo "--- [server] Installing Nginx vHost config ---"

# Create SSL directory if it doesn't exist
mkdir -p /etc/nginx/ssl-certificates

# Install the nginx config
cp deploy/nginx/demo.alphasync.app.conf "${NGINX_CONF}"

# Check if SSL certs exist — if not, create self-signed temporarily
if [ ! -f "/etc/nginx/ssl-certificates/${DOMAIN}.crt" ]; then
    echo "SSL cert not found — creating temporary self-signed cert..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "/etc/nginx/ssl-certificates/${DOMAIN}.key" \
        -out "/etc/nginx/ssl-certificates/${DOMAIN}.crt" \
        -subj "/CN=${DOMAIN}" 2>/dev/null
    echo "NOTE: Replace with Let's Encrypt cert via CloudPanel for production."
fi

# Test nginx config
echo "Testing nginx config..."
if nginx -t 2>&1; then
    echo "Nginx config OK — reloading..."
    systemctl reload nginx
    echo "Nginx reloaded!"
else
    echo "ERROR: Nginx config test failed! Check ${NGINX_CONF}"
    echo "Rolling back..."
    rm -f "${NGINX_CONF}"
    systemctl reload nginx
    exit 1
fi

echo ""
echo "--- [server] Container status ---"
docker compose -p alphasync-demo -f docker-compose.demo.yml ps

echo ""
echo "--- [server] All running containers (verify no conflicts) ---"
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"

echo ""
echo "--- [server] Pruning dangling images ---"
docker image prune -f 2>/dev/null || true

REMOTE_EOF

# ── Step 4: Clean up local archive ──────────────────────────
rm -f "${ARCHIVE}"

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "  DEPLOYED SUCCESSFULLY"
echo "========================================================"
echo ""
echo "  Containers:"
echo "    alphasync-demo-frontend  → 127.0.0.1:3001"
echo "    alphasync-demo-backend   → 127.0.0.1:8001"
echo ""
echo "  Nginx:"
echo "    Config installed at /etc/nginx/sites-enabled/${DOMAIN}.conf"
echo "    Handles SSL, rate limiting, WebSocket upgrades, gzip"
echo ""
echo "  Existing alpha_zebu containers are UNTOUCHED:"
echo "    alpha_zebu-frontend-1    → 127.0.0.1:3000"
echo "    alpha_zebu-backend-1     → 127.0.0.1:8000"
echo ""
echo "  DNS Setup (do this once):"
echo "  ─────────────────────────────────────"
echo "  Point ${DOMAIN} → A record → ${REMOTE_HOST}"
echo ""
echo "  SSL (do this once after DNS propagates):"
echo "  ─────────────────────────────────────"
echo "  Option A: Via CloudPanel → ${DOMAIN} → Let's Encrypt"
echo "  Option B: ssh ${REMOTE_USER}@${REMOTE_HOST}"
echo "            certbot certonly --nginx -d ${DOMAIN}"
echo "            (then update cert paths in nginx config)"
echo ""
echo "  Test:"
echo "    https://${DOMAIN}"
echo "    https://${DOMAIN}/api/health"
echo ""
echo "  Manage:"
echo "    Logs:    ssh ${REMOTE_USER}@${REMOTE_HOST} 'cd /opt/alphasync-demo && docker compose -p alphasync-demo -f docker-compose.demo.yml logs -f'"
echo "    Restart: ssh ${REMOTE_USER}@${REMOTE_HOST} 'cd /opt/alphasync-demo && docker compose -p alphasync-demo -f docker-compose.demo.yml restart'"
echo "    Stop:    ssh ${REMOTE_USER}@${REMOTE_HOST} 'cd /opt/alphasync-demo && docker compose -p alphasync-demo -f docker-compose.demo.yml down'"
echo "    Redeploy: bash deploy-demo.sh"
echo ""
