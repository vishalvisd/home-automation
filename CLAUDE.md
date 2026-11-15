# CLAUDE.md

Guidance for AI coding assistants working in this repository. The detailed
architecture reference is `README.md`; read it first.

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
- Each finished segment is uploaded to Backblaze B2 once, then deleted,
  whether or not the upload succeeded. There is no retry queue and no
  local backup. If uploads fall behind, the oldest waiting segment is
  dropped (`pending_upload_limit`).
- Two camera types must keep working side by side:
  - `esp32_mjpeg`: ESP32-CAM MJPEG over HTTP, GStreamer capture, x264
    software encode, MPEG-TS `.ts` segments. Day/night presets apply.
  - `rtsp`: commercial IP cameras, ffmpeg with `-c:v copy` (never
    re-encode video on the Pi), audio converted to AAC, MP4 segments.
- Uploads rotate between several Backblaze accounts, one account per
  calendar day (`CloudRotationService`, state in
  `runtime/cloud_rotation_state.json`). A past day's account never
  changes. The downloader must look in every account for a day.
- Keep the B2 object layout `camN/YYYY/MM/DD/HH/cam_N_YYYY_MM_DD_HH_MM_SS.<ext>`.
  Another project downloads these objects.
- Do not auto-restart the shared camera power relay because one camera
  fails.

## Live view

- Browser live view is served by go2rtc, a separate systemd service on
  the Pi installed once with `scripts/install_go2rtc.sh`. The backend
  writes `runtime/go2rtc.yaml` from the camera list and restarts go2rtc
  through a sudoers rule. Do not re-encode video for live view.
- The player is go2rtc's `video-rtc.js`, vendored under
  `frontend/src/vendor`. Update it from a pinned go2rtc tag, never edit
  it by hand.

## Relay rules that are deliberate

- Relay ON/OFF means the relay coil, not the appliance. Some appliances
  are wired through normally closed contacts, so relay OFF can mean
  powered. Do not add appliance-state tracking.

## Downloader (`downloader/`)

A separate local app, not run on the Pi: Python FastAPI + b2sdk backend and a
React UI, started with `uv run visdcam-downloader` from `downloader/`. It
browses, downloads, joins, archives and time-lapses the clips the Pi uploads.
It has its own `pyproject.toml`, `.venv`, `frontend/` and gitignored
`runtime/`. See `downloader/README.md`. Clip names carry the clip END time.

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
```
