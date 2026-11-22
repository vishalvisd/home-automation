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


# The app needs a few seconds after the service starts before it
# answers. Ask once a second, for up to a minute, before calling it
# a failure.
HEALTH_URL="http://127.0.0.1:8000/health"
HEALTH_WAIT_SECONDS=60
healthy=0

for _ in $(seq 1 "${HEALTH_WAIT_SECONDS}"); do
    if curl \
        --fail \
        --silent \
        --max-time 5 \
        "${HEALTH_URL}" \
        >/dev/null 2>&1; then

        healthy=1
        break
    fi

    sleep 1
done


if [[ "${healthy}" -ne 1 ]]; then
    echo
    echo "ERROR: Home Automation did not answer on ${HEALTH_URL}"
    echo "       within ${HEALTH_WAIT_SECONDS} seconds."
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