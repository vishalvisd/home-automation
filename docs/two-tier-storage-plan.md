# Two-tier CCTV storage plan

Status: draft for owner review, 2026-11-15. Nothing in this document is
implemented yet.

## Goal

- Full-quality video with audio from every camera is kept at home on an
  external USB disk for about 10 days.
- A smaller copy with audio goes to Backblaze B2 as evidence insurance, so
  that footage survives the Pi or the cameras being destroyed.
- Cloud uploads rotate between several B2 accounts, one account per day,
  so that most of the storage stays inside each account's free 10 GB.
  A small bill on heavy days is acceptable.
- The downloader keeps working, now across all accounts.
- Both web UIs get a simple passphrase login.

## Decisions already taken by the owner

| Topic | Decision |
|---|---|
| Cloud copy | camera sub stream, audio kept as AAC 24 kbps mono |
| Local archive | camera main stream, audio kept, on the USB HDD, ~10 days |
| Sub stream quality | tuned for picture, roughly 12 to 15 GB a day for three cameras |
| Rotation | one B2 account per calendar day (Asia/Kolkata), next account in the list each new day |
| Bucket lifecycle | stays 3+1 days in every bucket; a fifth account removes the overlap |
| Account list | kept only on the Pi, served to the downloader over the Pi API |
| Login | one passphrase for the Pi UI, same passphrase typed into the downloader UI, remembered by the browser, logout clears it |
| Caching | the downloader does not cache the account list; it pulls it on every operation |
| Spending cap | none; owner watches the bill |
| Re-encoding | never on the Pi; both tiers are stream copies |

## Part 1. Passphrase login

### Pi backend

- New runtime file `runtime/auth.json` (mode 0600) holding a salted hash of
  the passphrase (PBKDF2-SHA256). The passphrase itself is never stored.
- First run: if the file does not exist, the UI shows a "set passphrase"
  screen instead of a login. Setting it creates the file. After that the
  only way to change it is the Pi's shell (delete the file) or a
  "change passphrase" form that asks for the old one.
- Every request under `/api/` must carry the header `X-Passphrase`.
  Wrong or missing gives `401`. `GET /health` and the static frontend stay
  open so the update script's health check keeps working.
- One exception discussed below: `GET /api/cloud/accounts` returns the
  application keys. It is the only endpoint that ever returns a secret,
  and it is protected like every other one.

### Pi frontend

- A login page: passphrase field, "Remember on this device" is always on.
- The passphrase is saved in browser `localStorage`, which survives closing
  the browser and is shared by all tabs of the same site. A new device
  must enter it once.
- Every API call sends the header. A `401` sends the user back to the login
  page.
- A Logout button in the header clears the stored passphrase.

### Downloader

- Settings page loses the bucket, key ID and application key fields and
  gains two: Pi address (default `http://192.168.1.31:8000`) and the
  passphrase.
- The passphrase is stored in the browser's `localStorage`, the same way,
  and sent to the downloader backend with each request. The backend uses
  it to pull the account list from the Pi. Logout clears it. Nothing in
  the downloader runs without a browser tab open, so the backend never
  needs to store the passphrase.
- The downloader's local archive feature (mirroring B2 to a Mac disk on a
  schedule) is removed: downloads from B2 cost money and the USB disk on
  the Pi now holds the full-quality copy. The Archive tab, the archive
  service and its runtime state go away.

## Part 2. Several B2 accounts, rotated by day

### Account list on the Pi

`runtime/backblaze_credentials.json` changes from one key pair to a list:

```json
{
  "accounts": [
    {"name": "eu",      "key_id": "0030...", "application_key": "...", "bucket": "visd-cctv-eu",      "enabled": true},
    {"name": "eu-10r",  "key_id": "003f...", "application_key": "...", "bucket": "visd-cctv-eu-10r",  "enabled": true},
    {"name": "eu-06",   "key_id": "0037...", "application_key": "...", "bucket": "visd-cctv-eu-06",   "enabled": true},
    {"name": "ue-10g",  "key_id": "0055...", "application_key": "...", "bucket": "visd-cctv-ue-10g",  "enabled": true}
  ]
}
```

- The existing single key pair and the `b2_bucket` setting are migrated
  into the first row on first start, so nothing stops working during the
  upgrade.
- The region of an account does not matter to the code: b2sdk discovers it
  when it authorises. Account 4 (US East) is simply slower from India.
- Pi UI: a table with add, edit, remove and enable rows. Application keys
  are entered once and shown masked afterwards.

### Choosing the account for a clip

- New runtime file `runtime/cloud_rotation_state.json`, a short map from
  date to account name, for example
  `{"2026-11-15": "eu", "2026-11-16": "eu-10r"}`. Entries older than
  14 days are pruned.
- Each clip already has a date: the Asia/Kolkata date of its close time,
  the same date used in the object path `camN/YYYY/MM/DD/...`.
- Rule: if the clip's date is in the map, use that account. If it is a new
  date, take the latest date in the map, find its account in the enabled
  list, step to the next enabled row (wrapping to the top), record it for
  the new date, and use it. If the map is empty, use the first enabled
  row.
- Consequences: no two consecutive days share an account; adding a row
  adds a stop on the cycle; disabling or removing a row is skipped; a clip
  that closes just before midnight but uploads after it still goes to the
  right day's account; past assignments never change.
- The Pi UI shows today's account and the recent map, and the status API
  exposes the same.

### Upload throttle

- Today each upload is throttled on its own, so three cameras uploading at
  once use three times the setting. The limit becomes one shared budget
  for all uploads.
- The setting is renamed to make its unit clear: kilobytes per second.

### Pi API additions

| Endpoint | Purpose |
|---|---|
| `GET /api/cloud/accounts` | full list including application keys, for the downloader |
| `PUT /api/cloud/accounts` | save the list from the Pi UI |
| `GET /api/cloud/rotation` | today's account and the recent date map |

## Part 3. Downloader across accounts

- The B2 client becomes a set of clients, one per enabled account, built
  from the list pulled from the Pi. B2 sessions are reused in memory while
  the process runs; the list itself is fetched again from the Pi on every
  user action, as decided.
- For a requested day the downloader asks every account for the
  `camN/YYYY/MM/DD/` prefix in parallel and merges the result. Each clip
  remembers which account it came from, so download, preview, join and
  time-lapse fetch it from the right place.
- Browse shows the account name next to each day for information.
- Clip naming, join logic and time-lapse are untouched.

## Part 4. Sub stream to the cloud

- Each camera gets a second URL in the Pi settings:
  - `stream_url` stays as it is and becomes the cloud (sub stream) URL;
  - `archive_stream_url` is new, the main stream for the HDD.
  This keeps existing `cameras.json` files valid.
- The cloud recorder is unchanged apart from audio: AAC 24 kbps mono.
- Camera-side settings, done by the owner in each camera's own UI, before
  the switch:

  | Camera | Sub stream path | Suggested |
  |---|---|---|
  | Trueview cam1 | `/ch0_1.264` | 800x448, 10 fps, variable, 384 kbps ceiling |
  | Tekzor cam2 | `/live/0/SUB` | 800x448, 10 fps, variable, 384 kbps ceiling, H.265 |
  | Hikvision cam3 | `/Streaming/Channels/102` | 640x360 or nearest, 10 fps, variable, 384 kbps ceiling, I-frame 20 |

  At these settings each camera sends roughly 4 to 4.5 GB a day, 12 to
  14 GB for the three, which is the range the owner chose.

## Part 5. Archive tier on the USB disk

- The disk is formatted ext4 with the label `cctv` and mounted at
  `/mnt/cctv` through `/etc/fstab` with `nofail`, so a missing disk does
  not stop the Pi from booting. The owner runs these commands from steps
  this plan will provide.
- New settings: `archive_enabled`, `archive_directory` (`/mnt/cctv`),
  `archive_days` (10), `archive_min_free_gb` (5).
- A second ffmpeg recorder per camera, same class as the cloud one, reads
  `archive_stream_url` and writes 3-minute MP4 segments straight to
  `/mnt/cctv/camN/YYYY/MM/DD/cam_N_YYYY_MM_DD_HH_MM_SS.mp4`, the same
  layout as B2. Video and audio are copied; nothing is uploaded or deleted
  after the segment closes.
- Safety: the archive recorder refuses to start unless `archive_directory`
  is a real mount point. This is what keeps continuous video off the boot
  pen drive if the disk is unplugged.
- A sweeper thread runs hourly: delete files older than `archive_days`,
  and if free space drops below `archive_min_free_gb`, delete the oldest
  files until it recovers.
- Power: the 2.5-inch disk is tried on the Pi's own USB first. If it
  drops out under load, the fallback is a separate pen drive for video.
- The UI shows archive state per camera, disk free space and the oldest
  day kept.

## Part 6. Small fixes picked up on the way

- `CameraRecorderService` forgets recorders whose key is no longer in the
  settings, so a reused key no longer shows the previous camera's error.
- README camera table and defaults updated: three RTSP cameras, ESP32-CAM
  support kept but no longer the default.
- `scripts/find_camera.py` committed as a desk tool, with a short note in
  the README.

## Order of work

Each step is one commit, deployed with `scripts/update_pi.sh`, and verified
before the next starts.

1. Passphrase login on the Pi API and UI.
2. Account list and day rotation on the Pi, still uploading the main
   streams. Verified by watching the first midnight switch.
3. Downloader: pull accounts from the Pi, browse and download across
   accounts, passphrase in its UI, archive feature removed.
4. Sub stream to the cloud, after the owner sets the three cameras' sub
   streams and checks them in VLC.
5. Archive tier, after the disk is mounted on the Pi.
6. Small fixes and documentation.

## Open question for the owner

Order: is it acceptable that steps 2 and 3 upload main streams, so the
first few rotated days exceed 10 GB per account, until step 4 lands? The
alternative is to do step 4 first, which only needs the camera sub streams
set and a URL change per camera.
