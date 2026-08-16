#!/usr/bin/env bash

set -euo pipefail


SERVICE_NAME="home-automation"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"
USER_HOME="${HOME}"

UV_BIN="${USER_HOME}/.local/bin/uv"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"


if [[ "${EUID}" -eq 0 ]]; then
    echo "Do not run this script with sudo."
    echo
    echo "Run:"
    echo "  bash scripts/setup_pi.sh"
    exit 1
fi


echo
echo "=========================================="
echo " Home Automation Raspberry Pi Setup"
echo "=========================================="
echo
echo "Project: ${PROJECT_DIR}"
echo "User:    ${RUN_USER}"
echo


echo "[1/5] Installing operating-system packages..."

sudo apt-get update

sudo apt-get install -y \
    ca-certificates \
    curl \
    git \
    gcc \
    pkg-config \
    python3-dev \
    swig \
    liblgpio-dev \
    libcairo2-dev \
    gobject-introspection \
    libgirepository-2.0-dev \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly


echo
echo "[2/5] Installing uv..."

if [[ ! -x "${UV_BIN}" ]]; then
    curl -LsSf https://astral.sh/uv/install.sh \
        | env UV_INSTALL_DIR="${USER_HOME}/.local/bin" sh
else
    echo "uv already installed: ${UV_BIN}"
fi

"${UV_BIN}" --version


echo
echo "[3/5] Creating Python environment..."

cd "${PROJECT_DIR}"

"${UV_BIN}" sync --frozen


echo
echo "[4/5] Checking CCTV GStreamer components..."

GSTREAMER_ELEMENTS=(
    souphttpsrc
    multipartdemux
    jpegdec
    videorate
    videoconvert
    x264enc
    h264parse
    splitmuxsink
    mpegtsmux
)

for element in "${GSTREAMER_ELEMENTS[@]}"; do
    if ! gst-inspect-1.0 "${element}" >/dev/null 2>&1; then
        echo "ERROR: Missing GStreamer element: ${element}"
        exit 1
    fi
done

echo "GStreamer components OK."


echo
echo "[5/5] Installing boot service..."

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

TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF


sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"


echo
echo "=========================================="
echo " Setup complete"
echo "=========================================="
echo
echo "Home Automation is now running."
echo
echo "It will start automatically whenever"
echo "the Raspberry Pi boots."
echo
echo "Service status:"
sudo systemctl --no-pager --full status "${SERVICE_NAME}" || true