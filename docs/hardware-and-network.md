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
| Access points | D-Link DIR-615 at 192.168.1.7, TP-Link Deco at 192.168.1.14. |
| USB disk | Toshiba MQ01UBD100 1 TB 2.5", bus powered, ext4, label `cctv`. Mounted at `/mnt/cctv` only during batches. Parks with `hdparm -y`. SMART needs `-d sat,16`. `hdparm -C` lies on this enclosure; use `smartctl -d sat,16 -n standby -i`. |
| Relay board, watering | See `README.md`. The camera power relay (IN3) exists but the current cameras are powered separately. |

## Cameras

All are RTSP cameras. The two ESP32-CAMs are retired; their code path is
kept.

| Key | Camera | Address | Main stream (disk copy, live view) | Sub stream (cloud copy) |
|---|---|---|---|---|
| cam1 | Trueview T18296S, Wi-Fi | 192.168.1.33, router binding, MAC 80:1d:0d:94:2a:3b | `/ch0_0.264` 2304x1296 H.265 15 fps + G.711 a-law, about 19 MB per 3 min | `/ch0_1.264` 800x448 H.265, about 3 MB per 3 min |
| cam2 | Tekzor TZ-1W-IP-NG5SL(ADP), wired, second-floor access point | 192.168.1.36, router binding, MAC 5a:5a:02:4e:f2:1d | `/live/0/MAIN` 2304x1296 H.265 + G.711 mu-law, 7 to 30 MB per 3 min | `/live/0/SUB` 640x360 H.264 10 fps CBR 256 kbps, about 5 MB per 3 min |
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

RAM: the Pi has 3.8 GB; `/dev/shm` (the RAM disk) is 1.9 GB. With four
cameras one 30-minute batch is up to about 1.1 GB of waiting clips.

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
