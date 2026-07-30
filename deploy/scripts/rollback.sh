#!/usr/bin/env bash
# ==============================================================================
#  AlphaSync Academic — Rollback (this application ONLY)
#
#  Modes:
#    (default)  re-tag & recreate from images recorded by update.sh
#    --git      reset to the commit recorded in the snapshot, then rebuild
#
#  SAFETY: project "acalphasync" only. Data volumes are always preserved.
#  No prune, no rm, no stop of other apps, no down, no --remove-orphans.
# ==============================================================================
set -euo pipefail

APP_DIR="/opt/apps/alphasync-academic"
PROJECT="acalphasync"
MODE="${1:-images}"
SNAP=".rollback/last-good.txt"

G='\033[0;32m'; C='\033[0;36m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
info() { echo -e "${C}>>>${N} $*"; }
ok()   { echo -e "${G}[OK]${N} $*"; }
warn() { echo -e "${Y}[!]${N}  $*"; }
fail() { echo -e "${R}[FAIL]${N} $*"; exit 1; }

cd "${APP_DIR}" || fail "Missing ${APP_DIR}"
[[ -f "${SNAP}" ]] || fail "No snapshot at ${SNAP}. Run an update first."

if [[ "${MODE}" == "--git" ]]; then
    COMMIT=$(grep '^commit=' "${SNAP}" | cut -d= -f2)
    [[ -n "${COMMIT}" ]] || fail "No commit recorded in snapshot."
    info "Resetting to ${COMMIT} and rebuilding..."
    git reset --hard "${COMMIT}"
    docker compose -p "${PROJECT}" build
    docker compose -p "${PROJECT}" up -d
    ok "Rolled back to commit ${COMMIT}."
    "$(dirname "$0")/verify.sh" || true
    exit 0
fi

# ── Image rollback ────────────────────────────────────────────────────────────
info "Re-tagging services to their last-good image IDs:"
cat "${SNAP}"
while IFS= read -r line; do
    [[ "${line}" =~ ^# ]] && continue
    [[ "${line}" =~ ^commit= ]] && continue
    [[ -z "${line}" ]] && continue
    svc="${line%%=*}"
    id="${line#*=}"
    [[ -z "${id}" ]] && { warn "No saved image for ${svc}; skipping."; continue; }
    info "Re-tagging ${id} → acalphasync-${svc}:latest"
    docker tag "${id}" "acalphasync-${svc}:latest" || warn "Could not re-tag ${svc} (image gone?)."
done < "${SNAP}"

info "Recreating containers from rolled-back images (no rebuild)..."
docker compose -p "${PROJECT}" up -d --no-build

info "Waiting for backend health..."
for i in $(seq 1 30); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' acalphasync-backend 2>/dev/null || echo "unknown")
    [[ "${STATUS}" == "healthy" ]] && { ok "Backend healthy after rollback."; break; }
    echo "  waiting... (${i}/30, ${STATUS})"; sleep 3
done

ok "Rollback complete. Data volumes preserved."
"$(dirname "$0")/verify.sh" || true
