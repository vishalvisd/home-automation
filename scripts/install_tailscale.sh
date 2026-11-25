#!/usr/bin/env bash
#
# Open the Pi's page to the internet through Tailscale Funnel.
#
# Tailscale runs on the Pi only. The Pi keeps a connection open to
# Tailscale's relay, and a browser anywhere reaches the page through
# that relay at https://<name>.<tailnet>.ts.net. Nothing is opened on
# the router and nothing is installed on a phone.
#
# Two things become public, both on port 443 of that address:
#   /         the Pi's page and API (port 8000)
#   /api/ws   go2rtc's video connection only, for live view. The rest
#             of go2rtc (port 1984) stays inside the home network.
#
# There is no login on the page: whoever has the address can use it.
# That is the owner's choice for now (docs/decisions.md).
#
# Run once, as the normal user (not with sudo):
#   bash scripts/install_tailscale.sh
#
# Safe to run again. To close the page to the internet again:
#   bash scripts/install_tailscale.sh off

set -euo pipefail


# The first part of the public address. It is listed in a public
# register of HTTPS certificates, so it must not say anything private.
TS_HOSTNAME="visd-ha"

BACKEND_URL="http://127.0.0.1:8000"
GO2RTC_WS_URL="http://127.0.0.1:1984/api/ws"
PUBLIC_PORT="443"


if [[ "${EUID}" -eq 0 ]]; then
    echo "Do not run this script with sudo."
    echo
    echo "Run:"
    echo "  bash scripts/install_tailscale.sh"
    exit 1
fi

sudo -v


if [[ "${1:-}" == "off" ]]; then
    echo "Closing the page to the internet..."
    sudo tailscale funnel reset
    echo
    sudo tailscale funnel status || true
    echo
    echo "Done. Tailscale itself stays installed and signed in."
    echo "Run this script again without 'off' to open the page again."
    exit 0
fi


echo
echo "=========================================="
echo " Tailscale Funnel install"
echo "=========================================="
echo


echo "[1/4] Installing Tailscale..."

if command -v tailscale >/dev/null 2>&1; then
    echo "Already installed: $(tailscale version | head -n 1)"
else
    # shellcheck disable=SC1091
    . /etc/os-release

    case "${ID:-}" in
        debian|raspbian) ;;
        *)
            echo "ERROR: this script knows Debian and Raspbian only," \
                 "and this system says '${ID:-unknown}'."
            exit 1
            ;;
    esac

    REPO_URL="https://pkgs.tailscale.com/stable/${ID}/${VERSION_CODENAME}"

    sudo mkdir -p --mode=0755 /usr/share/keyrings

    curl -fsSL "${REPO_URL}.noarmor.gpg" \
        | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null

    curl -fsSL "${REPO_URL}.tailscale-keyring.list" \
        | sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null

    sudo apt-get update
    sudo apt-get install -y tailscale
fi

sudo systemctl enable --now tailscaled


echo
echo "[2/4] Joining the Pi to your Tailscale account..."

# accept-dns=false: the Pi keeps using the router for name lookups, so
# recording and uploads are not touched by anything set in Tailscale.
if sudo tailscale status >/dev/null 2>&1; then
    echo "Already signed in. Setting the name to ${TS_HOSTNAME}."
    sudo tailscale set --accept-dns=false --hostname="${TS_HOSTNAME}"
else
    echo "Open the link printed below in a browser and sign in."
    echo "This script continues by itself once you have."
    echo
    sudo tailscale up --accept-dns=false --hostname="${TS_HOSTNAME}"
fi


echo
echo "[3/4] Opening the page and the video connection..."
echo "If Tailscale prints a link here, Funnel is not yet allowed for"
echo "your account: open the link, approve it, and the script continues."
echo

# Start from nothing, so a rule left by an earlier run cannot stay.
# What was there is printed first, in case it was set by hand.
echo "Rules before this run (replaced by the two below):"
sudo tailscale funnel status || true
echo

sudo tailscale funnel reset

sudo tailscale funnel --bg --https="${PUBLIC_PORT}" "${BACKEND_URL}"

sudo tailscale funnel --bg --https="${PUBLIC_PORT}" \
    --set-path=/api/ws "${GO2RTC_WS_URL}"


echo
echo "[4/4] Result"
echo

sudo tailscale funnel status

echo
echo "=========================================="
echo " Tailscale Funnel install complete"
echo "=========================================="
echo
echo "The https address above is the Pi's page, from anywhere."
echo "A new address can take up to ten minutes to start working."
echo
echo "One step is left, on Tailscale's own site (login.tailscale.com,"
echo "Machines): open the menu at the right of '${TS_HOSTNAME}' and"
echo "choose 'Disable key expiry'. Without it the Pi is signed out"
echo "after 180 days and the address stops working."
