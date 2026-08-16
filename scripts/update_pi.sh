#!/usr/bin/env bash

set -euo pipefail


SERVICE_NAME="home-automation"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${HOME}/.local/bin/uv"


if [[ "${EUID}" -eq 0 ]]; then
    echo "Do not run this script with sudo."
    echo
    echo "Run:"
    echo "  bash scripts/update_pi.sh"
    exit 1
fi


if [[ ! -x "${UV_BIN}" ]]; then
    echo "ERROR: uv not found at ${UV_BIN}"
    echo "Run the initial setup first:"
    echo "  bash scripts/setup_pi.sh"
    exit 1
fi


echo
echo "=========================================="
echo " Home Automation Update"
echo "=========================================="
echo


# Get sudo authentication before changing anything.
sudo -v


echo "[1/4] Pulling latest code..."

cd "${PROJECT_DIR}"

git pull --ff-only


echo
echo "[2/4] Synchronizing Python dependencies..."

"${UV_BIN}" sync --frozen


echo
echo "[3/4] Restarting Home Automation..."

sudo systemctl restart "${SERVICE_NAME}"

sleep 2


echo
echo "[4/4] Verifying service..."

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo
    echo "ERROR: Home Automation service is not running."
    echo
    sudo journalctl \
        -u "${SERVICE_NAME}" \
        -n 100 \
        --no-pager

    exit 1
fi


if ! curl \
    --fail \
    --silent \
    --show-error \
    --max-time 5 \
    http://127.0.0.1:8000/health \
    >/dev/null; then

    echo
    echo "ERROR: Home Automation health check failed."
    echo
    sudo journalctl \
        -u "${SERVICE_NAME}" \
        -n 100 \
        --no-pager

    exit 1
fi


echo
echo "=========================================="
echo " Update complete"
echo "=========================================="
echo
echo "Git revision:"
git rev-parse --short HEAD
echo
echo "Home Automation is running normally."