# Hardware and network

What is physically installed and how each device is set up. This is the
living record; update it whenever a device, address or camera setting
changes. No passwords here, ever: camera logins live only in
`runtime/cameras.json` on the Pi.

Settings made on a camera's own web page or on the router are manual
steps outside the Pi. They are written here so the installation can be
rebuilt.

## Pi and network

| Item | Detail |
|---|---|
| Pi | Raspberry Pi 4, 3.8 GB RAM, Debian trixie, Python 3.13. Boots from a 28.7 GB USB pen drive. No fan; about 60 C idle. |
| Pi address | 192.168.1.31 wired (DHCP). API on :8000, go2rtc on :1984. Clock is UTC; clip names and the UI use Asia/Kolkata. |
| Pi power | 45 W phone charger. A 15.5 W one browned out. |
| UPS | 600 VA desktop UPS for the Pi, cameras and router. Nothing tells the Pi when the battery is low. |
| Main router | ZTE F670L at 192.168.1.5. DHCP bindings are made in its admin page. Internet 100 Mbps. |
| Internet line | Basic unlimited 100 Mbps plan, no fixed public address; it can change at any time (owner). Checked from the Mac on 25 Nov 2026: a trace to the public address is passed on by the ZTE, which suggests the provider shares one address between customers. Not confirmed on the ZTE's own page. The line also has IPv6. |
| Remote access | Tailscale Funnel on the Pi, machine name `visd-ha`, set up with `scripts/install_tailscale.sh` (see `SETUP_PI.md`). Public port 443 only: `/` goes to the page on :8000, `/api/ws` to go2rtc's video connection on :1984. `sudo tailscale funnel status` on the Pi shows the address. Key expiry for the Pi must be disabled on Tailscale's site. Installed on 25 Nov 2026 on the owner's existing Tailscale account. Measured that evening from the Mac through the relay: the page and the video connection work; go2rtc's own addresses (`/api/config`, `/api/streams`) answer 404; the four main streams arrived at 4.8 Mbit/s together against 5.2 directly at home, the four sub streams at 1.1 Mbit/s; video starts after about 2 seconds against under 1 at home. The owner then opened it on his phone on mobile data and it works, and he disabled key expiry for `visd-ha` on Tailscale's site (25 Nov 2026). The Android app with both addresses was tried by the owner on home Wi-Fi and on mobile data and opens on both (25 Nov 2026). |
| Access points | D-Link DIR-615 at 192.168.1.7, TP-Link Deco at 192.168.1.14. Wi-Fi names as told by the owner on 28 Nov 2026: `visdgx5ghz_EXT` is the access point at 192.168.1.7 (no router binding); `visd2f_2.4ghz` is a TP-Link TL-WR841N at 192.168.1.9 (router binding, which the owner thinks is not needed). |
| Router bindings | The ZTE holds 10 DHCP bindings and all 10 are used (owner, 28 Nov 2026). The Pi's binding is the one that must always stay. |
| USB disk | Toshiba MQ01UBD100 1 TB 2.5", bus powered, ext4, label `cctv`. Mounted at `/mnt/cctv` only during batches. Parks with `hdparm -y`. SMART needs `-d sat,16`. `hdparm -C` lies on this enclosure; use `smartctl -d sat,16 -n standby -i`. |
| Relay board, watering | See `README.md`. The camera power relay (IN3) exists but the current cameras are powered separately. |

### Development Mac

- SSH: `ssh pi` (192.168.1.31, key `~/.ssh/id_ed25519_pi`) is the entry
  to use. The `Host piwifi` entry in `~/.ssh/config` points at
  192.168.1.10, an address the Pi no longer has.
- The frontend's development server (`npm run dev` in `frontend/`) sends
  its API calls to the Pi at `http://192.168.1.31:8000`. The address is
  set in `frontend/.env.development`, with the same default in
  `frontend/vite.config.js`; change both if the Pi's address changes. It
  affects only a local preview on the Mac, not the built frontend. In
  practice changes are checked on the Pi itself after an update.
- Android build tools, installed with Homebrew on 23 Nov 2026 for the
  app in `android/`: `openjdk@17` (about 300 MB; the Mac's own Java is
  version 8) and the cask `android-commandlinetools` (about 170 MB, SDK
  folder `/opt/homebrew/share/android-commandlinetools`).
  `bash android/setup_tools.sh` adds the two Android parts the build
  needs. Nothing was added to the shell's PATH; the build scripts find
  the tools themselves.

### Where the Pi's address is written down

If the Pi's address changes, these hold the old one:

| Place | What to do |
|---|---|
| The Android app on each phone | Press and hold the app icon, "Pi address". The defaults for a new install are in `android/src/com/visd/ha/MainActivity.java` |
| `frontend/.env.development` and `frontend/vite.config.js` | Edit both (Mac preview only) |
| `~/.ssh/config` on the Mac, `Host pi` | Edit |
| The downloader's Pi address setting | Change it in the downloader |

The Pi's Tailscale address, `visd-ha.tail64b203.ts.net`, is held by
the Android app in the same two places (its away address). It changes
only if the Pi's Tailscale name or account changes.

The Pi gets its address from the router by DHCP. Whether the ZTE router
has a binding for the Pi's MAC has not been confirmed; with one, the
address cannot change by itself.

### How it is cabled (as told by the owner, 23 Nov 2026)

The main ZTE router is on the roof (third floor). Its four Ethernet
ports are all in use:

| ZTE port | Goes to |
|---|---|
| 1 | Ground-floor router, set up as an access point. cam1 Trueview joins its Wi-Fi. |
| 2 | First-floor router, set up as an access point. cam2 Tekzor and cam3 Hikvision (street pole) are cabled to it. |
| 3 | cam4 BlueView, on the roof |
| 4 | The Raspberry Pi, on the roof |

So every camera reaches the Pi through the ZTE router's own ports. While
the ZTE is off or restarting, the Pi can reach no camera and nothing is
recorded, on the disk or in the cloud. A small switch on the roof (Pi,
cam4 and the two access-point cables into the switch, one cable from the
switch to the ZTE) would remove that dependence. The owner considered
it on 23 Nov 2026 and decided against it.

Until 22 Nov 2026 a second-floor access point also existed. It was
removed to free a ZTE port for cam4; the second floor (tenant) uses the
ZTE's own Wi-Fi.

The router power relay is `router_power` (IN2, GPIO 3). The router is
wired through the normally closed contact: relay OFF means powered,
relay ON cuts its power.

cam4 takes its power from the same 12 V line as the router (owner,
25 Nov 2026). So whenever the relay cuts the router, cam4 goes off too
and has to start up again afterwards; expect its gap to be a little
longer than the other cameras'. The owner accepts this.

**Open, 24 Nov 2026: the relay did not cut the router's power.** The
first nightly restart ran from 00:02:21 to 00:04:21 and reported "ok",
but no camera lost a second: 20 clips of 20 in that hour on all eight
recorders, no reconnect, and the steady streams (cam3, cam4) show no
dip in size. With the router really off, the Pi can reach no camera.
So the relay was told to switch and the router stayed powered. The
cause (owner, 24 Nov): he had bypassed the relay himself some time ago,
so the router's supply did not pass through IN2 at all. He began
putting it back on 24 Nov; the restart of 25 Nov 00:00 still had no
effect.

The owner rewired it on the morning of 25 Nov 2026 and reports that the
relay now cuts the router. The Pi's own figures agree: all eight
recorders recovered in the same second, 08:49:19, after his test. The
first nightly restart that can really work is the one of 26 Nov 00:00;
expect about two minutes without recording on every camera and one
recovery per recorder.

**First real nightly restart, 26 Nov 2026.** Started 00:01:02, power off
30 seconds, finished 00:03:02, result "ok". The Mac could not reach the
Pi from 00:01:11 to 00:02:19. All eight recorders were connected again
between 00:02:34 and 00:03:04; cam4, which loses its power with the
router, at 00:02:48. The first uploads of the day went to the new
account without a failure.

The gap is longer than the two minutes expected: about 4 minutes 40
seconds on every camera. The last clip before it ended at about 23:58
and the next began at about 00:03. The clip being written when the
power went (23:58 to 00:01) is lost, because a recorder that starts
again deletes the unfinished file it finds
(`_discard_leftover_files` in `rtsp_ffmpeg_recorder.py`). So about
2 minutes 45 seconds of the gap is footage from before the router went
off. The owner chose on 26 Nov 2026 to leave it as it is.

**Switching the router relay by hand.** Relay ON for the router is a
kill switch: once the router is off, the phone or Mac can no longer
reach the Pi to switch the relay off again, and the router stays dark
until someone goes to the Pi. Use the "Restart router" button on the
Main Router card (Relay Controls tab), where the Pi restores the power
by itself. The plain Relay ON button is in a red box and asks first.

Without the page (backend stopped, or from an SSH session), this does
the same on the Pi itself and finishes even if the SSH session drops
when the router goes off:

```bash
sudo sh -c 'nohup sh -c "pinctrl set 3 op dl; sleep 10; pinctrl set 3 op dh" >/dev/null 2>&1 &'
```

GPIO 3 low is relay ON (the board is active-low), which cuts the
router's power; ten seconds later GPIO 3 high releases the relay. It
works whether the backend is running or stopped, and leaves the pin as
the backend expects it (relay OFF). Every camera loses about two
minutes while the router starts, and cloud clips that finish in that
time fail to upload.

### The disk-rest test script

`~/drive_rest_test.sh` exists only on the Pi, in the service user's home
folder. It was used once to confirm by ear and touch that `hdparm -y`
really stops the disk. It is not in the repository and is not needed to
rebuild a Pi; the disk activity log does the same job now.

## Room microphone modules

ESP32 boards with an I2S microphone, inside wall switch boards, powered
from the mains through a small 5 V supply. Decisions are in
`docs/decisions.md` under "Room microphones". No Wi-Fi or update
password is written here or anywhere in the repository.

| | Module 1 | Module 2 |
|---|---|---|
| Name it sends | `esp32-mic` (trial firmware, fixed name) | `esp32-mic-2f20` |
| Board | ESP32-WROOM-32, 30-pin DevKit V1 | A newer 30-pin ESP32 dev board |
| Microphone | G-SENSE ICS-43434, one microphone | G-SENSE ICS-43434 2CH, two microphones mixed into one |
| Wi-Fi | `visdgx5ghz_EXT` | `visdgx5ghz_EXT` |
| Address on 28 Nov 2026 | 192.168.1.13, router binding | 192.168.1.166, router binding |
| Firmware on 28 Nov 2026 | trial `mic-wifi-1` | trial `mic-wifi-3` |
| Installed | 21 Nov 2026 | 28 Nov 2026 |

Wiring, the same on every module: microphone VDD to 3V3, GND to GND,
SCK to GPIO 14, WS to GPIO 15, SD to GPIO 32 (and L/R to GND on the
one-microphone board). The blue LED on GPIO 2 is steady when Wi-Fi is
connected.

The trial firmware waits for a listener on its own port 3333, which is
why each module has a router binding today. The new firmware calls the
Pi instead, at 192.168.1.31 port 3334, so a module needs no fixed
address. When both modules run it, their two bindings can be given
back (step 6 of the build order).

Known hardware faults, from the trial:

- Module 1 sometimes hangs on a cold start after a power cut (red light
  only) until its power is switched off and on. A restart by software
  is fine. The page will show a module that is not connected.
- A large capacitor on the 3V3 pin stops module 1 from starting.
- Powered through a USB hub the board browns out; plug it into the Mac
  directly.
- A microphone level of 0 has twice been a loose wire.
- An access point that shows a module as connected while nothing can
  reach it has been cured by restarting that access point.

Sound quality, measured in the trial: Wi-Fi adds a hum at 62.5 Hz and
its multiples to the microphone; a ceiling fan is louder than a soft
voice at 2 to 3 metres and covers the same range as speech. The sound
is very quiet as sent; loudness is added when listening.

## Cloud accounts as they stand

Seven Backblaze accounts are entered in the Pi UI; four are enabled and
take part in the daily rotation. Three have been switched off since
21 Nov 2026, because they refused uploads once they held 10 GB
(`StorageCapExceeded`) and the clips of those hours never reached the
cloud. The Test button in the UI does not detect such a cap.

Before one of the three is enabled again, in that account on Backblaze's
site:

1. Raise the storage cap under Caps and Alerts.
2. Set the bucket's lifecycle to 3 days till hide and 1 day till delete,
   like the other buckets (these three were set to never delete).
3. Tick "Enabled" for the account in the Pi UI and save.

## Cameras

All are RTSP cameras. The two ESP32-CAMs are retired; their code path is
kept.

| Key | Camera | Address | Main stream (disk copy, live view) | Sub stream (cloud copy) |
|---|---|---|---|---|
| cam1 | Trueview T18296S, Wi-Fi | 192.168.1.33, router binding, MAC 80:1d:0d:94:2a:3b | `/ch0_0.264` 2304x1296 H.265 15 fps + G.711 a-law, about 19 MB per 3 min | `/ch0_1.264` 800x448 H.265, about 3 MB per 3 min |
| cam2 | Tekzor TZ-1W-IP-NG5SL(ADP), wired, first-floor access point | 192.168.1.36, router binding, MAC 5a:5a:02:4e:f2:1d | `/live/0/MAIN` 2304x1296 H.265 + G.711 mu-law, 7 to 30 MB per 3 min | `/live/0/SUB` 640x360 H.264 10 fps CBR 256 kbps, about 5 MB per 3 min |
| cam3 | Hikvision DS-2CD202RF-I, outdoor pole, 18 m Cat6 with passive 12 V injector | 192.168.1.64 static in the camera, MAC 94:e1:ac:de:95:6f | `/Streaming/Channels/101` 1920x1080 H.264 15 fps VBR max 1536 kbps, about 30 MB per 3 min, no audio hardware | `/Streaming/Channels/102` 704x576 H.264 10 fps VBR max 512 kbps, about 8 MB per 3 min |
| cam4 | BlueView (looks like the Tekzor, different firmware), recording since 22 Nov 2026 21:00 | 192.168.1.113 static in the camera plus router binding, MAC 00:d5:0b:29:b5:5f | `/ch01.264?dev=1` 2560x1440 H.265 about 10 fps + G.711 mu-law. Measured as delivered, at night: 2.1 Mbit/s, about 48 MB per 3 min | `/ch01_sub.264?dev=1` 720x576 H.265 10 fps. The bitrate varies with the scene: measured 256 kbps at 20:06 and 104 kbps at 21:10 on 22 Nov, so 2.5 to 6.5 MB per 3 min |

### Per-camera notes

- **cam1 Trueview.** Login is part of the URL. No ONVIF on port 80. The
  TrueCloud Plus app has no stream or IP settings. It took several app
  reboots to pick up the router binding.
- **cam2 Tekzor.** Web page at `http://192.168.1.36/` (Boa / "zwcloud"
  firmware). ONVIF on port 80 answers without a login. It came with DHCP
  off at 192.168.1.159. The sub-stream bitrate field appears only when CBR
  is chosen. Night clips are up to four times larger (IR grain).
- **cam3 Hikvision.** Bought second hand, activated by the owner. Only
  Main and Basic profile offered. Its password contains `@`, written `%40`
  inside a URL.
- **cam4 BlueView.** Web page at `http://192.168.1.113/` (nginx). ONVIF on
  port 80 answers without a login and gave the stream addresses (profiles
  `D01_CH01_Main` and `D01_CH01_Sub`). ONVIF reports 2592x1904 for the
  main stream but the stream itself is 2560x1440. **As delivered, both
  RTSP streams open without any login.** Each stream also carries a data
  track, which ffmpeg leaves out by default.

### Finding a new camera

`scripts/find_camera.py` runs on the Mac:

```bash
python3 -I scripts/find_camera.py discover
python3 -I scripts/find_camera.py onvif 192.168.1.113
```

The first lists ONVIF devices and the ARP table; the second asks one
camera for its stream addresses.

### Adding a camera, in order

1. Give it a fixed address (in the camera, and a DHCP binding on the main
   router for its MAC).
2. Find the main and sub stream addresses (`find_camera.py onvif`).
3. Record a minute of each stream on the Mac and work out MB per 3
   minutes; check the totals in "Numbers" below still fit.
4. Set the stream bitrates on the camera's own web page and write them in
   the table above.
5. Add the camera in the Pi UI (CCTV tab, Cameras): type RTSP, main stream
   address, sub stream address. The UI gives it the next key (`camN`).
6. Restart the backend so every part starts clean (the owner runs
   `sudo systemctl restart home-automation`).
7. Check the camera card (both lights), live view, the next disk batch,
   and the clips in the downloader.

## Numbers

Daily sizes, measured. Update when a camera or bitrate changes.

| Camera | Disk copy per day | Cloud copy per day |
|---|---|---|
| cam1 Trueview | about 8.5 GB | about 2.1 GB (94 MB an hour by day, 77 at night) |
| cam2 Tekzor | about 5 GB (160 MB an hour by day, 290 at night) | about 2.8 GB (124 MB an hour by day, 110 at night) |
| cam3 Hikvision | about 15 GB | about 2.4 GB (107 MB an hour by day, 93 at night) |
| cam4 BlueView, night figures only | about 22 GB (935 MB an hour) | about 1.05 GB (43 MB an hour) after the owner tuned the sub stream on 22 Nov 2026 |

The cloud figures for cam1 to cam3 are from the hourly counters of
22 Nov 2026 and add up to about 7.3 GB a day. That leaves about 2.7 GB
for cam4. Night of 22 to 23 Nov with all four cameras: about 283 MB an
hour to the cloud (about 6.8 GB a day at the night rate) and about
2.1 GB an hour to the disk (one 30-minute batch is about 1.07 GB).

Night of 23 to 24 Nov 2026, measured per hour: the cam2 main stream
grows through the night, from about 300 MB an hour at midnight to
700 MB an hour between 05:00 and 06:00 (160 by day). All four cameras
together then write about 2.5 GB an hour to the disk against 2.1 GB at
other times, and a 30-minute batch reaches 1.25 to 1.4 GB. One batch
that night (06:11) started early because the waiting clips passed
`archive_buffer_limit_mb` (1300); nothing was dropped. The cloud copy
ran at 255 to 300 MB an hour by night and about 420 by day, about
8.3 GB a day.

RAM: the Pi has 3.8 GB; `/dev/shm` (the RAM disk) is 1.9 GB. With four
cameras one 30-minute batch is about 1.1 GB of waiting clips, and up to
1.4 GB before dawn (see above).

Room microphones, measured on 28 Nov 2026 on a recording from each
module: Opus at 32 kbps needs about 12 MB an hour per module, so the
2 hours kept are about 25 MB per module and about 100 MB for four
(limit 120 MB). Raw sound would be 115 MB an hour per module, FLAC 28
to 31. Encoding one module costs about 2 % of one core of the Pi.

- Each Backblaze account has 10 GB free; a day's cloud copy goes to one
  account, so the daily cloud total should stay under 10 GB.
- Backblaze price: 6.95 USD per TB per month, uploads free.
- Upload limit on the Pi is shared by all cameras (`b2_upload_rate_kb_s`).

## Restarting the backend

A restart (`bash scripts/update_pi.sh` or `sudo systemctl restart
home-automation`) stops every recorder, finishes the uploads and runs a
last disk batch before the new process starts. On 22 Nov 2026 that took
53 seconds, so every camera has a gap of about one minute. Restart only
when needed.
