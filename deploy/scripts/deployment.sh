#!/usr/bin/env bash
# ==============================================================================
#  AlphaSync Academic — First-time / full deployment
#  Operates ONLY inside /opt/apps/alphasync-academic, project "acalphasync".
#
#  SAFETY (hard guarantees):
#    - Never stops/restarts/recreates/removes any other application.
#    - No `docker system/volume/network prune`, no `docker rm`, no `docker stop`.
#    - No `compose down`, no `--remove-orphans`.
#    - Aborts if ports 3004/8004 are occupied — never kills another app.
# ==============================================================================
set -euo pipefail

APP_DIR="/opt/apps/alphasync-academic"
PROJECT="acalphasync"
FRONTEND_PORT=3004
BACKEND_PORT=8004

G='\033[0;32m'; C='\033[0;36m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
info() { echo -e "${C}>>>${N} $*"; }
ok()   { echo -e "${G}[OK]${N} $*"; }
warn() { echo -e "${Y}[!]${N}  $*"; }
fail() { echo -e "${R}[FAIL]${N} $*"; exit 1; }

cd "${APP_DIR}" || fail "Missing ${APP_DIR}."

# ── Pre-flight ────────────────────────────────────────────────────────────────
[[ -f docker-compose.yml ]] || fail "docker-compose.yml not found in ${APP_DIR}"
[[ -f .env ]] || fail ".env not found. Copy .env.academic.example → .env and fill secrets."
command -v docker >/dev/null || fail "docker not installed."

info "Ensuring runtime directories exist..."
mkdir -p uploads logs
ok "Directories ready."

# ── MANDATORY port validation — abort, never kill ────────────────────────────
info "Validating ports ${FRONTEND_PORT} and ${BACKEND_PORT} are free..."
ss -tlnp | grep -q ":${FRONTEND_PORT} " && (docker ps --format '{{.Names}} {{.Ports}}' | grep -q "${PROJECT}.*:${FRONTEND_PORT}->" && warn "Port ${FRONTEND_PORT} already held by our own ${PROJECT} stack — safe to recreate." || fail "Port ${FRONTEND_PORT} is occupied by another application. ABORTING.") || ok "Port ${FRONTEND_PORT} is free."
ss -tlnp | grep -q ":${BACKEND_PORT} " && (docker ps --format '{{.Names}} {{.Ports}}' | grep -q "${PROJECT}.*:${BACKEND_PORT}->" && warn "Port ${BACKEND_PORT} already held by our own ${PROJECT} stack — safe to recreate." || fail "Port ${BACKEND_PORT} is occupied by another application. ABORTING.") || ok "Port ${BACKEND_PORT} is free."

# ── Build & start (scoped strictly to this project) ──────────────────────────
info "Building images (project=${PROJECT})..."
docker compose -p "${PROJECT}" build

info "Starting containers (no down, no remove-orphans)..."
docker compose -p "${PROJECT}" up -d

# ── Health wait ───────────────────────────────────────────────────────────────
info "Waiting for backend health..."
for i in $(seq 1 40); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' acalphasync-backend 2>/dev/null || echo "unknown")
    [[ "${STATUS}" == "healthy" ]] && { ok "Backend healthy."; break; }
    echo "  waiting... (${i}/40, ${STATUS})"; sleep 3
    [[ "${i}" -eq 40 ]] && { warn "Backend not healthy in time. Recent logs:"; docker compose -p "${PROJECT}" logs --tail=40 backend; }
done

# ── Post-deploy verification ─────────────────────────────────────────────────
"$(dirname "$0")/verify.sh" || warn "Verification reported issues — review above."

echo ""
ok "AlphaSync Academic deployed (project=${PROJECT})."
echo "  Frontend : http://127.0.0.1:${FRONTEND_PORT}"
echo "  Backend  : http://127.0.0.1:${BACKEND_PORT}/api/health"
echo "  Domain   : https://ac.alphasync.app"
