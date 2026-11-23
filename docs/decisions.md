# Decisions

The living list of what the owner has decided and why. A new session (any
AI assistant or a person) reads this before proposing anything. Do not
reopen a decision here unless the owner brings it up. When a new decision
is made, add it here with the date, in plain words.

The dated files in `docs/context/` are the history of how each decision was
reached. This file is the current state.

## How we work

- **Everything comes from the repository.** Code goes Mac -> GitHub -> Pi
  (`bash scripts/update_pi.sh`). Nothing is changed on the Pi by hand.
- **The rebuild rule.** If the Pi's system USB drive dies, a new drive must
  be brought to the same state quickly from this repository alone. So any
  step that has to be done on the Pi outside `update_pi.sh` is either a
  script in `scripts/` or is written down in `SETUP_PI.md` under "Steps
  outside the update script". A manual step that is not written there is a
  bug. The same goes for settings made outside the Pi (camera web pages,
  router bindings): they are written in `docs/hardware-and-network.md`.
- **Ask before changing code logic or Pi settings.** Summarise, agree,
  then implement. The owner makes design and logic decisions. Documentation
  files (this one, `CLAUDE.md`, `README.md`, `SETUP_PI.md`, `docs/`) may be
  updated without asking.
- **Commands on the Pi are run by the owner.** Give him the exact command
  and wait for the output. SSH from the Mac (`ssh pi`) exists for reading.
- **One step at a time** for hands-on work. Plain language. Numbers in
  tables. Honest feedback, including when an earlier choice was wrong.
- **Secrets never in chat or in git.** Camera passwords and Backblaze keys
  are typed by the owner into the Pi UI and live only under `runtime/`.
- Commit messages: one short lowercase line. No `Co-Authored-By`. The owner
  pushes to GitHub himself.

## Words

- **Disk copy**: the full-quality recording on the USB disk. It is the
  primary recording.
- **Cloud copy**: the small sub-stream recording in Backblaze. It is the
  backup against theft, sabotage or disk failure.
- Never call the disk copy "archive" in UI text or prose. The word remains
  only in code and settings names (`archive_*`, `ArchiveService`).

## Recording

| Decision | Reason |
|---|---|
| Disk copy = main stream, cloud copy = sub stream with audio, live view = main stream with a Main/Sub switch | Full quality at home, small uploads |
| Video is never re-encoded on the Pi (`-c:v copy`) | CPU and heat; no fan |
| Clips are recorded to RAM (`/dev/shm`), never to the system drive | Wear on the USB pen drive |
| No buffering through the system drive either | Same reason; RAM batches instead |
| The USB disk rests (parked) between batches and never spins all day | The owner wants the disk to last |
| No day limit on the disk; delete the oldest day when free space is under `archive_min_free_gb` | "Fill the disk" is simplest |
| **No recording may be dropped while RAM has room** (22 Nov 2026) | Stated by the owner when the fourth camera was added. No size limit drops a waiting clip; only a nearly full RAM disk does (`archive_buffer_reserve_mb`), oldest clip of all cameras first |
| The disk rests as long as RAM allows; batches run on the timer, early batches are only a safety net (22 Nov 2026) | 4 GB of RAM is there to be used |
| Clips waiting in RAM are lost on a sudden power cut or crash; accepted (22 Nov 2026) | The UPS covers short cuts; the cloud copy remains |
| Every camera: main stream to the disk, sub stream to the cloud, whatever the camera's bitrates are | Bitrates are tuned on the camera's own page, any time |
| The day's cloud copy of all cameras together must stay under 10 GB | One free account per day |
| An open RTSP stream on the LAN (cam4 has no stream login) is not a concern (22 Nov 2026) | Owner's call |
| Cloud upload is tried once, then the clip is deleted, no retry queue | RAM is finite; the disk copy is the primary |
| No speed-up or time-lapse on the Pi | CPU; done in the downloader on the Mac |
| The shared camera power relay is never restarted automatically | One failing camera must not cut the others |

### Disk rest study (started 23 Nov 2026, temporary)

The owner wants to see for a few days when the disk is woken, how long it
runs and when it is parked. "Log disk activity" in the Disk copy tab writes
this to `runtime/disk_activity.csv` on the system drive (accepted for the
length of the study). `GET /api/cameras/archive/activity` gives the lines
and a summary per day. When the analysis is done the switch is turned off;
the code stays, the file can be deleted. If the sleep check finds the disk
awake by itself, it is only written down, not parked again: what to do
about it is the owner's decision once there is data.

## Cloud accounts (Backblaze B2)

| Decision | Reason |
|---|---|
| Several free accounts, one account per calendar day (Asia/Kolkata) | Each account has 10 GB free |
| A past day's account never changes; the downloader searches every account | Clips must stay findable |
| No automatic switch when an account refuses uploads | It would confuse the downloader. Manual way: untick the account in the UI |
| Bucket lifecycle stays 3 days till hide + 1 till delete | Add accounts rather than shorten it |
| No $0 spending cap; a small bill is accepted | Caps caused silent loss on 20 and 21 Nov 2026 |
| Object layout `camN/YYYY/MM/DD/HH/cam_N_YYYY_MM_DD_HH_MM_SS.<ext>` is fixed | Another project downloads these objects |

## Router

| Decision | Reason |
|---|---|
| The main router is power-cycled once a night, at the moment the day's Backblaze account changes (just after midnight), through the `router_power` relay (23 Nov 2026) | For the router's own health. Midnight is the safest time: streets still active, no office calls (the owner works 2 PM to 10 PM, sometimes 11 PM), thefts have happened around 1 AM |
| About two minutes without recording on all cameras during that restart is accepted (23 Nov 2026) | Every camera reaches the Pi through the router's own ports |
| No separate network switch on the roof (23 Nov 2026) | Considered and declined by the owner; the nightly gap is acceptable to him |
| The restart is not a way to give each Backblaze account a different public address | See "Decided against" |
| Power off 30 seconds, then hold uploads at least 1 minute (owner's figures); after that wait until the internet answers, 5 minutes at most (23 Nov 2026) | A fibre router can need more than a minute; an upload that fails is deleted, not retried |
| The restart runs only in the hour after midnight; if the Pi was off at midnight that night is skipped (23 Nov 2026) | The internet must never be cut during the day or the owner's office hours |
| Uploads in progress finish first and the others wait in RAM, so no cloud clip is lost beyond the recording gap | |

## Downloader

- Offers Cloud or Pi disk as the source; no automatic preference.
- No local archive feature (cloud download costs; never wanted).

## Decided against

- Buying the official Pi power supply (the 45 W charger copes).
- Appliance-state tracking for relays (relay ON/OFF means the coil).

## Deferred, not rejected

- Passphrase login for the Pi UI and the downloader. Until then the
  account export endpoint and the camera addresses are open on the LAN.
- 30-second clips (with upload limit 2000 KB/s and waiting-clip cap 20).
  If done, the downloader must infer clip length per day.
- Renaming `archive` identifiers to `disk_copy`.
- A heatsink or fan for the Pi.
