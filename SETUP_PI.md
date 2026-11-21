# Fresh Raspberry Pi Setup

This document is intentionally short.

## Prerequisites

- Raspberry Pi OS Lite 64-bit installed
- Network connected
- Secure Shell (SSH) enabled
- GitHub access configured

## Install

Clone the repository:

```bash
mkdir -p ~/workspace
cd ~/workspace
git clone git@github.com:vishalvisd/home-automation.git
cd home-automation
```

## Run the complete setup:

```
bash scripts/setup_pi.sh
```


### Check status if something is wrong
```
sudo systemctl status home-automation
```

### Recent logs:
```
sudo journalctl -u home-automation -n 100 --no-pager
```

### For normal updates

After pushing changes from the Mac:

```bash
cd ~/workspace/home-automation
bash scripts/update_pi.sh
```

The update script pulls the latest code, synchronizes Python dependencies,
restarts Home Automation, and verifies that it started successfully.

## Steps outside the update script

Everything on the Pi comes from this repository, so a new system drive
can be rebuilt from scratch. These steps are not part of `update_pi.sh`;
run the ones that apply, in this order, after the install above.

### Service unit changed

When `scripts/install_service.sh` changes, apply it to an existing Pi:

```bash
bash scripts/install_service.sh
```

### Live view (go2rtc)

```bash
bash scripts/install_go2rtc.sh
```

### Archive disk

Format the USB disk once, with the label `cctv`. This erases it. Find
the device first and make sure it is the disk, not the boot drive:

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,TRAN,MODEL
```

Then, with `/dev/sdX` replaced by the disk:

```bash
sudo wipefs -a /dev/sdX
printf 'label: gpt\n,,L\n' | sudo sfdisk /dev/sdX
sudo mkfs.ext4 -L cctv -m 0 /dev/sdX1
```

Then the fstab entry, sudoers rule and persistent journal:

```bash
bash scripts/install_archive.sh
```

Finally switch the archive on in the CCTV tab and press Stop Recording,
then Start Recording.

### Runtime files

`runtime/` is not in git. On a new drive, re-enter in the UI: the camera
list with its stream URLs, the Backblaze accounts, the watering settings.
Keep a private copy of `runtime/cameras.json`,
`runtime/backblaze_credentials.json` and `runtime/watering.json` somewhere
safe to make that quick.

### SSH from the development Mac

The Mac holds a key in `~/.ssh/id_ed25519_pi` and a `Host pi` entry in
`~/.ssh/config`. On a new Pi, append the Mac's public key to
`~/.ssh/authorized_keys`:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '<public key>' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
```

