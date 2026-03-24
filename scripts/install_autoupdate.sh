#!/usr/bin/env bash
# Install auto-update systemd timer for Posipaka.
# Usage: sudo bash scripts/install_autoupdate.sh

set -euo pipefail

SCRIPT_DIR="/opt/posipaka/scripts"

# Make executable
chmod +x "$SCRIPT_DIR/auto_update.sh"

# Create systemd service (oneshot — runs and exits)
cat > /etc/systemd/system/posipaka-update.service << 'EOF'
[Unit]
Description=Posipaka Auto-Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/posipaka/scripts/auto_update.sh
WorkingDirectory=/opt/posipaka
Environment=HOME=/root
EOF

# Create systemd timer (every 5 minutes)
cat > /etc/systemd/system/posipaka-update.timer << 'EOF'
[Unit]
Description=Posipaka Auto-Update Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable posipaka-update.timer
systemctl start posipaka-update.timer

echo "[posipaka] Auto-update timer installed (every 5 min)"
echo "[posipaka] Check status: systemctl list-timers posipaka-update"
echo "[posipaka] View logs: journalctl -t posipaka-autoupdate"
