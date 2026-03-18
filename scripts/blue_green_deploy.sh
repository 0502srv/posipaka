#!/usr/bin/env bash
# Blue-Green Deployment для Posipaka
# Використання: ./blue_green_deploy.sh [blue|green]
set -euo pipefail

APP_NAME="posipaka"
DEPLOY_DIR="/opt/${APP_NAME}"
BLUE_DIR="${DEPLOY_DIR}/blue"
GREEN_DIR="${DEPLOY_DIR}/green"
CURRENT_LINK="${DEPLOY_DIR}/current"
HEALTH_URL="http://localhost:8080/api/v1/health"
HEALTH_TIMEOUT=30
SMOKE_TIMEOUT=60

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Визначити поточний та новий слот
if [ -L "$CURRENT_LINK" ]; then
    CURRENT=$(readlink "$CURRENT_LINK" | xargs basename)
else
    CURRENT="none"
fi

if [ "$CURRENT" = "blue" ]; then
    NEW_SLOT="green"
    NEW_DIR="$GREEN_DIR"
else
    NEW_SLOT="blue"
    NEW_DIR="$BLUE_DIR"
fi

log "Current: ${CURRENT}, deploying to: ${NEW_SLOT}"

# 1. Підготувати новий слот
mkdir -p "$NEW_DIR"
log "Pulling latest code..."
if [ -d "${NEW_DIR}/.git" ]; then
    cd "$NEW_DIR" && git pull origin main
else
    git clone --depth 1 https://github.com/0502srv/posipaka.git "$NEW_DIR"
fi

# 2. Встановити залежності
cd "$NEW_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]" --quiet
deactivate

# 3. Переключити symlink
log "Switching to ${NEW_SLOT}..."
ln -sfn "$NEW_DIR" "$CURRENT_LINK"

# 4. Перезапустити сервіс
log "Restarting service..."
sudo systemctl restart posipaka

# 5. Health check
log "Waiting for health check..."
for i in $(seq 1 $HEALTH_TIMEOUT); do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        log "Health check passed after ${i}s"
        break
    fi
    if [ "$i" -eq "$HEALTH_TIMEOUT" ]; then
        log "ERROR: Health check failed after ${HEALTH_TIMEOUT}s! Rolling back..."
        # Rollback
        if [ "$CURRENT" != "none" ]; then
            ln -sfn "${DEPLOY_DIR}/${CURRENT}" "$CURRENT_LINK"
            sudo systemctl restart posipaka
            log "Rolled back to ${CURRENT}"
        fi
        exit 1
    fi
    sleep 1
done

# 6. Smoke tests
log "Running smoke tests..."
if [ -f "${NEW_DIR}/tests/smoke/test_smoke.py" ]; then
    cd "$NEW_DIR"
    source .venv/bin/activate
    timeout "$SMOKE_TIMEOUT" python -m pytest tests/smoke/ -v --timeout=30 || {
        log "ERROR: Smoke tests failed! Rolling back..."
        if [ "$CURRENT" != "none" ]; then
            ln -sfn "${DEPLOY_DIR}/${CURRENT}" "$CURRENT_LINK"
            sudo systemctl restart posipaka
            log "Rolled back to ${CURRENT}"
        fi
        exit 1
    }
    deactivate
fi

log "Deploy to ${NEW_SLOT} completed successfully!"
