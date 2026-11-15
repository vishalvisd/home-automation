#!/usr/bin/env bash
#
# Install go2rtc on the Raspberry Pi for live view in the browser.
#
# go2rtc takes each camera's RTSP stream and serves it to the browser
# over WebRTC or MSE without re-encoding. It runs as its own systemd
# service. The home-automation backend writes its config file
# (runtime/go2rtc.yaml) from the camera list and restarts the service
# whenever that file changes, which needs the sudoers rule added below.
#
# Run once, as the normal user (not with sudo):
#   bash scripts/install_go2rtc.sh
#
# Safe to run again to upgrade the pinned version.

set -euo pipefail


GO2RTC_VERSION="v1.9.15"
GO2RTC_URL="https://github.com/AlexxIT/go2rtc/releases/download/${GO2RTC_VERSION}/go2rtc_linux_arm64"
GO2RTC_BINARY="/usr/local/bin/go2rtc"

SERVICE_NAME="go2rtc"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SUDOERS_FILE="/etc/sudoers.d/home-automation-go2rtc"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${PROJECT_DIR}/runtime"
CONFIG_FILE="${RUNTIME_DIR}/go2rtc.yaml"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"


if [[ "${EUID}" -eq 0 ]]; then
    echo "Do not run this script with sudo."
    echo
    echo "Run:"
    echo "  bash scripts/install_go2rtc.sh"
    exit 1
fi

if [[ "$(uname -m)" != "aarch64" ]]; then
    echo "ERROR: this script installs the 64-bit ARM build and this"
    echo "machine is $(uname -m)."
    exit 1
fi


echo
echo "=========================================="
echo " go2rtc ${GO2RTC_VERSION} install"
echo "=========================================="
echo

sudo -v


echo "[1/4] Downloading go2rtc..."

TMP_FILE="$(mktemp)"
trap 'rm -f "${TMP_FILE}"' EXIT

curl -fsSL -o "${TMP_FILE}" "${GO2RTC_URL}"
chmod +x "${TMP_FILE}"

# Make sure it is a working binary for this machine before installing.
"${TMP_FILE}" --version

sudo install -m 0755 -o root -g root "${TMP_FILE}" "${GO2RTC_BINARY}"
echo "Installed ${GO2RTC_BINARY}"


echo
echo "[2/4] Writing a starting config (the backend rewrites it)..."

mkdir -p "${RUNTIME_DIR}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
    cat > "${CONFIG_FILE}" <<EOF
api:
  listen: ":1984"
  origin: "*"
rtsp:
  listen: ""
streams:
EOF
fi


echo
echo "[3/4] Installing the systemd service..."

sudo tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=go2rtc live view for Home Automation
Wants=network-online.target
After=network-online.target

[Service]
Type=simple

User=${RUN_USER}
Group=${RUN_GROUP}

WorkingDirectory=${RUNTIME_DIR}

ExecStart=${GO2RTC_BINARY} -config ${CONFIG_FILE}

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Let the backend (running as ${RUN_USER}) restart go2rtc, and only that.
echo "${RUN_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart ${SERVICE_NAME}" \
    | sudo tee "${SUDOERS_FILE}" >/dev/null
sudo chmod 0440 "${SUDOERS_FILE}"
sudo visudo -cf "${SUDOERS_FILE}"

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"


echo
echo "[4/4] Asking the backend to write the camera list..."

sleep 2

if curl --fail --silent --show-error --max-time 10 \
    -X POST http://127.0.0.1:8000/api/cameras/live/sync >/dev/null; then
    echo "Camera list written and go2rtc restarted."
else
    echo "Backend not reachable; it will write the config on its next start."
fi


echo
echo "=========================================="
echo " go2rtc install complete"
echo "=========================================="
echo
echo "Live view API: http://$(hostname -I | awk '{print $1}'):1984/"
echo
sudo systemctl --no-pager --full status "${SERVICE_NAME}" || true
