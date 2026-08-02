#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICE_NAME="home-automation.service"
SERVICE_SOURCE="$PROJECT_ROOT/deploy/systemd/$SERVICE_NAME"
SERVICE_DESTINATION="/etc/systemd/system/$SERVICE_NAME"

echo "Installing ${SERVICE_NAME}"

sudo cp "$SERVICE_SOURCE" "$SERVICE_DESTINATION"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo
sudo systemctl status "$SERVICE_NAME" --no-pager