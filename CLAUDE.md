# CLAUDE.md

Guidance for AI coding assistants working in this repository. The detailed
architecture reference is `README.md`; read it first.

## Read these first, in this order

1. `docs/decisions.md`: what the owner has decided. Do not reopen these.
2. `docs/hardware-and-network.md`: the devices, addresses, camera streams
   and measured sizes as they are now.
3. `README.md` for the architecture, `SETUP_PI.md` for building a Pi.

Keep them current. When a decision is made, a device changes or a manual
step is added, update the matching file in the same piece of work. These
documentation files may be edited without asking the owner first.

## The rebuild rule

If the Pi's system USB drive fails, a new drive must reach the same state
quickly from this repository alone. So:

- Code reaches the Pi only through git (`bash scripts/update_pi.sh`).
- Anything else needed on the Pi is a script in `scripts/`, or a step
  written in `SETUP_PI.md` under "Steps outside the update script".
- Never give the owner a one-off command that changes the Pi without also
  recording it there. A manual step that is not written down is a bug.
- Settings made outside the Pi (camera web pages, router DHCP bindings)
  go in `docs/hardware-and-network.md`.

## What this is

A Raspberry Pi 4 home-automation and CCTV backend (FastAPI + Python 3.13,
managed with `uv`) with a React/Vite frontend served as static files from
`frontend/dist`. One systemd service, `home-automation`, runs the backend.
All application scheduling lives in Python threads, not cron or systemd timers.

## How to work here

- Read the relevant code before proposing anything. Summarise, agree the
  plan with the owner, then implement. The owner makes design and logic
  decisions; do not make project-logic calls unilaterally.
- Small steps, one concept at a time. Plain language in code comments,
  commit messages and explanations.
- Give honest feedback. If an existing choice is a bad idea for a new
  requirement, say so plainly instead of working around it quietly.
- Flag hard-coded values (IP addresses, bucket names, hosts) rather than
  silently changing them.
- Commands that run on the Pi are given to the owner to run; wait for the
  output. One step at a time for hands-on work.
- There is no automated test suite yet, by decision. When a change needs
  a check script (a simulated disk, relay or camera), keep it in `tests/`
  and commit it with the change.
- There is no login, by decision. Since 25 Nov 2026 the owner also wants
  the page reachable from the internet, through Tailscale Funnel on the
  Pi only (see "Remote access" below). Do not add a login, and do not
  expose anything more than that section lists, without the owner
  asking.
- Never ask for or repeat a camera password or Backblaze key in chat.

## Workflow

- Development happens on a Mac. Code is pushed to GitHub, then pulled on the
  Pi with `bash scripts/update_pi.sh` (git pull, `uv sync --frozen`, service
  restart, health check).
- The frontend production build is made on the Mac and committed:
  `cd frontend && nvm use && npm ci && npm run build`. Never build it on
  the Pi. Commit `frontend/dist` with any frontend change.
- Commit messages: one short lowercase line, written like a human.
- No `Co-Authored-By` lines in commits.

## Secrets and runtime state

- Everything machine-specific lives under `runtime/` on the Pi, which is
  gitignored: camera settings (`cameras.json`), Backblaze credentials
  (`backblaze_credentials.json`, mode 0600), schedule state, editable
  automation scripts.
- Never commit credentials, bucket names tied to an account, or camera
  passwords. RTSP URLs may contain a camera login and are stored only in
  `runtime/cameras.json`.
- Defaults in `src/home_automation/config/*.py` are only used the first
  time a runtime file is created. After that the JSON file is the source
  of truth and is edited from the UI.

## CCTV rules that are deliberate

- Recording goes to RAM (`/dev/shm`) on purpose, to spare the SD card.
  `scripts/install_service.sh` sets logind `RemoveIPC=no` and linger for
  the service user; without that, a logout wipes /dev/shm.
- Each finished segment is uploaded to Backblaze B2 once, then deleted,
  whether or not the upload succeeded. There is no retry queue and no
  local backup. If uploads fall behind, the oldest waiting segment is
  dropped (`pending_upload_limit`).
- Two camera types must keep working side by side:
  - `esp32_mjpeg`: ESP32-CAM MJPEG over HTTP, GStreamer capture, x264
    software encode, MPEG-TS `.ts` segments. Day/night presets apply.
  - `rtsp`: commercial IP cameras, ffmpeg with `-c:v copy` (never
    re-encode video on the Pi), audio converted to AAC, MP4 segments.
- The two "Pause uploads" buttons act only on the cloud uploads for a
  set time; they must never stop a recorder. One keeps the clips in RAM
  and uploads them afterwards (limited by `upload_pause_buffer_mb`,
  giving way before the disk copy runs short of RAM); the other deletes
  them so nothing uploads afterwards.
- "Stop recording for N min" stops every recorder and starts them again
  by itself. Pauses and the timed stop live in memory only, so a backend
  restart always ends them.
- Uploads rotate between several Backblaze accounts, one account per
  calendar day (`CloudRotationService`, state in
  `runtime/cloud_rotation_state.json`). A past day's account never
  changes. The downloader must look in every account for a day.
- Keep the B2 object layout `camN/YYYY/MM/DD/HH/cam_N_YYYY_MM_DD_HH_MM_SS.<ext>`.
  Another project downloads these objects.
- Do not auto-restart the shared camera power relay because one camera
  fails.

## Nightly router restart that is deliberate

- With `router_restart_enabled`, the main router is power-cycled once a
  night through the `router_power` relay, at the moment the day's
  Backblaze account changes (`RouterRestartService`, called from
  `CameraUploadService`). It is for the router's health only.
- It costs about two minutes of recording on every camera, because every
  camera reaches the Pi through the router. The owner accepts this.
- It runs only in the hour after midnight. Do not add other automatic
  triggers.
- Relay ON for `router_power` is a kill switch: with the router off,
  nothing on the home network can reach the Pi to switch it back. The
  safe way is `POST /api/relays/router_power/restart` (the "Restart
  router" button), where the Pi restores the power by itself. It only
  switches the relay and does not hold uploads, by the owner's choice.
  Never ask the owner to switch that relay on from the page or from
  another device, and never do it yourself: a preview on the Mac sends
  its relay commands to the real Pi.

## Disk copy rules that are deliberate

- Call it the disk copy (the primary recording); the cloud is the backup.
  "archive" survives only in code and settings names.
- Main streams go to a USB laptop disk through `ArchiveService`: clips
  wait in RAM, move to the disk in batches, and the disk is parked
  (`hdparm -y`) between batches. Never leave it spinning; never write
  the archive to the boot pen drive.
- No day limit. When free space falls under `archive_min_free_gb` the
  oldest day is deleted in one go.
- No size limit may drop a waiting clip. A clip is dropped only when the
  RAM disk is nearly full (`archive_buffer_reserve_mb`), oldest clip of
  all cameras first. `archive_buffer_limit_mb` only starts a batch early.
- Setup is `scripts/install_archive.sh` (fstab `noauto,user`, sudoers
  for park and SMART, persistent journal).

## Live view

- Browser live view is served by go2rtc, a separate systemd service on
  the Pi installed once with `scripts/install_go2rtc.sh`. The backend
  writes `runtime/go2rtc.yaml` from the camera list and restarts go2rtc
  through a sudoers rule. Do not re-encode video for live view.
- The player is go2rtc's `video-rtc.js`, vendored under
  `frontend/src/vendor`. Update it from a pinned go2rtc tag, never edit
  it by hand.
- The player opens a WebSocket from the browser to go2rtc: on port 1984
  at home, and on the page's own address when the page is `https`
  (`frontend/src/services/liveUrl.js`, checked by
  `tests/check_live_url.mjs`).
  The Claude desktop app's built-in browser can open the Pi page on port
  8000 but refuses that WebSocket, so live view can only be confirmed in
  the owner's own browser. Ask him to look.

## Remote access

- The page is reachable from the internet through Tailscale Funnel,
  which runs on the Pi only (`scripts/install_tailscale.sh`, steps in
  `SETUP_PI.md`). The Pi dials out to Tailscale's relay; nothing is
  opened on the router. The owner rules out port forwarding, a paid
  domain or server, and any Tailscale or VPN app on a phone.
- Public, on port 443 of the Funnel address: `/` (the page and API on
  port 8000) and `/api/ws` (go2rtc's video connection). Never publish
  the rest of go2rtc's port 1984: its own page hands out the stream
  addresses with the camera logins.
- No login for now, by the owner's choice; he plans one later. Do not
  lecture him about it. His own limit is that nobody may reach the Mac
  or other devices on the home network.
- Do not write the full Funnel address in the repository.
- Only the owner can test from outside, on mobile data.

## Relay rules that are deliberate

- Relay ON/OFF means the relay coil, not the appliance. Some appliances
  are wired through normally closed contacts, so relay OFF can mean
  powered. Do not add appliance-state tracking.

## Downloader (`downloader/`)

A separate local app, not run on the Pi: Python FastAPI + b2sdk backend and a
React UI, started with `uv run visdcam-downloader` from `downloader/`. It
browses, downloads, joins and time-lapses the clips the Pi uploads. It
gets the Backblaze account list from the Pi and searches every account.
It has its own `pyproject.toml`, `.venv`, `frontend/` and gitignored
`runtime/`. See `downloader/README.md`. Clip names carry the clip END time.

## Android app (`android/`)

A separate small app, not run on the Pi: one Java file that shows the
Pi's own page in a web view, opened on Live View with `?tab=live`. It is
built on the Mac with `bash android/build.sh` (JDK 17 and the Android
command-line tools, no Gradle) and copied to the phone as an APK, which
is not committed. Keep it a plain window onto the page: internet is its
only permission, and features belong in the page, not in the app. The
signing key lives in the gitignored `android/runtime/`. See
`android/README.md`. It cannot be run on the Mac; the owner tries it on
his phone.

## Layout

```
src/home_automation/
  api/        FastAPI app, routes, dependency helpers
  config/     pydantic settings models and static hardware config
  services/   long-lived services (relays, watering, cameras, upload)
frontend/src/ React UI (tabs: relays, cameras, watering, automations)
scripts/      Pi setup and update scripts, go2rtc install, LAN camera finder
automation_templates/  default standalone automation scripts
downloader/   local Mac/Windows app for the uploaded clips (own venv and UI)
android/      Android app that shows the Pi's page on Live View (own build)
```
