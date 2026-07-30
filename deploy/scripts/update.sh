#!/usr/bin/env bash
# ==============================================================================
#  AlphaSync Academic — Update to latest main
#  Steps (identical to the GitHub Action):
#    git fetch → git reset --hard origin/main → docker compose build → up -d
#
#  SAFETY: project "acalphasync" only. No prune, no rm, no stop, no down,
#  no --remove-orphans. Snapshots current images for rollback.sh first.
# ==============================================================================
set -euo pipefail

APP_DIR="/opt/apps/alphasync-academic"
PROJECT="acalphasync"

G='\033[0;32m'; C='\033[0;36m'; R='\033[0;31m'; N='\033[0m'
info() { echo -e "${C}>>>${N} $*"; }
ok()   { echo -e "${G}[OK]${N} $*"; }
fail() { echo -e "${R}[FAIL]${N} $*"; exit 1; }

cd "${APP_DIR}" || fail "Missing ${APP_DIR}"
[[ -f .env ]] || fail ".env not found."

# ── Snapshot current image IDs for rollback ──────────────────────────────────
mkdir -p .rollback
info "Snapshotting current images + commit for rollback..."
{
    echo "# saved $(date -u +%FT%TZ)"
    echo "commit=$(git rev-parse HEAD)"
    for svc in frontend backend; do
        ID=$(docker inspect --format='{{.Image}}' "acalphasync-${svc}" 2>/dev/null || echo "")
        echo "${svc}=${ID}"
    done
} > .rollback/last-good.txt
ok "Snapshot saved."

# ── Pull latest code (exactly the CI steps) ──────────────────────────────────
info "git fetch..."
git fetch origin
info "git reset --hard origin/main..."
git reset --hard origin/main

# ── Rebuild + restart (scoped to this project) ───────────────────────────────
info "docker compose build..."
docker compose -p "${PROJECT}" build
info "docker compose up -d..."
docker compose -p "${PROJECT}" up -d

# ── Health check ─────────────────────────────────────────────────────────────
info "Waiting for backend health..."
for i in $(seq 1 40); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' acalphasync-backend 2>/dev/null || echo "unknown")
    [[ "${STATUS}" == "healthy" ]] && { ok "Backend healthy."; break; }
    echo "  waiting... (${i}/40, ${STATUS})"; sleep 3
    [[ "${i}" -eq 40 ]] && fail "Backend unhealthy after update. Run scripts/rollback.sh."
done

"$(dirname "$0")/verify.sh" || true
ok "Update complete."
