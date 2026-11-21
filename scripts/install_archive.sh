#!/usr/bin/env bash
#
# Prepare the Raspberry Pi for the archive disk (main-stream clips kept
# on a USB disk that rests between batches).
#
# What it does, once:
#   - installs hdparm and smartmontools;
#   - rewrites the /mnt/cctv line in /etc/fstab so the disk is NOT
#     mounted at boot and the service user may mount and unmount it;
#   - adds a sudoers rule allowing exactly the park and SMART commands
#     on the disk, found by its label "cctv";
#   - makes the system journal persistent (capped at 200 MB) so logs
#     survive a reboot.
#
# Run as the normal user, not with sudo:
#   bash scripts/install_archive.sh
#
# The disk itself was formatted ext4 with the label "cctv" by hand; see
# README.md, section "Archive on the USB disk".

set -euo pipefail


MOUNT_POINT="/mnt/cctv"
DEVICE="/dev/disk/by-label/cctv"
SUDOERS_FILE="/etc/sudoers.d/home-automation-archive"
JOURNAL_CONF="/etc/systemd/journald.conf.d/persistent.conf"
RUN_USER="$(id -un)"


if [[ "${EUID}" -eq 0 ]]; then
    echo "Do not run this script with sudo."
    echo
    echo "Run:"
    echo "  bash scripts/install_archive.sh"
    exit 1
fi


echo
echo "=========================================="
echo " Archive disk setup"
echo "=========================================="
echo

sudo -v


echo "[1/4] Installing hdparm and smartmontools..."

sudo apt-get install -y hdparm smartmontools >/dev/null


echo
echo "[2/4] Updating /etc/fstab (no mount at boot, user may mount)..."

sudo mkdir -p "${MOUNT_POINT}"

if mountpoint -q "${MOUNT_POINT}"; then
    sudo umount "${MOUNT_POINT}"
fi

sudo sed -i "\#[[:space:]]${MOUNT_POINT}[[:space:]]#d" /etc/fstab

echo "LABEL=cctv  ${MOUNT_POINT}  ext4  defaults,noatime,nofail,noauto,user,x-systemd.device-timeout=10  0  2" \
    | sudo tee -a /etc/fstab >/dev/null

sudo systemctl daemon-reload

if [[ -e "${DEVICE}" ]]; then
    # The "user" option makes the mount nosuid,nodev,noexec, which is
    # fine for video files. Make sure the service user owns the root.
    mount "${MOUNT_POINT}"
    sudo chown "${RUN_USER}:${RUN_USER}" "${MOUNT_POINT}"
    umount "${MOUNT_POINT}"
    echo "Mount test OK."
else
    echo "Disk not plugged in right now; fstab is ready for when it is."
fi


echo
echo "[3/4] Allowing the park and SMART commands without a password..."

# In sudoers a comma inside an argument must be escaped.
sudo tee "${SUDOERS_FILE}" >/dev/null <<EOF
${RUN_USER} ALL=(root) NOPASSWD: /usr/sbin/hdparm -y ${DEVICE}
${RUN_USER} ALL=(root) NOPASSWD: /usr/sbin/smartctl -d sat\\,16 -A ${DEVICE}
${RUN_USER} ALL=(root) NOPASSWD: /usr/sbin/smartctl -d sat\\,16 -n standby -i ${DEVICE}
EOF
sudo chmod 0440 "${SUDOERS_FILE}"
sudo visudo -cf "${SUDOERS_FILE}"


echo
echo "[4/4] Making the system journal persistent (200 MB cap)..."

sudo mkdir -p /var/log/journal "$(dirname "${JOURNAL_CONF}")"

sudo tee "${JOURNAL_CONF}" >/dev/null <<EOF
[Journal]
Storage=persistent
SystemMaxUse=200M
EOF

sudo systemctl restart systemd-journald


echo
echo "=========================================="
echo " Archive setup complete"
echo "=========================================="
echo
echo "Turn the archive on in the CCTV tab of the UI, then press"
echo "Stop Recording and Start Recording so the archive recorders start."
