#!/usr/bin/env bash
# Auto-update Posipaka from git without downtime.
# Runs via systemd timer every 5 minutes.
# If no changes — does nothing. If changes — pull + restart.

set -euo pipefail

REPO_DIR="/opt/posipaka"
LOG_TAG="posipaka-autoupdate"

log() { logger -t "$LOG_TAG" "$*"; }

cd "$REPO_DIR" || { log "ERROR: $REPO_DIR not found"; exit 1; }

# Fetch latest without merging
git fetch origin main --quiet 2>/dev/null || { log "git fetch failed"; exit 0; }

# Check if there are new commits
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # Nothing to update
fi

log "Update available: $LOCAL -> $REMOTE"

# Sync to remote (handles both fast-forward and force push)
if ! git pull origin main --ff-only --quiet 2>/dev/null; then
    log "Fast-forward failed, resetting to origin/main"
    git reset --hard origin/main
fi

# Install new dependencies if pyproject.toml changed
if git diff "$LOCAL" "$REMOTE" --name-only | grep -q "pyproject.toml"; then
    log "pyproject.toml changed, reinstalling dependencies..."
    "$REPO_DIR/.venv/bin/pip" install -e ".[telegram]" --quiet 2>/dev/null || true
fi

# Restart service
log "Restarting posipaka..."
systemctl restart posipaka

# Wait for health check
for i in $(seq 1 15); do
    if curl -sf http://localhost:8080/api/v1/health > /dev/null 2>&1; then
        NEW_REV=$(git rev-parse --short HEAD)
        log "Update complete: $NEW_REV — healthy"
        exit 0
    fi
    sleep 2
done

log "WARNING: health check failed after update, service may need attention"
# auto-update test 1774351130
