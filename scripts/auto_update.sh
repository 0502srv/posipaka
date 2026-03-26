#!/usr/bin/env bash
# Auto-update Posipaka from git with preflight validation.
# Runs via systemd timer every 5 minutes.
# If no changes — does nothing. If changes — preflight → pull → restart.
# If preflight fails — does NOT update, service stays on current version.

set -euo pipefail

REPO_DIR="/opt/posipaka"
LOG_TAG="posipaka-autoupdate"
PREFLIGHT_DIR="/tmp/posipaka-preflight"
VENV="$REPO_DIR/.venv"

log() { logger -t "$LOG_TAG" "$*"; }

cd "$REPO_DIR" || { log "ERROR: $REPO_DIR not found"; exit 1; }

# ── Fetch latest without merging ─────────────────────────────────────────────
git fetch origin main --quiet 2>/dev/null || { log "git fetch failed"; exit 0; }

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # Nothing to update
fi

log "Update available: ${LOCAL:0:7} -> ${REMOTE:0:7}"

# ── Preflight validation in temporary worktree ───────────────────────────────
# Test the new code BEFORE applying it to the live installation.
# If preflight fails — skip this update, try again on next timer tick.

cleanup_preflight() {
    if [ -d "$PREFLIGHT_DIR" ]; then
        git worktree remove "$PREFLIGHT_DIR" --force 2>/dev/null || rm -rf "$PREFLIGHT_DIR"
    fi
}

# Clean up any stale preflight from previous run
cleanup_preflight

log "Running preflight validation..."

# Create temporary worktree with the new code
if ! git worktree add "$PREFLIGHT_DIR" origin/main --detach --quiet 2>/dev/null; then
    log "WARNING: git worktree failed, falling back to direct update"
else
    PREFLIGHT_OK=true

    # Check 1: Python syntax — all .py files must parse
    if ! "$VENV/bin/python" -c "
import py_compile, pathlib, sys
errors = []
for f in pathlib.Path('$PREFLIGHT_DIR/posipaka').rglob('*.py'):
    try:
        py_compile.compile(str(f), doraise=True)
    except py_compile.PyCompileError as e:
        errors.append(str(e))
if errors:
    print('Syntax errors:', *errors[:3], sep='\n  ')
    sys.exit(1)
" 2>/dev/null; then
        log "PREFLIGHT FAILED: Python syntax errors in new code"
        PREFLIGHT_OK=false
    fi

    # Check 2: Critical imports resolve
    if [ "$PREFLIGHT_OK" = true ]; then
        if ! PYTHONPATH="$PREFLIGHT_DIR" "$VENV/bin/python" -c "
from posipaka.core.agent import Agent
from posipaka.core.llm import LLMClient
from posipaka.core.agent_types import AgentStatus
" 2>/dev/null; then
            log "PREFLIGHT FAILED: critical imports broken in new code"
            PREFLIGHT_OK=false
        fi
    fi

    # Check 3: Unit tests (only if pytest is installed)
    if [ "$PREFLIGHT_OK" = true ] && "$VENV/bin/python" -c "import pytest" 2>/dev/null; then
        if ! PYTHONPATH="$PREFLIGHT_DIR" "$VENV/bin/python" -m pytest \
            "$PREFLIGHT_DIR/tests/unit/test_settings.py" \
            "$PREFLIGHT_DIR/tests/unit/test_tools.py" \
            -x -q --timeout=30 2>/dev/null; then
            log "PREFLIGHT FAILED: unit tests failed on new code"
            PREFLIGHT_OK=false
        fi
    fi

    # Cleanup worktree
    cleanup_preflight

    if [ "$PREFLIGHT_OK" = false ]; then
        log "Skipping update — preflight validation failed. Will retry on next tick."
        exit 0
    fi

    log "Preflight passed"
fi

# ── Apply update ─────────────────────────────────────────────────────────────
# Save current commit for rollback
echo "$LOCAL" > "$REPO_DIR/.last_good_commit"

if ! git pull origin main --ff-only --quiet 2>/dev/null; then
    log "Fast-forward failed, resetting to origin/main"
    git reset --hard origin/main
fi

# Install new dependencies if pyproject.toml changed
if git diff "$LOCAL" "$REMOTE" --name-only | grep -q "pyproject.toml"; then
    log "pyproject.toml changed, reinstalling dependencies..."
    "$VENV/bin/pip" install -e ".[telegram]" --quiet 2>/dev/null || true
fi

# ── Restart service ──────────────────────────────────────────────────────────
log "Restarting posipaka..."
systemctl restart posipaka

# ── Health check with auto-rollback ──────────────────────────────────────────
for i in $(seq 1 15); do
    if curl -sf http://localhost:8080/api/v1/health > /dev/null 2>&1; then
        NEW_REV=$(git rev-parse --short HEAD)
        log "Update complete: $NEW_REV — healthy"
        exit 0
    fi
    sleep 2
done

# Health check failed — rollback to previous commit
log "WARNING: health check failed after update, rolling back to ${LOCAL:0:7}"
git reset --hard "$LOCAL"

# Reinstall deps in case rollback changed them
if git diff "$LOCAL" "$REMOTE" --name-only | grep -q "pyproject.toml"; then
    "$VENV/bin/pip" install -e ".[telegram]" --quiet 2>/dev/null || true
fi

systemctl restart posipaka

# Verify rollback health
for i in $(seq 1 10); do
    if curl -sf http://localhost:8080/api/v1/health > /dev/null 2>&1; then
        log "Rollback successful, running ${LOCAL:0:7}"
        exit 0
    fi
    sleep 2
done

log "CRITICAL: rollback also failed, manual intervention needed"
exit 1
