# Decisions

The living list of what the owner has decided and why. A new session (any
AI assistant or a person) reads this before proposing anything. Do not
reopen a decision here unless the owner brings it up. When a new decision
is made, add it here with the date, in plain words.

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
| Cloud upload is tried once, then the clip is deleted, no retry queue | RAM is finite and the system drive must not be written to. The disk copy is the primary recording and holds everything; the cloud is the backup. Accepted with it: an internet outage leaves a gap in the cloud copy for that time. Failed uploads are counted per camera in the UI |
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

### Interrupting on purpose (23 Nov 2026)

Video calls sometimes break up. The owner used to press Stop Recording
during a call and then forget to start it again, so there are now four
buttons, and three of them end by themselves.

| Button | What it does | When to use it |
|---|---|---|
| Stop Recording | Stops every recorder until Start Recording | Maintenance; the only one that does not end by itself |
| Stop recording for N min | The same, and recording starts again by itself | When everything must be quiet for a while |
| Pause uploads, upload the clips afterwards | Only the uploads wait; clips are kept in RAM and uploaded at the end | A call, when the cloud copy should stay complete |
| Pause uploads, skip the clips | Only the uploads stop; the cloud clips of that time are deleted | A call, when a burst of uploads afterwards is not wanted |

| Decision | Reason |
|---|---|
| The two pauses never stop a recorder | Only the uploads share the internet line with a call. The disk copy, the primary recording, must go on |
| In the pause that uploads afterwards, the waiting clips have a size limit (200 MB by default) and give way before the disk copy runs short of RAM | The same RAM holds the clips waiting for the disk; the disk copy comes first |
| The pause that skips the clips leaves a gap in the cloud copy; accepted | The disk copy has that time in full quality |
| The lengths are set in the UI: one for both pauses, one for the timed stop (20 minutes each by default) | The owner's choice per situation |
| A backend restart ends a pause or a timed stop | A forgotten interruption must never outlive a restart |

## Router

| Decision | Reason |
|---|---|
| The main router is power-cycled once a night, at the moment the day's Backblaze account changes (just after midnight), through the `router_power` relay (23 Nov 2026) | For the router's own health. Midnight is the safest time: streets still active, no office calls (the owner works 2 PM to 10 PM, sometimes 11 PM), thefts have happened around 1 AM |
| About two minutes without recording on all cameras during that restart is accepted (23 Nov 2026) | Every camera reaches the Pi through the router's own ports |
| No separate network switch on the roof (23 Nov 2026) | Considered and declined by the owner; the nightly gap is acceptable to him |
| Power off 30 seconds, then hold uploads at least 1 minute (owner's figures); after that wait until the internet answers, 5 minutes at most (23 Nov 2026) | A fibre router can need more than a minute; an upload that fails is deleted, not retried |
| The restart runs only in the hour after midnight; if the Pi was off at midnight that night is skipped (23 Nov 2026) | The internet must never be cut during the day or the owner's office hours |
| Uploads in progress finish first and the others wait in RAM, so no cloud clip is lost beyond the recording gap | |
| The Main Router card has a "Restart router" button: the Pi cuts the power and brings it back by itself after the nightly restart's off time, 30 seconds (25 Nov 2026) | Relay ON for the router is a kill switch: with the router off, no phone or computer can reach the Pi to switch it back, though the Pi keeps running |
| That button only switches the relay; uploads are not held (25 Nov 2026) | Owner's choice, the simple way. Accepted with it: cloud clips that finish while the router is starting fail and are deleted |
| The plain Relay ON and Relay OFF buttons for the router stay, in a red box, and Relay ON asks first (25 Nov 2026) | The danger must be evident, and a slip of the finger must not cut the router |

## Downloader

- Offers Cloud or Pi disk as the source; no automatic preference.
- No local archive feature (cloud download costs; never wanted).

## Access and testing

| Decision | Reason |
|---|---|
| No login on the Pi page or the downloader | The Pi is reachable only from the home network; port 8000 is not forwarded and nothing is exposed to the internet. The people on that network (family and a tenant) are trusted. A login would add effort and daily inconvenience for no practical gain. Accepted with it: any device on the home network can use the page, including the addresses that edit and run automation scripts and the one that exports the Backblaze accounts to the downloader. Revisit if remote access is ever added or the network gets untrusted users; a passphrase design is kept for that day in `docs/two-tier-storage-plan.md` (Part 1) |
| No automated test suite yet | The design is still changing quickly and a suite would be rewritten with every change. Each change is checked on the real hardware before it is trusted, and the system checks itself while running: every finished clip is probed and discarded loudly if unplayable, per-camera counters and lights show failures, and the update script checks that the service answers. A suite will be added when the design settles |
| A check script written for a change (for example with a simulated disk or relay) is kept in `tests/` | It costs nothing extra once written, and it is the start of the suite |

## Remote access (being explored since 25 Nov 2026)

The owner wants to open the Pi page from anywhere in the world, switch
things from there and watch live view. Nothing is built yet. Decided so
far:

| Decision | Reason |
|---|---|
| It must work on any device in any browser, with nothing to install or set up on that device | The owner's requirement |
| No private-network app on the phones (Tailscale, WireGuard and the like) | With such an app on his phone, his office app and some bank apps complain |
| The way in is Tailscale Funnel, running on the Pi alone (25 Nov 2026) | The Pi keeps a connection open to Tailscale's relay and a browser anywhere reaches the page through it. Free, no domain, nothing on the phone, no router change, and the HTTPS lock is opened on the Pi, not at the relay. Set up with `scripts/install_tailscale.sh` |
| Two things are public: the page with its API, and go2rtc's video connection `/api/ws`. The rest of go2rtc's port stays inside the home network (25 Nov 2026) | go2rtc's own page hands out the stream addresses with the camera logins |
| The Pi's name on Tailscale is `visd-ha` (25 Nov 2026) | The name is listed in a public register of certificates, so it says nothing private. The full address is `visd-ha.tail64b203.ts.net` |
| Tailscale may not change the Pi's name lookups (`--accept-dns=false`) | Recording and uploads must not depend on anything set in Tailscale |
| Tailscale on the Pi alone is acceptable (25 Nov 2026) | Only the app on a phone causes the trouble above |
| No extra spend at all: no paid domain, no rented server (25 Nov 2026) | The owner's condition. A free domain would be acceptable if a dependable one exists |
| No port forwarding, nothing opened inbound on the ZTE router | He wants no way from the internet into the home network. The line has no fixed public address either |
| No login while this is being built; login and other protection are added later | Owner's call. He does not mind much if someone reaches the Pi page. What he does mind is anyone reaching the Mac or other devices on the home network |

Still open: the sub stream as the default from outside, keeping script editing and the
Backblaze export away from outside visitors, and the login.

The "No login" row under Access and testing describes the Pi before the
install script has been run. Once it has, the page is reachable from the
internet without a login, by the owner's choice above.

## Android app (23 Nov 2026)

The owner wants one tap on the phone to show the four cameras, without
opening Chrome and typing the Pi's address. The app is in `android/`.

| Decision | Reason |
|---|---|
| The app shows the same page the Pi serves and adds nothing of its own | A dead simple app; a change to the page needs no new APK |
| It opens on Live View, through `?tab=live` in the address | The page honours a tab named in the address; without it the page starts on the relays as before |
| The Pi's address is a setting in the app, `192.168.1.31:8000` by default | The owner wants to be able to change it. Accepted with it: the app is allowed plain HTTP with any address, because a rule for one address cannot follow a setting |
| Internet is the only permission | As few permissions as possible |
| It installs on Android 8 and newer | It must also run on older phones in the family |
| It tries the home address first, then the Pi's Tailscale address, then shows the address screen, where either address can be changed and is used from then on (25 Nov 2026) | The owner wants one app that works at home and away without choosing. Until 25 Nov it worked on the home Wi-Fi only |
| The Tailscale address is written in the app's source as the default (25 Nov 2026) | Owner's choice: no typing on any phone. It replaces the earlier choice to keep the address out of the repository |
| Built on the Mac with JDK 17 and the Android command-line tools, no Android Studio, no Gradle | One Java file with no libraries does not need them |
| The APK is not committed; it is built from source and copied to the phone | |
| The name shown for the Pi page and the app is `visd-HA` | The page title used to be "frontend" |
| Live View always starts with the sound off on every camera, in the app and in a browser; the speaker button on a video turns it on | Four cameras speaking at once when the app opens is not wanted. A browser usually silenced them by itself; the app did not |

## Decided against

- Buying the official Pi power supply (the 45 W charger copes).
- Appliance-state tracking for relays (relay ON/OFF means the coil).

## Deferred, not rejected

- 30-second clips (with upload limit 2000 KB/s and waiting-clip cap 20).
  If done, the downloader must infer clip length per day.
- Renaming `archive` identifiers to `disk_copy`.
- A heatsink or fan for the Pi.
