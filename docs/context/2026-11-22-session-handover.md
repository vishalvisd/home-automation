# Context handover: camera migration, disk copy, cloud rotation (13 to 22 Nov 2026)

This file lets a new Claude Code session continue exactly where the previous
one stopped. Read it in full before doing anything. It is written for the
assistant, in the owner's own terms. The owner is Vishal (he/him is not
stated; use "the owner"). The folder `docs/context/` is a permanent trail of
such handovers; never delete earlier ones.

Related files to read next: `CLAUDE.md`, `README.md`, `SETUP_PI.md`,
`docs/two-tier-storage-plan.md` (the design, mostly implemented now).

---

## 1. How the owner wants to work (non-negotiable)

- **Nothing on the Pi by hand.** Every change goes Mac -> git -> Pi
  (`bash scripts/update_pi.sh`, or a repo script). If something must be done
  on the Pi outside a script, it is documented in `SETUP_PI.md` under
  "Steps outside the update script" so a new system drive can be rebuilt.
  The assistant once gave a one-off `systemctl` drop-in command by hand and
  was corrected; the fix was moved into `scripts/install_service.sh`.
- **SSH from the Mac exists (`ssh pi`, key `~/.ssh/id_ed25519_pi`, user
  `visd`, 192.168.1.31) but is for reading, `git pull`, `uv sync` and repo
  scripts only.** `sudo` over that SSH session asks for a password (except
  the few sudoers rules the scripts install), so service restarts are run by
  the owner: he prefers to be given the exact command and run it himself.
  Latest preference (22 Nov): "give me the command to run on the Pi instead
  of you doing it yourself", even for a plain `git pull`.
- **Ask before changing code or Pi settings.** Summarise, agree, then
  implement. The owner makes design and logic decisions. He was irritated
  when settings were changed through the API without asking (early on), and
  once when the assistant renamed things unilaterally.
- **One step at a time** when guiding hands-on work (commands, camera UI
  pages): give one or a few commands, wait for the pasted output, then the
  next. Do not dump long procedures.
- **Plain language, honest feedback, numbers in tables.** He reads
  carefully and challenges claims; when he is right, say so plainly
  (e.g. the charger was not weak in general; the pen-drive batching idea).
- **Terminology:** the USB disk holds the **disk copy**, the primary,
  full-quality recording. The cloud is the **cloud copy**, a backup for
  sabotage or disk failure. **Never call the disk copy "archive"** in UI
  text or prose; the word survives only in code identifiers and settings
  keys (`archive_*`, `ArchiveService`, `/api/cameras/archive`). Renaming
  those is a possible later cleanup he has not asked for.
- **Secrets never in chat.** Camera passwords and Backblaze application keys
  are typed by the owner into the Pi UI. The Hikvision password once
  appeared in a pasted ffprobe line and the Pi password was once typed in
  chat; both were flagged, the SSH key replaced the password. Never echo
  them. When probing cameras from the Pi, read URLs from
  `runtime/cameras.json` inside a script and never print them.
- Commit messages: one short lowercase line, human. No Co-Authored-By.
  Frontend builds on the Mac (`cd frontend && nvm use && npm run build`),
  `frontend/dist` committed. Same for `downloader/frontend`.
- He pushes to GitHub himself (the assistant's `git push` is blocked by the
  app's permission classifier). Flow: assistant commits -> owner pushes ->
  owner (or assistant) pulls on the Pi -> owner restarts when needed.
- Memory: the assistant keeps notes in its memory directory
  (`working-style.md`, `trueview-camera-migration.md`,
  `camera-lineup-2026-11.md`, `cloud-tiering-plan.md`). This handover
  supersedes them where they differ.

## 2. Hardware and network as it stands

| Item | Detail |
|---|---|
| Pi | Raspberry Pi 4, 3.8 GB RAM, Debian trixie, Python 3.13, boots from a 28.7 GB SanDisk Cruzer Blade USB pen drive (`/dev/sda`), 21 GB free. Runs at about 60 C idle; it hit its soft thermal limit in the ESP32/x264 era. No fan. |
| Pi address | 192.168.1.31 wired (DHCP). The `~/.ssh/config` entry `piwifi` (192.168.1.10) is stale. API on :8000, go2rtc on :1984. The Pi's clock is UTC; clip names and the UI use Asia/Kolkata. |
| Pi power | A 45 W phone charger (replaced a 15.5 W one on 21 Nov). The old charger browned out under heavy CPU (x264 era: ~150 dips between 5 and 14 Nov) and at disk spin-up. On the 45 W charger `vcgencmd get_throttled` stayed `0x0` through disk spin-up and a 1 GB write. The owner decided NOT to buy the official supply; a boost-converter idea was shelved. |
| UPS | A repurposed 600 VA desktop UPS backs the Pi, the cameras and the router. Nothing tells the Pi when the battery is low. |
| Main router | ZTE F670L fibre router at 192.168.1.5 (admin UI used for DHCP bindings). Internet 100 Mbps. |
| Access points | D-Link DIR-615 at 192.168.1.7 (factory login advertised as admin/admin, flagged), TP-Link Deco at 192.168.1.14. The Tekzor is wired to the second-floor access-point router. |
| Mac | Development machine, Wi-Fi, 192.168.1.12 or .25 (changes). The Claude desktop app's built-in browser pane can open the Pi page on :8000 but refuses WebSockets to :1984, so Live View can only be verified in the owner's browser. The `.claude/launch.json` frontend entry and the Vite dev config still point at stale addresses (192.168.1.10) and were never made to work; local previews were abandoned in favour of checking on the Pi. |
| USB disk | Toshiba MQ01UBD100 1 TB, 2.5", bus powered, in its own USB 3.0 enclosure (Micro-B), bought with the owner's first salary; he is emotionally attached and wants it rested. SMART (needs `-d sat,16`): 229 h, 0 reallocated, 0 pending, 0 uncorrectable, short self-test passed. Formatted ext4, label `cctv`, `-m 0`. Mounted at `/mnt/cctv` only during batches. Parks with `hdparm -y` (the SCSI stop command is ignored by this enclosure); state read with `smartctl -d sat,16 -n standby -i`. Verified physically by the owner (script `~/drive_rest_test.sh` on the Pi, not in repo). Two damaged clips from before the KillMode fix remain on it (cam1 and cam3, 2026-11-22 01:05) and are skipped by the downloader. |
| Relay board, watering | Unchanged from README. Camera power relay (IN3) still exists but the new cameras are powered separately. |

### Cameras (all RTSP; ESP32-CAMs retired, code path kept)

| Key | Camera | Address | Main stream (disk + live view) | Sub stream (cloud) | Notes |
|---|---|---|---|---|---|
| cam1 | Trueview T18296S, Wi-Fi, same OEM as Manomay | 192.168.1.33, router DHCP binding, MAC 80:1d:0d:94:2a:3b | `/ch0_0.264` 2304x1296 H.265 15 fps + G.711 a-law, ~19 MB/3 min | `/ch0_1.264` 800x448 H.265 15 fps ~125 kbps, ~3 MB/3 min | Login in URL. No ONVIF on :80. TrueCloud Plus app has no stream or IP settings. Took several app reboots to take the DHCP binding. |
| cam2 | Tekzor TZ-1W-IP-NG5SL(ADP), wired, 2nd floor AP, own 12 V adapter | 192.168.1.36, DHCP binding, MAC 5a:5a:02:4e:f2:1d (locally administered, odd but stable) | `/live/0/MAIN` 2304x1296 H.265 + G.711 mu-law, 7 to 30 MB/3 min (IR grain at night) | `/live/0/SUB` 640x360 H.264 10 fps CBR 256 kbps -> ~213 kbps, ~4.8 MB/3 min | Boa/"zwcloud" firmware web UI at http://192.168.1.36/, admin password set by owner. ONVIF on :80 answers without login (gave the stream URIs). Was DHCP off at .159 until switched to DHCP. Sub-stream bitrate field appears only when CBR is chosen. |
| cam3 | Hikvision DS-2CD202RF-I, second hand, outdoor pole, 18 m Cat6 with passive 12 V injector pair | 192.168.1.64 static in the camera, MAC 94:e1:ac:de:95:6f | `/Streaming/Channels/101` 1920x1080 H.264 15 fps, VBR Medium, max 1536 kbps, I-frame 30, Main Profile (only Main/Basic offered), ~30 MB/3 min, NO audio hardware | `/Streaming/Channels/102` 704x576 H.264 10 fps VBR Higher max 512 -> ~370 kbps, ~8.3 MB/3 min | Was factory-reset ("inactive") when bought; owner activated it. Password contains `@`, written `%40` in URLs. Ran hours on an 18 V adapter by mistake without harm; the real outage was a disconnected power wire at the pole. |
| future cam4 | another Tekzor, planned | | | | would add ~8 GB/day main, ~2.4 GB/day sub |

Desk tool: `scripts/find_camera.py` (ONVIF discovery, ping sweep, ONVIF stream lookup, RTSP path guessing). Router DHCP bindings for the old ESP32 MACs were removed.

## 3. What was built this session, by commit (oldest first)

1. `bacbc0d` Live View tab via go2rtc (v1.9.15 pinned, `scripts/install_go2rtc.sh`, systemd unit, sudoers for `systemctl restart go2rtc`), `LiveViewService` writes `runtime/go2rtc.yaml` from the camera list and restarts go2rtc on change; player is vendored `frontend/src/vendor/video-rtc.js` (MIT).
2. `2b5f660` go2rtc `api.origin: "*"` so the page on :8000 may open WebSockets to :1984 (go2rtc 403s cross-origin otherwise).
3. `1cff488` Backblaze accounts as a list (`runtime/backblaze_credentials.json`, migrated from the single key + old `b2_bucket` setting), `CloudRotationService` (one account per calendar day in Asia/Kolkata, next enabled account after the latest known day, state in `runtime/cloud_rotation_state.json`, a clip is routed by its own date), `SharedUploadRateLimiter` (one budget for all uploads, setting `b2_upload_rate_kb_s`, default 750; the old `b2_upload_rate_kbps` was per upload and really KB/s). Accounts table in the UI, rotation status line.
4. `48bcc32` per-account Test button (`POST /api/cameras/backblaze/accounts/test`): authorise, find bucket, check writeFiles.
5. `a651c12` downloader pulls the account list from the Pi (`GET /api/cameras/backblaze/accounts/export`, returns keys, unprotected like the camera passwords in `/settings`), searches every account in parallel, clips carry `account`; downloader's local-archive feature removed (B2 egress costs; owner never wanted it); downloader settings now just `pi_url`.
6. `8ab8af4` disk copy: `sub_stream_url` per camera (renamed from `live_stream_url`, migration kept), recorder roles `cloud` (sub stream, AAC 24 kbps mono) and `archive` (main stream, 32 kbps), `ArchiveService` (RAM buffer `/dev/shm/home-automation/archive/<cam>` + `pending/`, batch every 30 min or at 800 MB: mount, copy with fsync and size check, delete oldest day when free < 20 GB, read SMART, unmount, `hdparm -y`; final batch at shutdown; buffer cap drops oldest when the disk is away), `scripts/install_archive.sh` (fstab `noauto,user`, sudoers for hdparm/smartctl by label, persistent journal 200 MB), UI section, per-camera line. Live view fixed to the main stream.
7. `add73c5` Live View Main / Sub switch (go2rtc streams `camN` and `camN_sub`).
8. `450f17f` downloader Cloud / Pi disk source switch; Pi serves `/api/cameras/archive/{cameras,days,clips,file}`; browsing wakes the disk and keeps it awake 3 min after the last request; a batch never parks under a browser; joins take all clips from one source.
9. `8b8b10b` restart bug: systemd signalled ffmpeg too, a second signal made ffmpeg abort the final index write -> clips without moov. `KillMode=mixed`, every finished clip is ffprobe'd and discarded loudly if unplayable (cloud and disk), downloader join skips damaged clips.
10. `227c19f` `scripts/install_service.sh` writes the unit (setup calls it; rerun on existing Pis), `SETUP_PI.md` "Steps outside the update script" (service, go2rtc, disk format, runtime files, Mac SSH key).
11. `5e74e34` `ArchiveService` recreates its RAM folder on demand.
12. `4e38dfa` ROOT CAUSE of vanishing RAM: systemd-logind `RemoveIPC=yes` deletes a user's `/dev/shm` files when their last login ends; every SSH logout (owner's laptop timeout at 03:34 on 22 Nov, or the assistant's own ssh commands) wiped `/dev/shm/home-automation`. Fixed in `install_service.sh`: `RemoveIPC=no` drop-in + `loginctl enable-linger visd`. Verified with a marker file across a logout.
13. `6c8ec4a` camera cards: per copy a traffic light (rules in `copyLight()` in `CameraPanel.jsx`), plain timings (connected since, clip in progress, last clip closed with size and duration, last upload/stored, since-start counters, recoveries with time, errors with time) and a 24-box last-24-hours strip per copy (`RecordingStatsService`, counters per camera/copy/clip-hour, saved to `runtime/recording_stats.json` at most hourly; green >= 90 % of 3600/segment_seconds, amber >= 50 %, red below, grey before counters existed). Status API: each camera has top-level cloud recorder fields + `upload` + `hours`, and `disk` (recorder fields + `store` + `hours`).
14. `25b4a35` CCTV tab split into sub tabs Cameras / Disk copy / Cloud (Backblaze) / Recording settings; header above, Save / Start / Stop below all; choice in localStorage.

Uncommitted: `docs/two-tier-storage-plan.md` (the design doc; add to the same commit as this handover), `.claude/launch.json` edits (a `frontend` entry that never worked; harmless).

## 4. Runtime state on the Pi right now (not in git)

- `runtime/cameras.json`: three cameras as in section 2, `archive_enabled: true`, `archive_directory /mnt/cctv`, `archive_disk_device /dev/disk/by-label/cctv`, buffer `/dev/shm/home-automation/archive`, `archive_min_free_gb 20`, `archive_flush_minutes 30`, `archive_buffer_limit_mb 800`, `segment_seconds 180`, `pending_upload_limit 3`, `b2_upload_enabled true`, `b2_upload_rate_kb_s 500` (owner set it), `recording_enabled true`.
- `runtime/backblaze_credentials.json`: seven accounts. Enabled: `visd-cctv-eu`, `visd-cctv-eu-10r`, `visd-cctv-eu-06`, `visd-cctv-ue-10g` (US East). **Disabled** since 21 Nov night: `visd-cctv-tullu1995ta-eu-key`, `visd-cctv-garima1992gv-eu-key`, `visd-cctv-ganga9636-eu-key` (owner's wife's accounts) because they refused uploads at 10 GB with `StorageCapExceeded`, losing hours of cloud footage on 20 and 21 Nov. All seven pass the Test button. **Pending for the owner:** in each wife account raise the storage cap under Caps and Alerts (cards are on file; the "06" account proved caps can be above 10 GB), set lifecycle to 3 days till hide and 1 till delete (they had 0 = never delete), then re-enable in the UI. Buckets elsewhere use lifecycle 3+1.
- `runtime/cloud_rotation_state.json`: 15 Nov eu, 16 eu-10r, 17 eu-06, 18 ue-10g, 19 tullu, 20 garima, 21 ganga then rewritten to eu after ganga was disabled, 22 -> next after eu. With a 4-day lifecycle and 4 enabled accounts, an account's old day overlaps its new day for a few hours (owner accepts the small bill).
- `runtime/go2rtc.yaml`, `runtime/recording_stats.json`, `runtime/cloud_rotation_state.json` are written by the backend.
- Pi system: unit from `install_service.sh` (KillMode=mixed), `/etc/systemd/logind.conf.d/home-automation.conf` RemoveIPC=no, linger on, `/etc/sudoers.d/home-automation-go2rtc` and `-archive`, fstab `LABEL=cctv /mnt/cctv ext4 defaults,noatime,nofail,noauto,user,x-systemd.device-timeout=10 0 2`, persistent journal, hdparm/smartmontools/sdparm installed, `~/.ssh/authorized_keys` has the Mac key. Passwordless sudo is NOT available for arbitrary commands.
- Downloader on the Mac: `cd downloader && uv run visdcam-downloader`, port 8800, settings `pi_url http://192.168.1.31:8000`. It was restarted by the owner after each change.

## 5. Numbers the owner relies on

- Main streams: Trueview ~8.5 GB/day, Tekzor ~8 GB/day (4x at night from IR grain), Hikvision ~13 to 15 GB/day at 1536 kbps; about 30 GB/day total; measured 29.4 GB in one account for 17 Nov.
- Sub streams (cloud): Trueview 1.3 GB/day, Tekzor 2.4, Hikvision 4.0; about 7.7 GB/day, inside each account's free 10 GB. First sub clips observed: 3.2 / 5.4 / 3.0 MB.
- Backblaze price confirmed from their page: 6.95 USD/TB/month, 10 GB free storage per account, egress free up to 3x stored, uploads free. At full main streams the four-account bill was about 0.6 USD/month; total billable storage = 120 GB minus 10 GB per account; with sub streams it rounds to zero.
- Disk: 10 days of 3 cameras ~300 GB; 1 TB gives weeks; retention is "fill the disk, delete the oldest day under 20 GB free" by the owner's explicit choice (no day cap).
- Blind window at an attack (Pi or router destroyed): with 3-minute clips 2 to 5 min; with 30-second clips about 20 to 40 s. The owner liked 30-second clips plus upload limit 2000 KB/s plus waiting-clip cap 20, but has NOT applied them (segment_seconds is still 180). If he does, the downloader's fixed "clip length" setting should become per-day inference from gaps between clip end times (not built).
- The first clip after any recorder restart is short (ffmpeg cuts at the stream's own 3-minute boundary); harmless.
- Cameras limit concurrent RTSP sessions; the Trueview and Tekzor briefly refused connections when six recorders plus go2rtc started at once; the supervisor recovers within a minute.

## 6. Decisions explicitly made by the owner (do not reopen)

- Cloud copy = sub stream with audio; disk copy = main stream; live view = main stream with a Main/Sub switch for comparison.
- No automatic account switch when an account refuses uploads (he said it would confuse the downloader; the manual workaround is to untick the account in the UI, which reassigns the rest of the day).
- No speed-up/time-lapse on the Pi (CPU, no HEVC encoder); time-lapse stays in the downloader on the Mac.
- No downloader archive feature. Downloader offers Cloud or Pi disk as source; no automatic preference.
- No pen-drive buffering through the system drive (wear); RAM batching with the disk parked instead.
- Lifecycle stays 3+1; he will add accounts rather than shorten it. He does not want a $0 spending cap. He runs several free accounts on family emails deliberately; the assistant declined to build IP/hostname tricks to hide that from Backblaze and he accepted.
- Passphrase login for the Pi UI and the downloader is designed (browser localStorage, logout) but **deferred** by him; the account export endpoint and camera passwords are therefore open on the LAN.
- The disk must rest between batches (parked), never spin continuously.

## 7. Open items, in the order he mentioned them

1. Wife accounts: caps, lifecycle, re-enable (section 4).
2. Verify the sub tabs after `git pull` on the Pi (frontend only; he was asked to run `cd ~/workspace/home-automation && git pull --ff-only`).
3. Watch the first days of the 24-hour strips and disk batches; the strips started at about 11:00 IST on 22 Nov.
4. Possibly 30-second clips (see section 5) with the downloader change.
5. Passphrase login (designed in `docs/two-tier-storage-plan.md` Part 1).
6. Optional cleanup: rename `archive` identifiers to `disk_copy`; `.claude/launch.json` and `frontend/.env.development` stale addresses; a SMART-based warning; a "Powering off" section in SETUP_PI.md (the assistant offered: `sudo systemctl stop home-automation` then `sudo poweroff`; the disk can be unplugged whenever the UI shows it parked).
7. Fourth camera (Tekzor) when bought: add in the UI, DHCP binding, sub stream CBR 256, main stream as cam2.
8. Heat: a heatsink/fan for the Pi was recommended, not bought.

## 8. Gotchas learned the hard way

- `/dev/shm` and logind RemoveIPC (fixed). Until `install_service.sh` has run on a Pi, do not ssh into it, each logout wipes RAM.
- Two signals kill ffmpeg's final write (fixed with KillMode=mixed). Never add a second signal path.
- The Pi journal was volatile until 22 Nov; older history is gone.
- Tmp heredocs: when writing Python patches through bash heredocs that themselves contain `<<EOF`, use a different outer delimiter (`PYEOF`), otherwise the shell ends the heredoc early and the patch silently does nothing.
- The app's auto-mode classifier sometimes refuses a Bash call for having a leading `cd` after the shell moved; re-issue the identical call on its own.
- The browser pane cannot reach port 1984; use the owner's browser for live view checks.
- `hdparm -C` lies on this enclosure; use smartctl `-n standby`.
- Phone chargers output 5.0 V; the Pi complains below 4.63 V; the 45 W one copes, the 15 W one did not with the disk.
- B2 free accounts refuse at exactly 10 GB with `StorageCapExceeded` unless the cap is raised; the Pi then deletes each refused clip (upload-once policy), so hours are lost silently. The Test button does not detect caps.
- Tekzor/Trueview sub streams are H.265 (Trueview) / H.264 (Tekzor after change); H.265 plays in Safari and Chrome on Mac only.
