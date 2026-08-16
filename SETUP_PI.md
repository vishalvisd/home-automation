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