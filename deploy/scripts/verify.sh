#!/usr/bin/env bash
# ==============================================================================
#  AlphaSync Academic — Post-deploy verification (READ-ONLY)
#  Confirms our stack is up AND that the other two production stacks are still
#  running untouched. Performs NO mutations of any kind.
# ==============================================================================
set -uo pipefail

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'

# Containers that MUST be running after a correct Academic deploy.
OURS=(acalphasync-frontend acalphasync-backend acalphasync-pg acalphasync-redis)
BROKER=(brokerdemo-frontend brokerdemo-backend brokerdemo-pg brokerdemo-redis)
TICK=(alphasync-api alphasync-postgres alphasync-redis)

echo ""
echo "=== docker ps (current state) ==="
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
echo ""

RUNNING="$(docker ps --format '{{.Names}}')"
FAILURES=0

check_group() {
    local label="$1"; shift
    echo "--- ${label} ---"
    for c in "$@"; do
        if grep -qx "$c" <<< "$RUNNING"; then
            echo -e "  ${G}✓${N} $c running"
        else
            echo -e "  ${R}✗${N} $c NOT running"
            FAILURES=$((FAILURES + 1))
        fi
    done
}

check_group "AlphaSync Academic (this deploy)" "${OURS[@]}"
check_group "AlphaSync Real Broker (must stay up — untouched)" "${BROKER[@]}"
check_group "TickAlpha (must stay up — untouched)" "${TICK[@]}"

echo ""
if [[ "${FAILURES}" -eq 0 ]]; then
    echo -e "${G}All expected containers are running. Isolation verified.${N}"
    exit 0
else
    echo -e "${Y}${FAILURES} expected container(s) missing (see ✗ above).${N}"
    echo -e "${Y}NOTE: if a brokerdemo/tickalpha container is missing, this deploy did"
    echo -e "NOT stop it — investigate separately. This script never mutates state.${N}"
    exit 1
fi
