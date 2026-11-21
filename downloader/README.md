# visdcam downloader

A small local app for the CCTV clips the Raspberry Pi uploads to Backblaze B2.
It runs on your Mac or Windows computer and opens in the browser. It can:

- browse the clips by camera and day and preview any 3-minute clip;
- download a time window and join the clips into one video, with audio;
- make time-lapse videos from any downloaded file, using the hardware encoder.

Clips come from one of two sources, chosen with the switch at the top of
the Browse tab and remembered by the browser:

- **Cloud (Backblaze)**: the small sub-stream clips the Pi uploads. The Pi
  rotates its uploads between several Backblaze accounts, one account per
  calendar day, and is the only place the account list lives.
- **Pi disk**: the full-quality main-stream clips on the USB disk attached
  to the Pi, read through the Pi's API (`/api/cameras/archive/...`).
  Browsing wakes the disk; the Pi parks it again a few minutes after the
  last request. Downloads come over the home network.

A download job takes all its clips from the source chosen when it was
started, so one joined file is never a mix of the two qualities.

About the cloud source: the Pi This app
fetches that list from the Pi (`/api/cameras/backblaze/accounts/export`) on
every browse or download, asks every account in parallel, and merges the
results. It keeps no copy of the keys.

It lives in the `downloader/` folder of the home-automation repository but is
a separate program. The Pi never runs it.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- ffmpeg on the PATH, or its location set in Settings.
  Mac: `brew install ffmpeg`. Windows: `winget install ffmpeg`.
- The Pi reachable on the home network.

## Run

```bash
cd downloader
uv sync --frozen
uv run visdcam-downloader
```

The browser opens at <http://127.0.0.1:8800>. Stop it with Ctrl+C.
Add `--no-browser` to skip opening the browser, `--port 9000` to change the port.

On first start go to Settings, check the Pi address, save, and press
Test Accounts. It lists every account the Pi knows and whether it answers.

## Where things are stored

Everything local lives under `downloader/runtime/`, which is gitignored:

```
runtime/
├── settings.json        Pi address, folders (owner-only on Mac/Linux)
├── jobs.json            job history
├── preview_cache/       clips played in the Browse tab (capped at 1 GB)
└── tmp/                 clips being downloaded for a join; cleared after each job
```

Joined videos and time-lapses go to the output folder, by default
`~/Movies/visdcam` on Mac and `~/Videos/visdcam` on Windows.

## How clips are named

The Pi uploads `camN/YYYY/MM/DD/HH/cam_N_YYYY_MM_DD_HH_MM_SS.<ext>` where the
time is Asia/Kolkata and is the moment the clip was *closed*. A clip therefore
covers roughly the 180 seconds before that time. The app uses the "Clip length
on the Pi" setting to work out the start, so a window starting at 10:00 really
starts at 10:00.

ESP32-CAM cameras produce `.ts` (MPEG-TS, H.264, no audio). RTSP cameras
produce `.mp4` (H.265 or H.264 with AAC audio). A window must be on one side of
a camera change; mixing the two types is refused.

## Joining

- `.ts` clips are concatenated byte by byte. MPEG-TS allows that.
- `.mp4` clips are joined with ffmpeg's concat demuxer and `-c copy`, so
  nothing is re-encoded and the audio is kept.

Output name: `cam3_2026-11-13_10-00-00_60min.mp4`.

## Time-lapse

Speed 1x only converts the file to MP4 (useful for `.ts` files) and keeps the
audio. Higher speeds drop the audio and use the first encoder that works from
this list: `h264_videotoolbox` / `hevc_videotoolbox` on Mac; `nvenc`, `qsv` or
`amf` on Windows; `libx264` / `libx265` as the software fallback.

## Layout

```
downloader/
├── pyproject.toml
├── src/visdcam_downloader/
│   ├── __main__.py           starts Uvicorn and opens the browser
│   ├── config.py             paths and the Settings model
│   ├── api/                  FastAPI app and routes
│   └── services/
│       ├── b2_client.py      b2sdk wrapper that understands the folder layout
│       ├── clips.py          clip-name parsing and window selection
│       ├── joiner.py         .ts concatenation / .mp4 ffmpeg concat
│       ├── timelapse.py      remux and speed-up with encoder fallback
│       ├── ffmpeg_tools.py   find and run ffmpeg/ffprobe with progress
│       ├── job_service.py    one-at-a-time background job queue with history
│       └── workflows.py      download and timelapse jobs
└── frontend/                 React + Vite + Tailwind; dist/ is committed
```

## Frontend changes

```bash
cd downloader/frontend
nvm use
npm install
npm run build
```

Commit `downloader/frontend/dist`. The backend serves it as static files.
