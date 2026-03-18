#!/usr/bin/env bash
# Rollback до попереднього слоту (Phase 41)
set -euo pipefail

APP_NAME="posipaka"
DEPLOY_DIR="/opt/${APP_NAME}"
CURRENT_LINK="${DEPLOY_DIR}/current"
HEALTH_URL="http://localhost:8080/api/v1/health"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [ ! -L "$CURRENT_LINK" ]; then
    log "ERROR: No current deployment found"
    exit 1
fi

CURRENT=$(readlink "$CURRENT_LINK" | xargs basename)
if [ "$CURRENT" = "blue" ]; then
    ROLLBACK_TO="green"
else
    ROLLBACK_TO="blue"
fi

ROLLBACK_DIR="${DEPLOY_DIR}/${ROLLBACK_TO}"
if [ ! -d "$ROLLBACK_DIR" ]; then
    log "ERROR: Rollback target ${ROLLBACK_TO} does not exist"
    exit 1
fi

log "Rolling back from ${CURRENT} to ${ROLLBACK_TO}..."
ln -sfn "$ROLLBACK_DIR" "$CURRENT_LINK"
sudo systemctl restart posipaka

# Перевірка
for i in $(seq 1 30); do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        log "Rollback successful! Now running: ${ROLLBACK_TO}"
        exit 0
    fi
    sleep 1
done

log "ERROR: Rollback health check failed!"
exit 1
