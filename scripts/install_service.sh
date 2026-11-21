#!/usr/bin/env bash
#
# Write (or rewrite) the systemd unit for the backend and restart it.
#
# setup_pi.sh calls this on a fresh Pi. Run it on its own whenever the
# unit text below changes, so an existing Pi gets the same unit a new
# one would:
#   bash scripts/install_service.sh
#
# Run as the normal user, not with sudo.

set -euo pipefail


SERVICE_NAME="home-automation"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"
USER_HOME="${HOME}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"


if [[ "${EUID}" -eq 0 ]]; then
    echo "Do not run this script with sudo."
    echo
    echo "Run:"
    echo "  bash scripts/install_service.sh"
    exit 1
fi


echo "Installing ${SERVICE_FILE}..."

sudo tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Home Automation
Wants=network-online.target
After=network-online.target

[Service]
Type=simple

User=${RUN_USER}
Group=${RUN_GROUP}

WorkingDirectory=${PROJECT_DIR}

Environment=HOME=${USER_HOME}
Environment=PYTHONUNBUFFERED=1

ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn home_automation.api.app:app --host 0.0.0.0 --port 8000

Restart=always
RestartSec=5

# Only the Python process gets the stop signal. The backend then stops
# each ffmpeg itself with one interrupt, so ffmpeg can finish writing
# the clip it is on. With the default KillMode systemd signals ffmpeg
# too, and a second signal makes ffmpeg abort mid-write.
KillMode=mixed

TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF

# Remove any drop-in left from earlier hand edits; the unit above is
# the only source of truth.
sudo rm -rf "/etc/systemd/system/${SERVICE_NAME}.service.d"

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "Service installed and restarted."
systemctl --no-pager --full status "${SERVICE_NAME}" | head -5 || true
