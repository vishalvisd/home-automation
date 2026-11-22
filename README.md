Raspberry Pi Home Automation

Home automation and CCTV system running on a Raspberry Pi 4. The project combines direct relay control, scheduled solar-panel cleaning and plant watering, editable Python automation scripts, and resilient CCTV recording/upload to Backblaze B2.

This README is intentionally detailed. It is the main architecture/reference document for future development and for giving a new developer or LLM enough context to work on the repository without rediscovering the hardware and design decisions.

Current status

As of 2026-11-13, the following are implemented and working:

FastAPI backend on Raspberry Pi.

React/Vite/Tailwind frontend served by FastAPI.

Raw control of the physical relay channels.

Scheduled and manual solar-panel cleaning / plant watering.

Editable standalone Python automation scripts.

CCTV recording from ESP32-CAM MJPEG streams (GStreamer) and from commercial RTSP cameras (ffmpeg, stream copy), side by side.

Independent camera-stream reconnect handling for unstable home networking.

Configurable wall-clock CCTV segment duration.

Automatic per-camera Day/Night preset control with configurable times and persistent applied-preset state.

H.264/MPEG-TS recording to RAM-backed temporary storage.

Backblaze B2 upload through the native b2sdk Python SDK.

Rate-limited uploads.

One-shot upload semantics: upload once, then delete the local segment whether upload succeeds or fails. A per-camera cap on waiting segments stops RAM filling up when uploads fall behind.

systemd auto-start/restart for the FastAPI/Uvicorn process.

Safe Raspberry Pi setup and update scripts.

Tabbed frontend navigation for Relay Controls, CCTV Cameras, Panel Cleaning and Plant Watering, and Automations.

Any deliberately deferred items are documented in Known pending work.

Design principles

Several decisions in this project are deliberate and should not be casually replaced with more abstract frameworks.

Relay commands are raw relay-coil commands. ON means energise the relay coil; OFF means release it. The backend does not infer or persist appliance state.

Electrical contact semantics remain explicit. Some appliances use normally closed contacts and therefore remain powered while their relay is OFF.

Python owns application scheduling and workflows. systemd is used only to keep the web/backend process alive at boot; it is not the watering/automation scheduler.

Automation playbooks remain simple standalone Python scripts. Do not introduce a workflow engine or state-machine framework without a strong reason.

The React production build is made on macOS, not on the Raspberry Pi. frontend/dist is committed and deployed with Git.

CCTV must tolerate an unreliable home network. A temporary camera-stream failure must not kill the long-lived recorder.

Missing camera frames are skipped, not fabricated. Do not duplicate/freeze frames to hide outages.

Failed CCTV uploads are not retried. Each completed segment is attempted once and then deleted from RAM. Nothing is ever kept locally.

Video from commercial RTSP cameras is never re-encoded on the Pi. ffmpeg copies the camera's own H.264/H.265 stream; only the audio is converted to AAC.

Do not power-cycle the shared camera power line automatically because one camera fails. A shared restart would interrupt a healthy camera.

High-level architecture

Browser
  |
  | HTTP
  v
FastAPI / Uvicorn on Raspberry Pi
  |
  +-- React production frontend (frontend/dist)
  |
  +-- Relay API --------------------> gpiozero ----> 12 V relay board
  |
  +-- Watering service -------------> relay commands
  |      +-- Python scheduler
  |
  +-- Automation script service ----> standalone runtime Python scripts
  |
  +-- Camera subsystem
         |
         +-- CameraPresetService ----> ESP32 control API :8080/day or /night
         |      +-- 30-minute check loop
         |      +-- runtime/camera_preset_state.json
         |
         +-- CameraRecorderService (supervisor, picks a recorder per camera)
         |      |
         |      +-- source_type = esp32_mjpeg
         |      |      ESP32-CAM MJPEG stream
         |      |        -> reconnectable CameraStreamSource (JPEG frames)
         |      |        -> CameraRecorder (x264 encode)
         |      |        -> H.264 / MPEG-TS .ts segments
         |      |
         |      +-- source_type = rtsp
         |             commercial IP camera RTSP stream
         |               -> RtspFfmpegRecorder (ffmpeg child process)
         |               -> video copied as-is, audio to AAC
         |               -> MP4 segments
         |                           |
         |                           v
         |                    /dev/shm/... (RAM)
         |                           |
         |                           v
         +-------------------- CameraUploadService
                                     |
                                     v
                              CameraStorageProvider
                                     |
                                     v
                              Backblaze B2

Technology stack

Raspberry Pi

Raspberry Pi 4 Model B.

Raspberry Pi OS Lite 64-bit.

Debian 13 / trixie.

Python 3.13.x.

uv for Python dependency/environment management.

FastAPI.

Uvicorn.

gpiozero for General-Purpose Input/Output (GPIO).

GStreamer 1.x for ESP32-CAM capture/encoding/segmenting.

ffmpeg for RTSP camera recording (stream copy, no re-encoding).

PyGObject (gi) for Python GStreamer bindings.

b2sdk for Backblaze B2.

Frontend

React.

JavaScript.

Vite.

Tailwind CSS.

The Raspberry Pi does not run a Node.js production server. FastAPI serves the compiled static frontend from frontend/dist.

Repository layout

The important repository areas are:

home-automation/
├── automation_templates/       # Factory/default standalone automation scripts
├── frontend/
│   ├── src/                    # React source
│   └── dist/                   # Production build; committed and deployed to Pi
├── runtime/                    # Runtime settings/state/secrets; gitignored
├── scripts/
│   ├── setup_pi.sh             # Fresh Pi setup
│   ├── update_pi.sh            # Normal safe deployment/update
│   ├── install_service.sh      # Writes the systemd unit (called by setup, rerun when it changes)
│   ├── install_go2rtc.sh       # One-time go2rtc install for live view
│   ├── install_archive.sh      # One-time USB archive disk setup
│   ├── find_camera.py          # Desk tool: find a camera on the LAN, get its RTSP URL
│   └── test_relays.py          # Sequential relay hardware test
├── src/home_automation/
│   ├── api/
│   │   ├── app.py
│   │   ├── dependencies.py
│   │   └── routes/
│   ├── config/
│   └── services/
├── README.md                   # This architecture/reference document
└── SETUP_PI.md                 # Intentionally short human setup instructions

runtime/ must remain outside version control because it contains machine-specific settings, schedule state, editable runtime scripts, and Backblaze credentials.

Backend architecture

Application lifecycle

home_automation.api.app:app creates all long-lived services during the FastAPI lifespan.

Startup creates:

RelayManager

WateringSettingsService

WateringService

WateringSchedulerService

AutomationScriptService

CameraSettingsService

CameraPresetService

BackblazeCredentialsService

BackblazeB2StorageProvider

CameraUploadService

CameraRecorderService

The watering scheduler and camera preset service start automatically. The camera preset service waits 30 seconds after backend startup before its first control request, then checks every 30 minutes. CCTV recording starts automatically only when persisted camera settings have recording_enabled=true.

Shutdown order is deliberate:

stop camera recorders;

stop the camera preset service;

wait for camera uploader workers;

stop watering scheduler;

safely stop watering service;

release GPIO resources.

Runtime files

Runtime configuration is stored beneath runtime/.

runtime/
├── watering.json
├── watering_schedule_state.json
├── cameras.json
├── camera_preset_state.json
├── backblaze_credentials.json
├── cloud_rotation_state.json
├── go2rtc.yaml
└── automations/
    ├── restart_router.py
    ├── restart_cameras.py
    └── restart_router_and_cameras.py

The services create missing runtime files/directories as needed and use atomic temporary-file replacement where appropriate.

Backblaze credentials are stored with Unix mode 0600 and the credentials API never returns the secret values.

Relay hardware

Relay board behavior

The relay board is a 12 V, 8-channel active-low board:

GPIO LOW  -> relay coil energised -> relay ON
GPIO HIGH -> relay coil released  -> relay OFF

The Raspberry Pi enclosure has separate 12 V DC and 5 V DC power inputs. The relay board itself is 12 V powered.

The software meaning of relay ON and OFF always refers to the relay coil, not the powered appliance.

Fixed mapping

Channel

Device key

Device

T-Cobbler / physical pin

BCM GPIO

Default relay state

Electrical behavior

IN1

ro_power

Reverse osmosis purifier

Row 2 left / pin 3

GPIO 2

OFF

Normally closed contact; relay OFF supplies RO power

IN2

router_power

Main router

Row 3 left / pin 5

GPIO 3

OFF

Normally closed contact; relay OFF supplies router power

IN3

camera_power

Shared camera power line

Row 16 right / pin 32

GPIO 12

ON

Normally open contact; relay ON supplies camera power

IN4

plant_valve

Plant solenoid valve

Row 17 left / pin 33

GPIO 13

OFF

Normally closed solenoid; relay ON opens valve

IN5

main_valve

Main valve

Row 19 left / pin 37

GPIO 26

OFF

Current installation behaves as ON=open, OFF=closed

IN6

pump

Pump control

Row 20 right / pin 40

GPIO 21

OFF

Relay ON activates pump control circuit

IN7

—

Pump second relay contact

physically tied to IN6 signal

GPIO 21

follows IN6

No separate software channel

IN8

valve_power

Valve system master power

Row 18 right / pin 36

GPIO 16

OFF

Relay ON supplies valve-control power

Important pump note

The pump is approximately 1 kW. The intended safe design is that the Raspberry Pi-controlled relay operates a properly motor-rated contactor, with the contactor switching pump power. Do not assume a small relay-board contact is an appropriate long-term motor switch.

Main-valve timing

The current main valve can operate like a solenoid, but the software intentionally retains configurable open and close delays so the system can later use a motorised valve without redesigning the workflow.

Raw relay API

The relay endpoints are intentionally simple:

POST /api/relays/{relay_key}/on
POST /api/relays/{relay_key}/off

No relay state is persisted or inferred.

This is especially important for the router and RO purifier because their normally closed wiring means:

relay OFF != appliance OFF

For example, the router normally has power while router_power relay is OFF.

Watering and solar-panel cleaning

Purpose

A single Python service performs the complete panel-cleaning and plant-watering sequence. It can be triggered manually or by the built-in Python scheduler.

Configurable settings

Settings are stored in runtime/watering.json and include:

schedule enabled/disabled;

run time;

frequency in days;

timezone;

main-valve open delay;

main-valve close delay;

plant-valve open delay;

plant-valve close delay;

solar-panel sprinkler duration;

plant watering duration;

wait after pump stop;

final water-settling delay.

Default timezone is Asia/Kolkata.

Watering sequence

The current sequence is:

1. valve_power ON
2. main_valve ON
3. wait main_valve_open_delay_seconds
4. pump ON
5. wait panel_sprinkler_seconds
6. plant_valve ON
7. wait plant_valve_open_delay_seconds
8. wait plant_watering_seconds
9. pump OFF
10. wait wait_after_pump_stop_seconds
11. plant_valve OFF
12. wait plant_valve_close_delay_seconds
13. wait water_settling_seconds
14. main_valve OFF
15. wait main_valve_close_delay_seconds
16. valve_power OFF

A manual stop requests safe termination. Cleanup always ensures:

pump OFF
valve_power ON while valves are being closed
plant_valve OFF + close delay
main_valve OFF + close delay
valve_power OFF

Cleanup close delays deliberately complete even after a stop request so a motorised valve is not left partway through travel.

Scheduler

WateringSchedulerService is a Python thread inside the FastAPI process. It is not a cron/systemd timer.

The scheduler checks the configured local time, frequency, and persisted last scheduled run date. Its state is stored in:

runtime/watering_schedule_state.json

Manual watering remains allowed even when scheduled watering is disabled.

Watering API

GET  /api/watering/settings
PUT  /api/watering/settings
GET  /api/watering/status
POST /api/watering/start
POST /api/watering/stop

Standalone automation scripts

Automation scripts are intentionally plain Python files rather than workflow definitions.

Configured automations currently include:

restart_router

restart_cameras

restart_router_and_cameras

Factory/default scripts live under:

automation_templates/

Editable runtime copies live under:

runtime/automations/

The frontend/API can:

list scripts;

view source;

edit/save runtime source;

restore a script from its repository template;

execute a script;

display the most recent exit code/output.

The runtime script model is deliberate: scripts must remain directly runnable Python programs that can also be scheduled externally or by future simple Python scheduling logic.

Automation API

GET  /api/automations
GET  /api/automations/{key}
PUT  /api/automations/{key}
POST /api/automations/{key}/restore
POST /api/automations/{key}/run

CCTV subsystem

Camera types

Every camera in runtime/cameras.json has a source_type:

esp32_mjpeg   ESP32-CAM serving MJPEG over HTTP. Uses host, stream_path and
              control_port. Frames are pulled by GStreamer and software-encoded
              to H.264 on the Pi. Output is MPEG-TS (.ts). Day/night presets apply.

rtsp          Commercial IP camera serving H.264/H.265 over RTSP. Uses stream_url,
              the full RTSP URL of the main stream including the camera login
              if it needs one, and optionally sub_stream_url, the camera's
              smaller second stream. ffmpeg copies the video untouched and
              converts audio to AAC. Output is MP4 (.mp4).

              With the archive enabled an RTSP camera has two recorders:
              "cloud" records sub_stream_url (or stream_url when empty) with
              24 kbps mono audio and uploads each clip to Backblaze;
              "archive" records stream_url with 32 kbps audio and keeps each
              clip on the USB disk. Live view always shows stream_url.

Both types run side by side. Cameras can be added and removed from the UI.
The first commercial camera is a Trueview T18296S (H.265 2304x1296 @ 15 fps,
G.711 audio). Its main stream records at roughly 20 MB per 3 minutes; its sub
stream (800x448) at roughly 5 MB. Which one is used is simply the URL in config.

Cameras

As of 2026-11-15 all three cameras are RTSP:

Key

Camera

IP

Streams

cam1

Trueview T18296S (Wi-Fi)

192.168.1.33 (router DHCP binding)

main /ch0_0.264 2304x1296 H.265 + G.711, sub /ch0_1.264 800x448

cam2

Tekzor TZ-1W-IP-NG5SL (wired, 2nd-floor access point)

192.168.1.36 (router DHCP binding)

main /live/0/MAIN 2304x1296 H.265 + G.711, sub /live/0/SUB 800x448

cam3

Hikvision DS-2CD202RF-I (wired, outdoor pole)

192.168.1.64 (static in the camera)

main /Streaming/Channels/101 1080p H.264, sub /Streaming/Channels/102, no audio hardware

The two ESP32-CAM cameras below are retired but the code path stays
supported. The installation started with them:

Key

Host

Stream

Control server

cam1

192.168.1.33

http://192.168.1.33/stream

port 8080

cam2

192.168.1.36

http://192.168.1.36/stream

port 8080

The ESP32 firmware currently produces MJPEG at approximately VGA resolution (640x480). The camera control firmware also has restart/day/night capabilities.

The home network is known to be unstable. The recorder architecture therefore assumes that either camera can disconnect at any time.

Camera settings

Persistent CCTV settings are stored in:

runtime/cameras.json

Important settings include:

recording enabled;

per-camera source type (esp32_mjpeg or rtsp) and its fields;

waiting-segment cap per camera (pending_upload_limit);

configurable segment duration (segment_seconds);

target frame rate;

H.264 bitrate;

RAM recording directory;

recorder restart delay;

per-camera host/path/control port/enabled flag;

Backblaze upload enabled;

Backblaze upload speed limit, shared by all uploads.

Current defaults include:

segment_seconds        = 180
frame_rate             = 15      (ESP32-CAM only)
video_bitrate_kbps     = 1000    (ESP32-CAM only)
recording_directory    = /dev/shm/home-automation/cameras
pending_upload_limit   = 3
b2_upload_rate_kb_s    = 750     (kilobytes per second, one shared budget)

The segment duration remains configurable from the UI. 180 seconds matches the old CCTV implementation's three-minute segment length.

Automatic Day / Night presets

Each camera exposes a small control API on its configured control_port (currently port 8080):

http://<camera-host>:8080/day
http://<camera-host>:8080/night

CameraPresetService applies these presets automatically. It does not query the camera for its current preset because the camera network is unreliable. Instead it stores the last preset that was successfully applied in:

runtime/camera_preset_state.json

The service behavior is deliberately simple:

backend starts
   -> wait 30 seconds so camera streams can settle
   -> determine desired preset from Asia/Kolkata time
   -> compare desired preset with local applied-preset state
   -> if already matching: do nothing
   -> if different/unknown: call /day or /night
       -> success: update local state file
       -> timeout/refused/network failure: leave state unchanged
   -> wait 30 minutes and check again

The default schedule is:

day_mode_time   = 06:00
night_mode_time = 18:00

Both times are stored with the other camera settings in runtime/cameras.json and are configurable from the UI. The UI does not provide a manual Day/Night toggle. It only shows the last successfully applied preset for each camera and allows the Day/Night schedule times to be changed.

A failed preset request is expected to be harmless. The service logs the failure and simply retries on the next 30-minute check. A camera control failure must not stop recording or trigger a shared camera-power restart.

Preset status is exposed through:

GET /api/cameras/preset/status

The response includes the configured Day/Night times, timezone, check interval, desired preset, and the locally recorded applied preset for each camera.

RTSP cameras: RtspFfmpegRecorder

For an rtsp camera the supervisor starts RtspFfmpegRecorder instead of the
GStreamer recorder. It:

1. runs ffprobe once to learn the video and audio codec;
2. starts ffmpeg as a child process with -c:v copy (plus -tag:v hvc1 for
   H.265 so Apple players accept it), audio to AAC 32 kbps unless it is
   already AAC, and the segment muxer cutting MP4 files every segment_seconds;
3. reads ffmpeg's log to learn when each file is finished and hands it to
   CameraUploadService, the same as the ESP32 path;
4. exits if the camera stops sending for 15 seconds (socket timeout), and a
   watchdog kills ffmpeg if no new segment starts for far too long. The
   supervisor then restarts it after recorder_restart_delay_seconds.

Leftover files from a crashed ffmpeg are deleted at the next start because an
unfinished MP4 does not play. Camera passwords in the RTSP URL are masked in
logs and in the status API.

Why the ESP32 camera architecture is split in two

The original direct GStreamer pipeline connected the HTTP source directly to the encoder. When an ESP32 stream disconnected, souphttpsrc could attempt HTTP Range/resume behavior that the ESP32 streaming server did not support, causing the entire recorder pipeline to fail.

The new design deliberately separates network acquisition from video recording.

1. CameraStreamSource

Each camera gets its own reconnectable source:

souphttpsrc
  -> multipartdemux
  -> image/jpeg
  -> appsink

Important behavior:

retries=0: GStreamer does not perform HTTP Range/retry recovery itself.

Python owns reconnects.

The source retries after a short delay.

appsink max-buffers=1 drop=true prevents stale frames building up.

Stream failures update stream_connected, stream_reconnect_count, and last_stream_error.

A camera disconnect does not stop the long-lived recording pipeline.

2. CameraRecorder

Received JPEG buffers are pushed into a separate recording pipeline through appsrc:

appsrc
  -> queue
  -> videorate (drop-only)
  -> jpegdec
  -> videoconvert
  -> x264enc
  -> h264parse
  -> splitmuxsink / mpegtsmux

The output format remains MPEG Transport Stream (.ts) with H.264 video.

videorate is configured to drop excess frames only. It must not generate duplicate frames to hide camera/network outages.

Camera timestamps and missing frames

Network outages must not create huge timestamp jumps inside a recorded clip.

For that reason, the recorder assigns compact media timestamps itself:

frame 1 -> media time 0
frame 2 -> next frame interval
...
network outage -> no frames, media time does not advance
next real frame -> next media interval

This means:

unavailable camera frames simply do not exist in the output;

no frozen or synthetic frames are inserted;

the resulting video contains the usable frames that were actually received.

Wall-clock segment windows

Segment duration is based on wall-clock time, not on the amount of successfully received video.

This is important on an unstable network. A camera should not need 20-30 real-world minutes to accumulate three minutes of received frames before producing a file.

For a configured 180-second segment window:

00:00 - 00:30  frames received
00:30 - 01:20  camera unavailable
01:20 - 01:45  frames received
01:45 - 02:40  camera unavailable
02:40 - 03:00  frames received
--------------------------------
03:00           finalize/upload the usable video received in this window

The Python recorder monitor owns the wall-clock boundary and explicitly asks splitmuxsink to split. Automatic splitmuxsink media-time segmentation is disabled so compact media timestamps and wall-clock segmentation remain independent.

If an entire window receives no frames, no empty video should be uploaded. When frames resume, recording continues normally.

A split may occur slightly after the exact wall-clock boundary because MPEG/H.264 splitting is aligned to a usable video keyframe/group-of-pictures boundary.

Recorder-level recovery

CameraRecorderService owns the desired recording state separately from the instantaneous GStreamer recorder state.

If the recording pipeline itself dies, the service waits for the configured recorder_restart_delay_seconds, starts a new recorder, and only treats the recovery as successful after it remains alive for a confirmation period.

This is separate from ordinary camera HTTP disconnect/reconnect events. Normal stream reconnects should not increment recorder recovery counts or restart the recorder.

Temporary recording storage

Segments are written under:

/dev/shm/home-automation/cameras/<camera-key>/

systemd-logind must not clean /dev/shm: with its default RemoveIPC=yes it
deletes a user's files there when that user's last login ends, which wiped
the whole recording tree whenever an SSH session to the Pi closed.
scripts/install_service.sh sets RemoveIPC=no and enables linger for the
service user. The archive service also recreates its buffer folder on
demand, so a wipe costs at most the clips that were waiting.

/dev/shm is RAM-backed temporary storage on Linux, avoiding normal continuous CCTV writes to the Raspberry Pi SD card.

Do not treat this directory as persistent storage.

Backblaze B2 upload

Cloud upload is intentionally separated behind a generic interface:

CameraUploadService
      |
      v
CameraStorageProvider protocol
      |
      v
BackblazeB2StorageProvider

This allows another storage provider to be added later without rewriting the recorder.

The project uses the native Backblaze b2sdk, not Boto3/S3-compatible upload code.

Upload behavior

For every completed non-empty segment:

segment closes
   -> if upload is disabled: delete the segment immediately
   -> if pending_upload_limit segments are already waiting:
        delete the oldest waiting one without uploading
   -> submit upload
   -> attempt upload exactly once
   -> success: log success
   -> failure: log exception
   -> always delete local segment
   -> move on

There is intentionally no retry queue and no local backup. Segments live in
RAM, so nothing may accumulate.

Upload rate limit

All uploads in progress share one budget of b2_upload_rate_kb_s kilobytes
per second (a token bucket in SharedUploadRateLimiter). Three cameras
uploading at the same time therefore use the configured number in total,
not three times it. This keeps CCTV uploads from taking all upstream
bandwidth.

Accounts and day rotation

Several Backblaze accounts are kept, each with its own bucket, so that
most of the stored footage stays inside each account's free allowance.
They are stored as a list at:

runtime/backblaze_credentials.json      (mode 0600)

{"accounts": [{"name": "eu", "key_id": "...", "application_key": "...",
               "bucket": "visd-cctv-eu", "enabled": true}, ...]}

Every calendar day in Asia/Kolkata goes to one account. CloudRotationService
keeps a small map of date -> account name in runtime/cloud_rotation_state.json.
A clip is routed by the date in its own object path (its close time), so a
clip that closes before midnight and uploads after it still goes to its own
day's account. A new date takes the next enabled account in the list after
the account of the latest known date, wrapping round. Adding an account adds
a stop on the cycle; disabling or removing one is skipped; past days never
move. Each bucket carries a lifecycle rule (currently 3+1 days) so an
account holds about one day of clips when its turn comes round again.

The old single-key file ({"key_id", "application_key"}) plus the b2_bucket
setting are migrated into a one-account list on the first start after the
upgrade.

GET /api/cameras/backblaze/accounts returns the list without application
keys. PUT saves it; a row with an empty application key keeps the key
already stored under that name. POST .../accounts/test authorises one
account and looks up its bucket without uploading, so a wrong key is
caught before that account's day comes. GET /api/cameras/backblaze/rotation
shows today's account and the recent map.

The downloader currently knows one account only; browsing days that went
to other accounts is the next change.

B2 object naming

The downstream system depends on the existing object layout, so preserve it:

cam1/YYYY/MM/DD/HH/cam_1_YYYY_MM_DD_HH_MM_SS.ts     (ESP32-CAM)
cam3/YYYY/MM/DD/HH/cam_3_YYYY_MM_DD_HH_MM_SS.mp4    (RTSP camera)

The extension follows the camera type. The object timestamp uses Asia/Kolkata.

Example:

cam2/2026/08/16/20/cam_2_2026_08_16_20_23_41.ts

Do not casually change this naming scheme because the downloader app in downloader/ (and previously a separate project) reads these objects and joins them into videos.

Archive on the USB disk

Full-quality clips of every RTSP camera's main stream are kept on a USB
disk attached to the Pi (ArchiveService). The disk is a laptop drive, so it
is not left spinning: clips are buffered in RAM
(archive_buffer_directory, under /dev/shm) and moved to the disk in
batches, every archive_flush_minutes or sooner when the buffer passes
archive_buffer_limit_mb. One batch is:

mount the disk (this spins it up)
  -> copy every waiting clip to <archive_directory>/camN/YYYY/MM/DD/,
     same file names as the cloud copy, fsync, verify size, delete from RAM
  -> while free space < archive_min_free_gb: delete the oldest day
     (all cameras) in one go
  -> read the disk's SMART counters for the UI
  -> sync, unmount, park the disk (hdparm -y)

There is no day limit; the disk fills and the oldest day goes. If the disk
is unplugged or will not mount, clips wait in RAM up to the buffer limit and
the oldest waiting clip is dropped beyond it, so RAM never fills. On a
clean shutdown a final batch runs so waiting clips are not lost.

One-time Pi setup: scripts/install_archive.sh. It rewrites the /etc/fstab
line for /mnt/cctv with "noauto,user" (not mounted at boot, the service
user may mount it), adds a sudoers rule for exactly the park and SMART
commands on /dev/disk/by-label/cctv, installs hdparm and smartmontools,
and makes the system journal persistent (200 MB cap). The disk itself is
formatted ext4 with the label "cctv" by hand.

This enclosure (Toshiba MQ01UBD100) parks with hdparm -y, not with the
SCSI stop command, and SMART needs "-d sat,16". The disk's state is shown in
the CCTV tab: parked or awake, waiting clips, last batch, free space,
oldest day, SMART counters.

GET  /api/cameras/archive         status
POST /api/cameras/archive/flush   run one batch now
GET  /api/cameras/archive/cameras, /days?camera=, /clips?camera=&day=, /file?key=
                                  browse and fetch clips on the disk (for the
                                  downloader). Browsing wakes the disk; it is
                                  parked again 3 minutes after the last request,
                                  and a batch never parks it while browsing.

Live view in the browser (go2rtc)

Browsers cannot play RTSP. The Live View tab uses go2rtc, a separate
systemd service on the Pi, which takes each camera's RTSP stream and
serves it over WebRTC (MSE as fallback) without re-encoding. It connects
to a camera only while someone is watching, so recording is unaffected.

Install it once on the Pi:

bash scripts/install_go2rtc.sh

The script downloads a pinned go2rtc release, installs the go2rtc
service running as the same user as the backend, and adds a sudoers
rule allowing exactly "systemctl restart go2rtc" without a password.

The backend owns go2rtc's config file, runtime/go2rtc.yaml. It rewrites
it from runtime/cameras.json on every camera settings save and on
backend start, and restarts go2rtc when the file changed. Each RTSP
camera becomes a go2rtc stream named by its key (cam1, cam2, ...). The
main stream (stream_url) is served as "camN" and, when the camera has a
sub_stream_url, the sub stream as "camN_sub". The Live View tab has a
Main / Sub switch so both can be compared. ESP32-CAM cameras are not
served.

The browser player is go2rtc's video-rtc.js web component, vendored in
frontend/src/vendor (MIT) so it loads from the Pi's own page. It
connects to ws://<pi>:1984/api/ws?src=camN. H.265 plays in Safari and
in Chrome on Mac; for other devices set the camera's sub stream to
H.264. go2rtc listens on port 1984 on all interfaces with no login.

Camera API

GET  /api/cameras/settings
PUT  /api/cameras/settings
GET  /api/cameras/preset/status
GET  /api/cameras/recording/status
POST /api/cameras/recording/start
POST /api/cameras/recording/stop
GET  /api/cameras/backblaze/accounts
PUT  /api/cameras/backblaze/accounts
POST /api/cameras/backblaze/accounts/test
GET  /api/cameras/backblaze/rotation
GET  /api/cameras/archive
POST /api/cameras/archive/flush
GET  /api/cameras/archive/cameras
GET  /api/cameras/archive/days
GET  /api/cameras/archive/clips
GET  /api/cameras/archive/file
GET  /api/cameras/live
POST /api/cameras/live/sync

Changing camera settings is persistent, but recording-pipeline changes take effect the next time recording is started.

Frontend

The React UI uses tabbed navigation so the major control areas are not rendered as one long vertical page. The tab order is intentionally:

Relay Controls

CCTV Cameras

Panel Cleaning and Plant Watering

Automations

Tab labels use non-wrapping text. On a narrow screen the tab row scrolls horizontally rather than breaking long labels such as Panel Cleaning and Plant Watering. The underlying panels remain mounted while hidden so their existing state, polling, and unsaved UI state are not discarded when switching tabs.

The React UI provides:

backend health indication;

raw relay ON/OFF controls;

watering status, schedule, timing settings, start and safe-stop controls;

editable automation script panel;

CCTV settings and recording status;

per-camera configuration/status;

automatic Day/Night schedule configuration and locally recorded applied-preset status;

Backblaze account list, rotation status and upload settings;

recording start/stop controls.

The relay UI must continue to communicate relay-coil commands. It must not display an inferred appliance ON/OFF state.

Frontend development rule

Do not build the production frontend on the Raspberry Pi.

The normal workflow is on macOS:

cd frontend
nvm use
npm install        # or npm ci when appropriate
npm run dev        # local development

For a production frontend change:

cd frontend
nvm use
npm ci
npm run build

Then commit the generated:

frontend/dist/

and deploy it through Git to the Raspberry Pi.

FastAPI serves frontend/dist directly. No Node.js process is required on the Pi.

API summary

Health

GET /health

Returns:

{"status":"healthy"}

Relays

POST /api/relays/{relay_key}/on
POST /api/relays/{relay_key}/off

Watering

GET  /api/watering/settings
PUT  /api/watering/settings
GET  /api/watering/status
POST /api/watering/start
POST /api/watering/stop

Automations

GET  /api/automations
GET  /api/automations/{key}
PUT  /api/automations/{key}
POST /api/automations/{key}/restore
POST /api/automations/{key}/run

Cameras

GET  /api/cameras/settings
PUT  /api/cameras/settings
GET  /api/cameras/preset/status
GET  /api/cameras/recording/status
POST /api/cameras/recording/start
POST /api/cameras/recording/stop
GET  /api/cameras/backblaze/accounts
PUT  /api/cameras/backblaze/accounts
POST /api/cameras/backblaze/accounts/test
GET  /api/cameras/backblaze/rotation
GET  /api/cameras/archive
POST /api/cameras/archive/flush
GET  /api/cameras/archive/cameras
GET  /api/cameras/archive/days
GET  /api/cameras/archive/clips
GET  /api/cameras/archive/file
GET  /api/cameras/live
POST /api/cameras/live/sync

Raspberry Pi process management

The backend runs as one systemd service:

home-automation.service

systemd is used only for process lifecycle:

boot -> start Uvicorn
unexpected exit -> restart Uvicorn

Application scheduling remains inside Python.

Useful commands:

sudo systemctl status home-automation
sudo systemctl restart home-automation
sudo journalctl -u home-automation -f
sudo journalctl -u home-automation -n 100 --no-pager

The Uvicorn command installed by scripts/setup_pi.sh is conceptually:

.venv/bin/uvicorn home_automation.api.app:app \
    --host 0.0.0.0 \
    --port 8000

The service uses Restart=always and a short restart delay.

Fresh Raspberry Pi setup

For a new Raspberry Pi, first clone the repository:

mkdir -p ~/workspace
cd ~/workspace
git clone git@github.com:vishalvisd/home-automation.git
cd home-automation

Then run:

bash scripts/setup_pi.sh

Do not run the script itself with sudo; it invokes sudo only for the operations that require it.

The setup script installs the required operating-system packages (GStreamer and ffmpeg), installs uv if missing, creates/synchronizes the Python environment, verifies required GStreamer elements, installs the systemd unit, enables it at boot, and starts the service.

SETUP_PI.md is intentionally kept short; this README is the detailed architecture reference.

Normal Raspberry Pi deployment/update

After code has been committed and pushed from the development machine, use:

cd ~/workspace/home-automation
bash scripts/update_pi.sh

The update script is designed to prevent partial deployments. It performs the equivalent of:

sudo credential check
git pull --ff-only
uv sync --frozen
restart home-automation service
verify systemd service is active
verify http://127.0.0.1:8000/health
report revision / show logs on failure

This step is important whenever Python dependencies change. A Git pull alone is not sufficient because the Pi's .venv may otherwise be missing a newly committed dependency.

Logging and diagnostics

Application logs are routed through the Uvicorn logging handlers and are available via systemd journal.

Live logs:

sudo journalctl -u home-automation -f

Recent logs:

sudo journalctl -u home-automation -n 100 --no-pager

Expected useful CCTV messages include:

Camera recorder started: Camera 1
Camera stream connected: Camera 1
Camera stream disconnected [Camera 2]: ...
Camera stream reconnected: Camera 2
Camera segment window elapsed [Camera 2]: ... frame(s) received
Camera segment created [Camera 2]: ...
Camera upload started [Camera 2]: ...
Camera upload successful [Camera 2]: ...
Camera segment deleted [Camera 2]: ...

A stream disconnect/reconnect is normal on the current network. A repeated recorder failure is a different condition and should be investigated separately.

High-frequency polling endpoints such as camera/watering status are intentionally suppressed from normal access logging so useful operational events remain visible.

Development notes for future changes

Do not introduce appliance-state tracking

The system intentionally does not know whether the router, RO unit, cameras, valves, or pump are physically powered/open/running. It only knows which relay command was issued.

This prevents incorrect state assumptions after reboot, manual electrical intervention, network failure, or normally closed wiring.

Do not hide normally closed semantics

For the router and RO purifier:

relay OFF -> device receives power
relay ON  -> device power is disconnected

For the camera line:

relay OFF -> camera line has no power
relay ON  -> camera line receives power

These differences are hardware facts, not bugs to normalize away in the backend.

Do not build the frontend on the Pi

Production frontend builds belong on the Mac development machine. Commit frontend/dist.

Keep application schedules in Python

Avoid adding cron jobs or systemd timers for watering or other application workflows unless there is a specific architectural reason.

Preserve camera-provider abstraction

New cloud providers should implement the CameraStorageProvider contract. Do not embed provider-specific upload logic back into CameraRecorder.

Preserve single-attempt camera uploads

Do not add a retry queue unless the project requirement is explicitly changed. Current requirement is:

attempt once -> log -> delete -> continue

Do not auto-restart shared camera power for one failed camera

The ESP32 cameras share the camera power relay. The stream/recorder software is expected to reconnect independently. Automatically cycling the shared line because Camera 2 is unhealthy would unnecessarily interrupt Camera 1.

Known pending work

The core Day/Night preset automation and UI schedule configuration are implemented. The remaining camera item below is intentionally not treated as an active feature.

Legacy/planned camera health settings

The settings model currently also contains:

health_check_seconds
restart_after_failures

The current resilient design already handles HTTP stream reconnects in CameraStreamSource and recorder-pipeline recovery in CameraRecorderService. These two settings should not be assumed to drive a separate camera-power health-recovery feature unless that feature is deliberately implemented later.

Quick orientation for a new developer or LLM

If making a change, first identify which layer owns it:

Physical relay behavior
    -> config/relays.py + RelayManager

Watering sequence
    -> WateringService

Watering schedule
    -> WateringSchedulerService

Editable scripts
    -> AutomationScriptService + automation_templates/

ESP32-CAM HTTP reliability
    -> CameraStreamSource

ESP32-CAM encoding / segment creation
    -> CameraRecorder

RTSP camera recording (ffmpeg)
    -> RtspFfmpegRecorder

Recorder process recovery
    -> CameraRecorderService

Cloud upload lifecycle
    -> CameraUploadService

Backblaze API details
    -> BackblazeB2StorageProvider

Persistent camera settings
    -> CameraSettingsService / runtime/cameras.json

Camera Day/Night preset scheduling and state
    -> CameraPresetService / runtime/camera_preset_state.json

Frontend controls and tab navigation
    -> frontend/src

When modifying CCTV code, preserve the separation between the unreliable HTTP stream and the long-lived recording pipeline. This separation is what allows the system to keep useful video despite intermittent camera/network failures.

When modifying hardware behavior, always check the relay contact wiring before interpreting ON/OFF as appliance power.

Closing state of this iteration

The core goals of this iteration are complete:

relay control
watering + scheduler
editable automations
systemd backend lifecycle
safe update workflow
ESP32-CAM capture
unstable-stream reconnects
wall-clock CCTV segments
RAM-backed recording
Backblaze B2 upload
provider abstraction
single-attempt upload/delete policy
automatic Day/Night camera presets
tabbed frontend navigation

The current iteration has no deliberately deferred Day/Night UI/control work.